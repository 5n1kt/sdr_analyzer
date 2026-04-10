# workers/fft_processor_zerocopy.py
# -*- coding: utf-8 -*-
#
# CORRECCIONES APLICADAS
# ──────────────────────
# 1. [CRÍTICO] KeyError si fft_size no está precalculado.
#    _process_buffer() accedía a self.windows[self.fft_size][self.window_type]
#    sin verificar que el tamaño existiera en el caché. Cualquier fft_size
#    personalizado (ej. 3000) lanzaba KeyError sin mensaje útil y el hilo
#    moría silenciosamente. FIX: _get_window() calcula la ventana on-demand
#    si el tamaño no está en el caché y la añade para reutilización futura.
#
# 2. [CRÍTICO] Race condition en update_settings() vs run().
#    self.fft_accum y self.fft_size se modifican desde el hilo principal
#    (update_settings) mientras run() los lee/escribe en el hilo worker.
#    Sin protección, run() puede leer un fft_size actualizado pero un
#    fft_accum del tamaño anterior → crash por shape mismatch.
#    FIX: _settings_lock (threading.Lock) protege fft_size, fft_accum
#    y window_type. _process_buffer() adquiere el lock solo para
#    copiar los parámetros al inicio de cada frame (impacto mínimo).
#
# 3. [CRÍTICO] Buffer liberado ANTES de procesar la FFT.
#    En el loop original: get_read_buffer → process_buffer → release_read.
#    Si _process_buffer() tardaba varios ms, el buffer permanecía en
#    estado READING todo ese tiempo, bloqueando ese slot para el IQProcessor.
#    FIX: release_read se llama INMEDIATAMENTE después de copiar los datos,
#    antes de la FFT. Se trabaja sobre una copia local del segmento.
#
# 4. [POTENCIAL] window_type case-sensitive sin fallback.
#    Si el usuario pasaba 'hann' (minúscula) o 'HANN' se lanzaba KeyError
#    porque el caché usa claves con mayúscula inicial ('Hann').
#    FIX: _get_window() normaliza el nombre con .capitalize().
#
# 5. [POTENCIAL] fft_accum con dtype float32 recibe potencia float64.
#    np.abs(fft_segment)**2 produce float64. np.add(..., out=fft_accum)
#    hace un downcast silencioso a float32, perdiendo precisión en señales
#    débiles (< -80 dBFS). FIX: acumulador interno en float64, conversión
#    a float32 solo al emitir.
#
# 6. [POTENCIAL] terminate() en stop() puede dejar un buffer en READING.
#    Si el hilo es terminado forzosamente mientras tiene un buffer en
#    estado BUFFER_READING, ese slot queda bloqueado para siempre.
#    FIX: se aumenta el timeout de wait() a 2000ms antes de terminate(),
#    y se documenta que el ring buffer debe resetearse tras terminate().
#
# 7. [POTENCIAL] QElapsedTimer creado en hilo main, usado en hilo worker.
#    QElapsedTimer no es thread-safe para operaciones start/elapsed entre
#    hilos distintos. FIX: se reemplaza con time.perf_counter() que es
#    thread-safe y de alta resolución.
#
# 8. [LIMPIEZA] fft_data_ready sin control de backpressure.
#    Si la UI procesa frames más lento que MIN_UPDATE_MS, la cola de
#    eventos Qt crece sin límite. FIX: flag _frame_pending que descarta
#    la emisión si el frame anterior no fue procesado aún.

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
import logging
import time
import threading

from workers.shared_buffer import IQRingBuffer


class FFTProcessorZeroCopy(QThread):
    """
    Procesador FFT que lee del ring buffer y emite espectros de potencia.

    El buffer se libera inmediatamente tras copiar los datos, minimizando
    el tiempo que cada slot permanece en estado READING.
    """

    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    fft_data_ready = pyqtSignal(np.ndarray)
    stats_updated  = pyqtSignal(dict)

    # -----------------------------------------------------------------------
    # CONSTANTES
    # -----------------------------------------------------------------------
    FLOOR_DB       = -120.0
    EPSILON        = 1e-12
    MAX_FPS        = 30
    MIN_UPDATE_MS  = 33    # ~30 fps máximo hacia la UI

    # Tamaños de FFT precalculados en el caché inicial
    _PRECALC_SIZES = [256, 512, 1024, 2048, 4096, 8192, 16384]

    # -----------------------------------------------------------------------
    # CONSTRUCTOR
    # -----------------------------------------------------------------------
    def __init__(self, ring_buffer: IQRingBuffer, sample_rate: float = 2e6):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        self.ring_buffer = ring_buffer

        # Estado del hilo
        self.is_running = False
        self._stop_flag = False

        # Parámetros FFT (protegidos por _settings_lock)
        # CORRECCIÓN 2: lock para sincronizar update_settings() / run()
        self._settings_lock = threading.Lock()
        self.fft_size    = 1024
        self.window_type = 'Hann'
        self.averaging   = 1
        self.overlap     = 50
        self.sample_rate = sample_rate

        # Caché de ventanas
        self.windows = self._precompute_windows()

        # CORRECCIÓN 5: acumulador en float64 para precisión
        self.fft_accum = np.zeros(self.fft_size, dtype=np.float64)

        # Control de framerate
        # CORRECCIÓN 7: time.perf_counter() en lugar de QElapsedTimer
        self._last_update_time = 0.0

        # CORRECCIÓN 8: flag de backpressure
        self._frame_pending = False

        # Estadísticas
        self.stats = {
            'fft_frames':          0,
            'buffers_processed':   0,
            'skipped_buffers':     0,
            'dropped_frames':      0,
            'avg_process_time_ms': 0.0,
        }

        self.logger.info("✅ FFTProcessorZeroCopy creado")

    # -----------------------------------------------------------------------
    # QTHREAD — LOOP PRINCIPAL
    # -----------------------------------------------------------------------
    def run(self):
        """Loop principal: lee buffers IQ, calcula FFT y emite resultados."""
        self.is_running = True
        self._stop_flag = False
        self.logger.info("🚀 FFTProcessorZeroCopy iniciado")

        while not self._stop_flag:
            try:
                result = self.ring_buffer.get_read_buffer(timeout_ms=100)
                if result is None:
                    continue

                iq_buffer, buffer_idx = result

                # CORRECCIÓN 3: copiar datos y liberar el buffer ANTES
                # de procesar la FFT para minimizar el tiempo en READING.
                iq_copy = iq_buffer.copy()
                self.ring_buffer.release_read(buffer_idx)
                self.stats['buffers_processed'] += 1

                # Procesar FFT sobre la copia local
                t0         = time.perf_counter()
                fft_result = self._process_buffer(iq_copy)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0

                self._update_avg_time(elapsed_ms)
                self._send_result_if_needed(fft_result)

                if self.stats['buffers_processed'] % 100 == 0:
                    self.stats_updated.emit(self.stats.copy())

            except Exception as exc:
                if not self._stop_flag:
                    self.logger.error(f"❌ Error en FFTProcessor: {exc}")

        self.is_running = False
        self.logger.info("⏹️ FFTProcessorZeroCopy detenido")

    # -----------------------------------------------------------------------
    # CONTROL PÚBLICO
    # -----------------------------------------------------------------------
    def update_settings(self, settings: dict) -> bool:
        """
        Actualiza parámetros FFT de forma thread-safe.

        Returns
        -------
        True si se cambió fft_size (el caller puede decidir reiniciar).
        """
        restart_needed = False

        # CORRECCIÓN 2: adquirir lock antes de modificar parámetros
        with self._settings_lock:
            if 'fft_size' in settings and settings['fft_size'] != self.fft_size:
                self.fft_size  = settings['fft_size']
                # CORRECCIÓN 5: float64
                self.fft_accum = np.zeros(self.fft_size, dtype=np.float64)
                restart_needed = True

            if 'window' in settings:
                self.window_type = settings['window']

            if 'averaging' in settings:
                self.averaging = max(1, int(settings['averaging']))

            if 'overlap' in settings:
                self.overlap = max(0, min(99, int(settings['overlap'])))

            if 'sample_rate' in settings:
                self.sample_rate = float(settings['sample_rate'])

        return restart_needed

    def stop(self, immediate: bool = False):
        """
        Detiene el procesamiento.

        CORRECCIÓN 6: timeout aumentado a 2000ms antes de terminate().
        Si terminate() es necesario, el caller debe llamar a
        ring_buffer.reset() para liberar posibles slots en READING.
        """
        self._stop_flag = True

        if not immediate:
            if not self.wait(2000):
                self.logger.warning(
                    "⚠️ FFTProcessor no respondió en 2s — forzando terminación"
                )
                self.terminate()
                self.wait(200)

        self.logger.info("⏹️ FFTProcessorZeroCopy detenido")

    # -----------------------------------------------------------------------
    # PRIVADOS — VENTANAS
    # -----------------------------------------------------------------------
    def _precompute_windows(self) -> dict:
        """Pre-calcula ventanas para los tamaños más comunes."""
        windows = {}
        for size in self._PRECALC_SIZES:
            windows[size] = self._build_window_set(size)
        return windows

    def _build_window_set(self, size: int) -> dict:
        """Construye el conjunto de ventanas para un tamaño dado."""
        return {
            'Rectangular': np.ones(size,                  dtype=np.float32),
            'Hann':        np.hanning(size).astype(np.float32),
            'Hamming':     np.hamming(size).astype(np.float32),
            'Blackman':    np.blackman(size).astype(np.float32),
            'Kaiser':      np.kaiser(size, 14).astype(np.float32),
        }

    def _get_window(self, fft_size: int, window_type: str) -> np.ndarray:
        """
        Retorna la ventana solicitada, calculándola on-demand si es necesario.

        CORRECCIÓN 1: si fft_size no está en el caché, se calcula y
        se añade para evitar recalcular en frames futuros.

        CORRECCIÓN 4: normaliza el nombre con capitalize() para aceptar
        'hann', 'HANN', 'Hann' indistintamente.
        """
        if fft_size not in self.windows:
            self.logger.info(
                f"⚙️ Calculando ventanas para fft_size={fft_size} (tamaño no precalculado)"
            )
            self.windows[fft_size] = self._build_window_set(fft_size)

        normalized_type = window_type.capitalize()
        window_set      = self.windows[fft_size]

        if normalized_type not in window_set:
            self.logger.warning(
                f"⚠️ Ventana '{window_type}' desconocida, usando Hann"
            )
            normalized_type = 'Hann'

        return window_set[normalized_type]

    # -----------------------------------------------------------------------
    # PRIVADOS — PROCESAMIENTO
    # -----------------------------------------------------------------------
    def _process_buffer(self, iq_data: np.ndarray):
        """
        Calcula el espectro de potencia en dBFS de un bloque IQ.

        Toma una instantánea thread-safe de los parámetros al inicio
        del frame para que update_settings() no cause shape mismatches.

        Returns
        -------
        np.ndarray float32 de longitud fft_size, o None si el buffer
        es demasiado pequeño.
        """
        # CORRECCIÓN 2: snapshot atómico de parámetros
        with self._settings_lock:
            fft_size    = self.fft_size
            window_type = self.window_type
            averaging   = self.averaging
            overlap     = self.overlap
            # Reusar el acumulador si el tamaño coincide;
            # de lo contrario, crear uno temporal (no debería ocurrir
            # si update_settings() se llamó correctamente)
            if self.fft_accum.size == fft_size:
                accum = self.fft_accum
            else:
                accum = np.zeros(fft_size, dtype=np.float64)

        if len(iq_data) < fft_size:
            return None

        # CORRECCIÓN 1: _get_window() nunca lanza KeyError
        window = self._get_window(fft_size, window_type)

        step = max(1, int(fft_size * (1 - overlap / 100)))
        max_segments = (len(iq_data) - fft_size) // step + 1
        num_segments = max(1, min(averaging, max_segments))

        accum.fill(0.0)

        for i in range(num_segments):
            start   = i * step
            segment = iq_data[start : start + fft_size] * window
            # np.fft.fft sobre complex64 produce complex128
            fft_seg  = np.fft.fftshift(np.fft.fft(segment))
            # CORRECCIÓN 5: acumulamos en float64 (accum ya es float64)
            accum   += np.abs(fft_seg) ** 2

        power            = accum / num_segments
        window_power     = np.sum(window.astype(np.float64) ** 2)
        power_normalized = power / (window_power * fft_size)

        power_normalized = np.maximum(power_normalized, self.EPSILON)
        power_dbfs       = 10.0 * np.log10(power_normalized)
        np.maximum(power_dbfs, self.FLOOR_DB, out=power_dbfs)

        # CORRECCIÓN 5: conversión a float32 solo al final
        return power_dbfs.astype(np.float32)

    def _update_avg_time(self, process_time_ms: float):
        """Actualiza la media exponencial del tiempo de procesamiento."""
        self.stats['avg_process_time_ms'] = (
            0.95 * self.stats['avg_process_time_ms'] +
            0.05 * process_time_ms
        )

    def _send_result_if_needed(self, fft_result):
        """
        Emite el resultado si ha pasado suficiente tiempo desde el último frame.

        CORRECCIÓN 7: usa time.perf_counter() en lugar de QElapsedTimer.
        CORRECCIÓN 8: descarta el frame si el anterior no fue procesado
        aún (backpressure básico para proteger la cola de eventos Qt).
        """
        if fft_result is None:
            return

        now_ms = time.perf_counter() * 1000.0

        if (now_ms - self._last_update_time) >= self.MIN_UPDATE_MS:
            if self._frame_pending:
                # Frame anterior aún en la cola — descartar este
                self.stats['dropped_frames'] += 1
                self.stats['skipped_buffers'] += 1
                return

            self._frame_pending    = True
            self._last_update_time = now_ms
            self.stats['fft_frames'] += 1

            # La señal Qt se encola en el event loop del hilo principal.
            # El receptor debe llamar a _on_fft_done() o equivalente
            # para limpiar _frame_pending cuando termine de renderizar.
            self.fft_data_ready.emit(fft_result)
        else:
            self.stats['skipped_buffers'] += 1

    def on_frame_consumed(self):
        """
        Llamar desde el slot receptor (hilo UI) cuando se termina de
        renderizar el frame. Habilita la emisión del siguiente frame.

        Conectar en el controller:
            self.main.fft_processor.fft_data_ready.connect(
                lambda data: (self.main.update_spectrum(data),
                              self.main.fft_processor.on_frame_consumed())
            )
        """
        self._frame_pending = False

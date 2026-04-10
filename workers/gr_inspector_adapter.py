# workers/gr_inspector_adapter.py
# -*- coding: utf-8 -*-
#
# VERSIÓN CORREGIDA - Cambios respecto a la versión anterior:
#
#  1. CFARDetector reescrito:
#     - Espectro normalizado correctamente (dBFS en vez de potencia cruda)
#     - BW medido a -3dB real con interpolación lineal (no con random)
#     - Frecuencia central del pico calculada sobre el espectro (offset real)
#     - Ruido estimado con mediana en lugar de percentil 10 (más robusto)
#     - find_peaks con prominence para evitar detecciones en el lóbulo lateral
#     - Múltiples picos detectados por bloque (antes solo el más fuerte)
#
#  2. GRInspectorAdapter:
#     - accum_buffer reemplazado por collections.deque (sin np.concatenate en loop)
#     - _process_with_gr_inspector ya no llama al simulado; usa CFAR real
#     - Usa SignalClassifier para clasificar (elimina if/elif duplicado)
#     - scan_timer debe ser mínimo 500ms (advertencia en log si es menor)
#     - progress emite índice real de frecuencia para barra de progreso correcta
#
# =======================================================================
# IMPORTS
# =======================================================================
import numpy as np
import time
import logging
from collections import deque
from scipy.signal import find_peaks, windows as sp_windows

from PyQt5.QtCore import QThread, pyqtSignal

# Importar el clasificador que ya existía en el proyecto
try:
    from utils.signal_classifier import SignalClassifier
    CLASSIFIER_AVAILABLE = True
except ImportError:
    CLASSIFIER_AVAILABLE = False

# Intentar importar gr_inspector
try:
    import gr_inspector
    GR_INSPECTOR_AVAILABLE = True
except ImportError:
    GR_INSPECTOR_AVAILABLE = False


# =======================================================================
# DETECTOR CFAR — IMPLEMENTACIÓN REAL
# =======================================================================
class CFARDetector:
    """
    Detector CFAR (Constant False Alarm Rate) para señales IQ.

    Correcciones sobre la versión anterior
    ─────────────────────────────────────
    • Espectro en dBFS (relativo a la saturación del ADC del bladeRF).
    • BW medido a −3 dB con interpolación submuestra (resultado en Hz reales).
    • Frecuencia central del pico incluye el offset en la ventana FFT.
    • Ruido estimado con mediana de los bins más bajos (más robusto que percentil 10).
    • find_peaks usa `prominence` para evitar falsas alarmas en lóbulos laterales.
    • Retorna LISTA de detecciones por bloque (no solo la más fuerte).
    """

    # Ventana pre-calculada para el tamaño FFT más común
    _WINDOW_CACHE: dict = {}

    def __init__(
        self,
        sample_rate: float = 2e6,
        threshold_db: float = 6.0,
        min_bw_hz: float = 10e3,
        max_bw_hz: float = 10e6,
        fft_size: int = 4096,
        guard_cells: int = 4,
        training_cells: int = 16,
    ):
        self.sample_rate    = sample_rate
        self.threshold_db   = threshold_db   # SNR mínima sobre el ruido
        self.min_bw_hz      = min_bw_hz
        self.max_bw_hz      = max_bw_hz
        self.fft_size       = fft_size
        self.guard_cells    = guard_cells
        self.training_cells = training_cells
        self.logger         = logging.getLogger(__name__)

        # Histórico de piso de ruido (promedio móvil de 20 bloques)
        self._noise_history: deque = deque(maxlen=20)
        self.noise_floor_db: float = -100.0

        # Resolución espectral
        self._freq_per_bin: float = sample_rate / fft_size

    # ------------------------------------------------------------------
    # API PÚBLICA
    # ------------------------------------------------------------------

    def update_sample_rate(self, sample_rate: float) -> None:
        self.sample_rate    = sample_rate
        self._freq_per_bin  = sample_rate / self.fft_size
        self._noise_history.clear()

    def process_block(
        self, iq_data: np.ndarray, center_freq_mhz: float
    ) -> list:
        """
        Procesa un bloque IQ y devuelve una lista (posiblemente vacía)
        de diccionarios de detección.

        Parámetros
        ----------
        iq_data         : array complejo normalizado (|max| ≈ 1 para SC16Q11/2048)
        center_freq_mhz : frecuencia central del SDR en MHz

        Retorna
        -------
        list[dict]  — cada dict es compatible con SignalDetectorWidget.add_detection()
        """
        if len(iq_data) < self.fft_size:
            return []

        try:
            # 1. Calcular espectro en dBFS
            spectrum_dbfs = self._compute_spectrum(iq_data)

            # 2. Estimar piso de ruido con mediana de bins más bajos
            self._update_noise_floor(spectrum_dbfs)

            # 3. Detectar picos sobre el umbral
            peaks = self._find_signal_peaks(spectrum_dbfs)

            # 4. Construir detecciones
            detections = []
            for peak_bin in peaks:
                det = self._build_detection(
                    spectrum_dbfs, peak_bin, center_freq_mhz
                )
                if det is not None:
                    detections.append(det)

            return detections

        except Exception as exc:
            self.logger.error(f"CFARDetector.process_block error: {exc}", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # MÉTODOS PRIVADOS
    # ------------------------------------------------------------------

    def _get_window(self, size: int) -> np.ndarray:
        """Devuelve la ventana Blackman-Harris de 'size' muestras (cacheada)."""
        if size not in CFARDetector._WINDOW_CACHE:
            CFARDetector._WINDOW_CACHE[size] = sp_windows.blackmanharris(size).astype(np.float32)
        return CFARDetector._WINDOW_CACHE[size]

    def _compute_spectrum(self, iq_data: np.ndarray) -> np.ndarray:
        """
        Devuelve el espectro de potencia en dBFS usando la ventana
        Blackman-Harris y promediado de segmentos solapados (Welch simplificado).

        El resultado está normalizado a 0 dBFS = nivel de saturación del ADC
        (bladeRF SC16Q11 → 2048 pasos → normalización ya hecha en bytes_to_complex).
        """
        win     = self._get_window(self.fft_size)
        step    = self.fft_size // 2          # 50 % overlap
        n_seg   = (len(iq_data) - self.fft_size) // step + 1
        n_seg   = min(n_seg, 8)               # máximo 8 segmentos para no bloquear el hilo

        accum = np.zeros(self.fft_size, dtype=np.float64)
        win_power = np.sum(win ** 2)

        for i in range(n_seg):
            seg    = iq_data[i * step : i * step + self.fft_size]
            fft_v  = np.fft.fftshift(np.fft.fft(seg * win))
            accum += np.abs(fft_v) ** 2

        # Promediar y normalizar a dBFS
        power_norm = accum / (n_seg * win_power * self.fft_size)
        # Clamp para evitar log(0)
        power_norm = np.maximum(power_norm, 1e-12)
        return 10.0 * np.log10(power_norm).astype(np.float32)

    def _update_noise_floor(self, spectrum_dbfs: np.ndarray) -> None:
        """
        Estima el piso de ruido usando la mediana del 30 % de bins más bajos.
        Más robusto que percentil10 ante señales con BW grande.
        """
        sorted_bins  = np.sort(spectrum_dbfs)
        cutoff       = max(1, len(sorted_bins) * 30 // 100)
        noise_est    = float(np.median(sorted_bins[:cutoff]))
        self._noise_history.append(noise_est)
        self.noise_floor_db = float(np.mean(self._noise_history))

    def _find_signal_peaks(self, spectrum_dbfs: np.ndarray) -> np.ndarray:
        """
        Detecta picos en el espectro con find_peaks usando:
        - altura mínima = noise_floor + threshold_db
        - prominencia mínima = threshold_db / 2  (evita lóbulos laterales)
        - distancia mínima = bins que corresponden a min_bw_hz
        """
        min_height    = self.noise_floor_db + self.threshold_db
        min_dist_bins = max(2, int(self.min_bw_hz / self._freq_per_bin))
        min_prom      = self.threshold_db / 2.0

        peaks, _ = find_peaks(
            spectrum_dbfs,
            height      = min_height,
            distance    = min_dist_bins,
            prominence  = min_prom,
        )
        return peaks

    def _measure_bandwidth_3db(
        self, spectrum_dbfs: np.ndarray, peak_bin: int
    ) -> tuple[float, int, int]:
        """
        Mide el BW a −3 dB con interpolación lineal entre bins.

        Retorna (bandwidth_hz, left_bin, right_bin).
        """
        peak_power  = float(spectrum_dbfs[peak_bin])
        half_power  = peak_power - 3.0
        n           = len(spectrum_dbfs)

        # Buscar borde izquierdo
        left_bin = peak_bin
        while left_bin > 0 and spectrum_dbfs[left_bin] > half_power:
            left_bin -= 1

        # Interpolación lineal izquierda
        if left_bin < peak_bin:
            y0, y1 = float(spectrum_dbfs[left_bin]), float(spectrum_dbfs[left_bin + 1])
            if abs(y1 - y0) > 1e-6:
                left_frac = (half_power - y0) / (y1 - y0)
            else:
                left_frac = 0.0
            left_exact = left_bin + left_frac
        else:
            left_exact = float(left_bin)

        # Buscar borde derecho
        right_bin = peak_bin
        while right_bin < n - 1 and spectrum_dbfs[right_bin] > half_power:
            right_bin += 1

        # Interpolación lineal derecha
        if right_bin > peak_bin:
            y0, y1 = float(spectrum_dbfs[right_bin - 1]), float(spectrum_dbfs[right_bin])
            if abs(y1 - y0) > 1e-6:
                right_frac = (half_power - y0) / (y1 - y0)
            else:
                right_frac = 1.0
            right_exact = (right_bin - 1) + right_frac
        else:
            right_exact = float(right_bin)

        bw_hz = (right_exact - left_exact) * self._freq_per_bin
        # Aplicar límites configurados
        bw_hz = float(np.clip(bw_hz, self.min_bw_hz, self.max_bw_hz))
        return bw_hz, left_bin, right_bin

    def _peak_bin_to_freq_offset_hz(self, peak_bin: int) -> float:
        """
        Convierte un bin del espectro FFT-shifted al offset en Hz respecto
        a la frecuencia central del SDR.

        Con fftshift: bin 0 → −SR/2, bin N/2 → 0, bin N−1 → +SR/2 − freq_res
        """
        return (peak_bin - self.fft_size // 2) * self._freq_per_bin

    def _build_detection(
        self,
        spectrum_dbfs: np.ndarray,
        peak_bin: int,
        center_freq_mhz: float,
    ) -> dict | None:
        """
        Construye el diccionario de detección para un pico dado.
        Retorna None si el BW está fuera del rango configurado.
        """
        peak_power_dbfs = float(spectrum_dbfs[peak_bin])
        snr_db          = peak_power_dbfs - self.noise_floor_db

        # Medir BW real
        bw_hz, _, _ = self._measure_bandwidth_3db(spectrum_dbfs, peak_bin)

        # Filtrar por BW configurado
        if bw_hz < self.min_bw_hz or bw_hz > self.max_bw_hz:
            return None

        # Frecuencia central del pico (SDR center + offset del bin)
        offset_hz       = self._peak_bin_to_freq_offset_hz(peak_bin)
        peak_freq_mhz   = center_freq_mhz + offset_hz / 1e6

        # Clasificar usando SignalClassifier si está disponible
        if CLASSIFIER_AVAILABLE:
            sig_type, type_info = SignalClassifier.classify(bw_hz)
            type_name  = type_info['name']
            type_color = type_info['color']
        else:
            # Fallback inline
            bw_khz = bw_hz / 1000
            if bw_khz < 200:
                sig_type, type_name, type_color = "NARROW", "📻 Narrow", "#00ff00"
            elif bw_khz < 2000:
                sig_type, type_name, type_color = "MEDIUM", "📺 Medium", "#ffff00"
            else:
                sig_type, type_name, type_color = "WIDE",   "📡 Wide",   "#ff8800"

        return {
            'center_freq_mhz': round(peak_freq_mhz, 4),
            'bandwidth_hz':    bw_hz,
            'bandwidth_khz':   bw_hz / 1000,
            'power_db':        peak_power_dbfs,
            'snr_db':          snr_db,
            'signal_type':     sig_type,
            'type_name':       type_name,
            'type_color':      type_color,
            'confidence':      float(np.clip(0.5 + snr_db / 30.0, 0.1, 0.99)),
            'timestamp':       time.time(),
            'simulated':       False,
            'detector':        'cfar',
            'noise_floor_db':  self.noise_floor_db,
        }


# =======================================================================
# ADAPTADOR GR-INSPECTOR — CORRECCIONES APLICADAS
# =======================================================================
class GRInspectorAdapter(QThread):
    """
    Adaptador que consume datos del ring buffer y los procesa con CFAR.

    Cambios sobre la versión anterior
    ──────────────────────────────────
    • accum_buffer: usa deque de bloques en vez de np.concatenate continuo.
    • process_block devuelve lista → se emiten TODAS las detecciones del bloque.
    • _process_with_gr_inspector ya no llama al simulado ficticio.
    • Se registra advertencia si scan_timer < 500 ms (tiempo insuficiente).
    • stats_updated emite también el progreso real (freq_index / total_freqs).
    """

    # Señales
    detection_result  = pyqtSignal(dict)
    inspector_ready   = pyqtSignal(bool)
    stats_updated     = pyqtSignal(int, int)       # (muestras, detecciones)
    scan_progress     = pyqtSignal(int, int)        # (índice actual, total)  ← NUEVO

    values_updated = pyqtSignal(float, float)  # (threshold, noise_floor)

    # Constantes
    TARGET_BUFFER_SIZE  = 131072    # ~65 ms @ 2 MSPS
    MIN_SCAN_INTERVAL   = 500       # ms recomendados por frecuencia
    DEFAULT_THRESHOLD   = 6.0       # dB SNR mínima
    DEFAULT_MIN_BW      = 10e3      # 10 kHz
    DEFAULT_MAX_BW      = 10e6      # 10 MHz

    def __init__(self, ring_buffer, sample_rate: float = 2e6):
        super().__init__()
        self.logger       = logging.getLogger(__name__)
        self.ring_buffer  = ring_buffer
        self.sample_rate  = sample_rate

        # Estado de hilo
        self.is_running   = False
        self._stop_flag   = False
        self._pause_flag  = False
        self.current_freq_mhz  = 0.0
        self.freq_index        = 0
        self.total_freqs       = 0

        # ── Buffer de acumulación eficiente ──────────────────────────────
        # Guardamos bloques completos en una deque; sólo concatenamos
        # cuando tenemos suficientes muestras. Evita el O(n²) del append.
        self._block_queue:  deque = deque()
        self._queued_samples: int = 0

        # Configuración
        self.threshold_db = self.DEFAULT_THRESHOLD
        self.min_bw_hz    = self.DEFAULT_MIN_BW
        self.max_bw_hz    = self.DEFAULT_MAX_BW

        # Estadísticas
        self.samples_processed  = 0
        self.detections_found   = 0
        self._last_log_time     = time.time()
        self._last_stats_time   = time.time()

        # Detector CFAR
        self.cfar = CFARDetector(
            sample_rate   = sample_rate,
            threshold_db  = self.threshold_db,
            min_bw_hz     = self.min_bw_hz,
            max_bw_hz     = self.max_bw_hz,
        )

        self.gr_inspector_available = GR_INSPECTOR_AVAILABLE
        self.logger.info(
            f"✅ GRInspectorAdapter creado — "
            f"gr-inspector: {self.gr_inspector_available}, "
            f"CFAR sample_rate: {sample_rate/1e6:.1f} MSPS"
        )

    # ------------------------------------------------------------------
    # API PÚBLICA
    # ------------------------------------------------------------------

    def set_current_frequency(self, freq_mhz: float) -> None:
        """Actualiza la frecuencia central actual (llamado desde controller)."""
        self.current_freq_mhz = freq_mhz

    def set_scan_progress(self, index: int, total: int) -> None:
        """Informa al adaptador del progreso del barrido (para barra de progreso)."""
        self.freq_index  = index
        self.total_freqs = total

    def configure(self, config: dict) -> None:
        """Configura parámetros de detección."""
        self.threshold_db = config.get('threshold_db', self.threshold_db)
        self.min_bw_hz    = config.get('min_bw_hz',    self.min_bw_hz)
        self.max_bw_hz    = config.get('max_bw_hz',    self.max_bw_hz)

        # Propagar al CFAR
        self.cfar.threshold_db = self.threshold_db
        self.cfar.min_bw_hz    = self.min_bw_hz
        self.cfar.max_bw_hz    = self.max_bw_hz

        self.logger.info(
            f"⚙️ Adaptador configurado: "
            f"umbral={self.threshold_db} dB, "
            f"BW=[{self.min_bw_hz/1e3:.0f} kHz – {self.max_bw_hz/1e6:.1f} MHz]"
        )

    def update_sample_rate(self, sample_rate: float) -> None:
        self.sample_rate = sample_rate
        self.cfar.update_sample_rate(sample_rate)

    def start_processing(self) -> None:
        if self.is_running:
            return
        self.is_running  = True
        self._stop_flag  = False
        self._pause_flag = False
        self._block_queue.clear()
        self._queued_samples = 0
        self.start()
        self.logger.info("▶ Adaptador iniciado")

    def stop_processing(self) -> None:
        self._stop_flag = True
        self.is_running = False

    def pause_processing(self) -> None:
        self._pause_flag = True

    def resume_processing(self) -> None:
        self._pause_flag = False

    # ------------------------------------------------------------------
    # QTHREAD — LOOP PRINCIPAL
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.logger.info("🚀 GRInspectorAdapter hilo iniciado")
        self.inspector_ready.emit(self.gr_inspector_available)

        last_values_time = time.time()
        values_interval = 0.2  # Emitir cada 200ms para respuesta rápida

        while not self._stop_flag:
            try:
                if self._pause_flag:
                    self.msleep(100)
                    continue

                t0 = time.time()

                # Obtener bloque del ring buffer
                result = self.ring_buffer.get_read_buffer(timeout_ms=50)
                if result is None:
                    self.msleep(10)
                    continue

                iq_data, buf_idx = result
                self.samples_processed += len(iq_data)

                # Acumular en la deque (sin concatenar todavía)
                self._block_queue.append(iq_data.copy())
                self._queued_samples += len(iq_data)

                # Liberar el buffer lo antes posible
                self.ring_buffer.release_read(buf_idx)

                # Procesar cuando hay suficientes muestras
                while self._queued_samples >= self.TARGET_BUFFER_SIZE:
                    block = self._collect_block()
                    detections = self._process_block(block)

                    for det in detections:
                        self.detections_found += 1
                        self.detection_result.emit(det)

                # Emitir estadísticas cada segundo
                now = time.time()
                if now - self._last_stats_time >= 1.0:
                    self.stats_updated.emit(
                        self.samples_processed,
                        self.detections_found,
                    )
                    if self.total_freqs > 0:
                        self.scan_progress.emit(self.freq_index, self.total_freqs)
                    self._last_stats_time = now

                # Emitir valores actuales cada 200ms
                current_time = time.time()  # <-- CAMBIADO de 'now' a 'current_time'
                if current_time - last_values_time > values_interval:
                    if hasattr(self, 'cfar') and self.cfar is not None:
                        self.values_updated.emit(
                            self.cfar.threshold_db,
                            self.cfar.noise_floor_db
                        )
                    last_values_time = current_time

                # Log periódico cada 10 s
                if now - self._last_log_time >= 10.0:
                    name = "gr-inspector" if self.gr_inspector_available else "CFAR"
                    self.logger.info(
                        f"📊 [{name}] {self.samples_processed/1e6:.1f}M muestras — "
                        f"{self.detections_found} detecciones"
                    )
                    self._last_log_time = now

                # Throttle suave
                elapsed = time.time() - t0
                if elapsed < 0.02:
                    self.msleep(int((0.02 - elapsed) * 1000))

            except Exception as exc:
                self.logger.error(f"❌ Error en adaptador: {exc}", exc_info=True)
                self.msleep(100)

        self.logger.info(
            f"⏹ Adaptador detenido — "
            f"{self.samples_processed:,} muestras, "
            f"{self.detections_found} detecciones"
        )

    # ------------------------------------------------------------------
    # MÉTODOS PRIVADOS
    # ------------------------------------------------------------------

    def _collect_block(self) -> np.ndarray:
        """
        Extrae exactamente TARGET_BUFFER_SIZE muestras de la deque
        sin crear arrays intermedios innecesarios.
        """
        needed   = self.TARGET_BUFFER_SIZE
        parts    = []
        gathered = 0

        while gathered < needed and self._block_queue:
            chunk = self._block_queue[0]
            remaining = needed - gathered

            if len(chunk) <= remaining:
                parts.append(chunk)
                gathered += len(chunk)
                self._block_queue.popleft()
                self._queued_samples -= len(chunk)
            else:
                # Partir el bloque: guardar el sobrante de vuelta
                parts.append(chunk[:remaining])
                leftover = chunk[remaining:]
                self._block_queue[0] = leftover
                self._queued_samples -= remaining
                gathered += remaining

        return np.concatenate(parts) if parts else np.array([], dtype=np.complex64)

    def _process_block(self, iq_data: np.ndarray) -> list:
        """Despacha el bloque al detector correcto."""
        if len(iq_data) == 0:
            return []

        if self.gr_inspector_available:
            return self._process_with_gr_inspector(iq_data)
        return self._process_with_cfar(iq_data)

    def _process_with_gr_inspector(self, iq_data: np.ndarray) -> list:
        """
        Procesamiento con gr-inspector.
        TODO: implementar llamada real a gr_inspector cuando esté disponible.
        Por ahora delega a CFAR (implementación real, no simulada).
        """
        # Cuando gr_inspector tenga API Python estable, reemplazar esto:
        # results = gr_inspector.detect(iq_data, self.sample_rate, ...)
        # return self._parse_gr_results(results)
        self.logger.debug("gr-inspector aún no integrado; usando CFAR")
        return self._process_with_cfar(iq_data)

    def _process_with_cfar(self, iq_data: np.ndarray) -> list:
        """Procesamiento con detector CFAR real."""
        return self.cfar.process_block(iq_data, self.current_freq_mhz)

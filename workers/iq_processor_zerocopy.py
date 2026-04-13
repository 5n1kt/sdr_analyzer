# workers/iq_processor_zerocopy.py
# -*- coding: utf-8 -*-
#
# CORRECCIONES APLICADAS
# ──────────────────────
# 1. [CRÍTICO] Buffer atascado en FILLING si _read_samples() falla.
#    FIX: _release_viz_buffer_on_error() libera el slot correctamente.
#
# 2. [CRÍTICO] int16_view invalidada si raw_buffer se reasigna externamente.
#    FIX: raw_buffer e int16_view se recrean juntos en _rebuild_raw_buffer().
#
# 3. [CRÍTICO] _read_and_discard() accede a bladerf.sdr.sync_rx directamente.
#    FIX: usa self.bladerf.read_samples() del contrato SDRDevice.
#
# 4. [POTENCIAL] _read_samples() accede a bladerf.sdr.sync_rx como fallback.
#    FIX: eliminado; solo se usa read_samples() del contrato SDRDevice.
#
# 5. [POTENCIAL] throttle_skips se incrementaba aunque el frame no esperó.
#    FIX: el incremento se mueve dentro del bloque `if sleep_time > 0`.
#
# 6. [LIMPIEZA] stop() timeout aumentado a 4000ms.
#
# 7. [CRÍTICO - v3] El throttling de visualización estrangulaba la grabación.
#    El loop original aplicaba _apply_throttling() ANTES de leer del hardware,
#    de modo que el hardware solo se leía a ~30 bloques/s en lugar de los
#    6836 bloques/s que produce la BladeRF a 56 MSPS. El recording_buffer
#    recibía exactamente los mismos 30 bloques/s que el viz_buffer, causando
#    que el grabador capturara solo ~1% de la señal real (~1 MB/s en vez de
#    ~1.8 GB/s efectivos después de throttle de hardware).
#
#    FIX: separación completa de las dos rutas dentro del loop:
#      a) Leer del hardware SIN throttle → siempre, todos los bloques.
#      b) recording_buffer → recibe TODOS los bloques leídos (sin throttle).
#      c) viz_buffer → recibe solo los bloques que pasan el gate de throttle.
#
#    El throttle ahora es un "gate" de decisión aplicado solo al viz_buffer,
#    sin bloquear el loop con msleep(). Se basa en tiempo transcurrido:
#    si no ha pasado expected_interval desde el último frame de viz, se
#    salta el commit al viz_buffer pero se sigue grabando normalmente.

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
import logging
import time


class IQProcessorZeroCopy(QThread):
    """
    Procesador IQ que escribe en DOS ring buffers en paralelo:
      - ring_buffer      : para visualización (con throttling de FPS)
      - recording_buffer : para grabación (SIN throttling — todos los bloques)

    Recibe un objeto SDRDevice (o cualquier objeto con read_samples() y
    bytes_per_sample / samples_per_block) como fuente de hardware.
    """

    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    buffer_written = pyqtSignal(int)
    error_occurred = pyqtSignal(str)
    stats_updated  = pyqtSignal(dict)

    # -----------------------------------------------------------------------
    # CONSTRUCTOR
    # -----------------------------------------------------------------------
    def __init__(self, sdr_device, ring_buffer, recording_buffer=None):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        self.bladerf          = sdr_device
        self.ring_buffer      = ring_buffer
        self.recording_buffer = recording_buffer
        # recording_active=False: no escribir en recording_buffer hasta que
        # el grabador llame attach_recording_buffer(). Evita overflow pre-grabacion.
        self.recording_active = False

        self.is_running  = False
        self._stop_flag  = False

        self.samples_per_block = getattr(sdr_device, 'samples_per_block', 8192)
        self.bytes_per_sample  = getattr(sdr_device, 'bytes_per_sample',  4)
        self.bytes_per_block   = self.samples_per_block * self.bytes_per_sample

        # CORRECCIÓN 2: raw_buffer e int16_view siempre creados juntos
        self._rebuild_raw_buffer(self.bytes_per_block)

        # Throttling — SOLO para visualización, nunca para grabación
        self.throttle_enabled         = True
        self.target_fps               = 30
        self.sample_rate              = getattr(sdr_device, 'sample_rate', 2e6)
        self.blocks_per_second        = self.sample_rate / self.samples_per_block
        self.target_blocks_per_second = self.target_fps
        self.throttle_factor          = max(
            1, int(self.blocks_per_second / self.target_blocks_per_second)
        )
        self.last_block_time   = time.time()
        self.expected_interval = 1.0 / self.target_blocks_per_second
        self.blocks_processed  = 0

        self.stats = {
            'blocks_received':       0,
            'bytes_received':        0,
            'errors':                0,
            'overflow_skips':        0,
            'write_buffer_failures': 0,
            'throttle_skips':        0,
            'recording_overflow':    0,
            'recording_writes':      0,
        }

        self.logger.info(
            f"✅ IQProcessorZeroCopy creado: {self.samples_per_block} muestras/bloque"
        )
        self.logger.info(
            f"⚙️ Throttling viz: {self.blocks_per_second:.0f} → "
            f"{self.target_blocks_per_second} blocks/s (factor {self.throttle_factor}x)"
        )
        if self.recording_buffer:
            self.logger.info(
                f"📼 Recording buffer: {self.recording_buffer.num_buffers} slots "
                f"— sin throttle (todos los bloques)"
            )

    # -----------------------------------------------------------------------
    # QTHREAD — LOOP PRINCIPAL
    # -----------------------------------------------------------------------
    def run(self):
        """
        Loop principal con throttling SOLO para visualización.

        CORRECCIÓN 7: arquitectura corregida:

        ANTES (bug):
            loop:
                msleep(throttle)        ← bloqueaba TODO el loop a 30 iter/s
                leer hardware           ← solo 30 lecturas/s en vez de 6836/s
                → viz_buffer            ← 30 bloques/s  ✓ (correcto para viz)
                → recording_buffer      ← 30 bloques/s  ✗ (debería ser 6836/s)

        DESPUÉS (correcto):
            loop:
                leer hardware           ← siempre, sin bloqueo → 6836/s
                → recording_buffer      ← TODOS los bloques (6836/s) ✓
                gate_viz = tiempo?      ← ¿pasó expected_interval?
                si gate_viz:
                    → viz_buffer        ← solo los bloques que pasan el gate ✓
        """
        self.is_running  = True
        self._stop_flag  = False
        self.logger.info("🚀 IQProcessorZeroCopy iniciado (dual buffer, throttle solo viz)")

        self._ensure_streaming()

        self.last_block_time  = time.time()
        self.blocks_processed = 0

        while not self._stop_flag:
            try:
                # ── PASO 1: Leer del hardware SIN throttle ───────────────────
                # Esta llamada bloquea hasta que la BladeRF entrega un bloque.
                # El hardware dicta la cadencia real (6836 bloques/s a 56 MSPS).
                # No hacemos msleep() antes de leer — dejamos que el hardware
                # controle el ritmo naturalmente.
                if not self._read_samples():
                    # Fallo de lectura: liberar slots reservados y continuar
                    self._release_viz_buffer_on_error()
                    self.stats['errors'] += 1
                    continue

                # ── PASO 2: Grabar — TODOS los bloques, sin excepción ────────
                if self.recording_active and self.recording_buffer is not None:
                    rec_buffer = self._get_recording_buffer()
                    if rec_buffer is not None:
                        self._write_to_recording(rec_buffer)
                        self.recording_buffer.commit_write()
                        self.stats['recording_writes'] += 1

                # ── PASO 3: Visualización — solo si pasó expected_interval ───
                now = time.time()
                elapsed_viz = now - self.last_block_time

                if not self.throttle_enabled or elapsed_viz >= self.expected_interval:
                    viz_buffer = self.ring_buffer.get_write_buffer()

                    if viz_buffer is not None:
                        self._write_to_viz(viz_buffer)
                        self.ring_buffer.commit_write()
                        self.last_block_time = now
                    else:
                        # Ring buffer de viz lleno → descartar este frame de viz
                        self.stats['overflow_skips']        += 1
                        self.stats['write_buffer_failures'] += 1
                else:
                    # Frame de viz omitido por throttle — la grabación ya se hizo
                    self.stats['throttle_skips'] += 1

                self._update_stats()

            except Exception as exc:
                self._handle_error(exc)

        self.is_running = False
        self.logger.info("⏹️ IQProcessorZeroCopy detenido")

    # -----------------------------------------------------------------------
    # CONTROL PÚBLICO
    # -----------------------------------------------------------------------
    def update_sample_rate(self, new_sample_rate: float):
        """Actualiza sample rate y recalcula throttling."""
        self.sample_rate              = new_sample_rate
        self.blocks_per_second        = self.sample_rate / self.samples_per_block
        self.throttle_factor          = max(
            1, int(self.blocks_per_second / self.target_blocks_per_second)
        )
        self.expected_interval = 1.0 / self.target_blocks_per_second
        self.last_block_time   = time.time()

        self.logger.info(
            f"📊 Throttling viz actualizado: {self.blocks_per_second:.0f} → "
            f"{self.target_blocks_per_second} blocks/s (factor {self.throttle_factor}x)"
        )

    def attach_recording_buffer(self, recording_buffer):
        """
        Habilita escritura en recording_buffer.
        Llamar cuando el grabador arranca — antes el processor no escribe nada.
        Thread-safe: asignación atómica en CPython.
        """
        self.recording_buffer = recording_buffer
        self.recording_active = True
        self.logger.info(
            f"📼 Recording buffer activado: {recording_buffer.num_buffers} slots"
        )

    def detach_recording_buffer(self):
        """
        Detiene la escritura en recording_buffer.

        Llamar cuando el grabador termina (por tiempo, tamaño o stop manual)
        pero la captura en vivo sigue activa. Sin esto el processor llena
        el buffer indefinidamente causando overflow continuo a plena velocidad.

        También se llama al inicio de captura (antes de grabar) para evitar
        overflow mientras no hay grabador activo.

        Thread-safe: asignación atómica en CPython.
        """
        self.recording_active = False
        self.logger.info("📼 Recording buffer desactivado en processor")

    def stop(self):
        """
        Detiene el procesamiento.
        CORRECCIÓN 6: timeout 4000ms cubre BladeRF sync_rx timeout (3500ms).
        """
        self._stop_flag = True
        if not self.wait(4000):
            self.logger.warning(
                "⚠️ IQProcessor no respondió en 4s — forzando terminación"
            )
            self.terminate()
            self.wait(500)
        self.logger.info("⏹️ IQProcessorZeroCopy detenido")

    # -----------------------------------------------------------------------
    # PRIVADOS — ESCRITURA EN BUFFERS
    # -----------------------------------------------------------------------
    def _write_to_recording(self, rec_buffer):
        """
        Escribe raw_buffer convertido a complex64 en rec_buffer.
        Ruta dedicada para grabación — sin mezclar con la lógica de viz.
        """
        try:
            n        = min(len(rec_buffer), self.samples_per_block)
            samples  = self.int16_view[:n * 2]
            iq_pairs = samples.reshape(-1, 2)
            k        = min(n, iq_pairs.shape[0])

            rec_buffer[:k].real = iq_pairs[:k, 0].astype(np.float32) / 2048.0
            rec_buffer[:k].imag = iq_pairs[:k, 1].astype(np.float32) / 2048.0

        except Exception as exc:
            self.logger.error(f"Error escribiendo en recording buffer: {exc}")
            rec_buffer.fill(0)

    def _write_to_viz(self, viz_buffer):
        """
        Escribe raw_buffer convertido a complex64 en viz_buffer.
        Ruta dedicada para visualización.
        """
        try:
            n        = min(len(viz_buffer), self.samples_per_block)
            samples  = self.int16_view[:n * 2]
            iq_pairs = samples.reshape(-1, 2)
            k        = min(n, iq_pairs.shape[0])

            viz_buffer[:k].real = iq_pairs[:k, 0].astype(np.float32) / 2048.0
            viz_buffer[:k].imag = iq_pairs[:k, 1].astype(np.float32) / 2048.0

        except Exception as exc:
            self.logger.error(f"Error escribiendo en viz buffer: {exc}")
            viz_buffer.fill(0)

    # -----------------------------------------------------------------------
    # PRIVADOS — THROTTLING Y CONTROL DE FLUJO
    # -----------------------------------------------------------------------
    def _apply_throttling(self):
        """
        Método conservado para compatibilidad.
        En v3 el throttle es un gate de tiempo en run(), no un msleep().
        """
        pass

    def _ensure_streaming(self):
        """Activa el stream del hardware si no está ya activo."""
        if hasattr(self.bladerf, 'streaming') and not self.bladerf.streaming:
            try:
                self.bladerf.start_stream()
            except Exception as exc:
                self.logger.error(f"Error activando stream: {exc}")

    def _get_recording_buffer(self):
        """Obtiene slot de escritura de grabación."""
        rec = self.recording_buffer.get_write_buffer()
        if rec is None:
            self.stats['recording_overflow'] += 1
            if self.stats['recording_overflow'] % 100 == 0:
                self.logger.warning(
                    f"⚠️ Recording overflow: {self.stats['recording_overflow']}"
                )
        return rec

    def _release_viz_buffer_on_error(self):
        """
        Libera el slot de visualización cuando la lectura del hardware falla.
        CORRECCIÓN 1: evita que el slot quede atascado en BUFFER_FILLING.
        """
        try:
            wb = self.ring_buffer
            with wb.lock:
                idx = (wb.write_index - 1) % wb.num_buffers
                if wb.buffer_states[idx] == wb.BUFFER_FILLING:
                    wb.buffer_states[idx] = wb.BUFFER_FREE
                    wb.write_index = idx
        except Exception as exc:
            self.logger.debug(f"_release_viz_buffer_on_error: {exc}")

    def _update_stats(self):
        """Actualiza estadísticas y emite señal cada 100 bloques."""
        self.blocks_processed         += 1
        self.stats['blocks_received'] += 1
        self.stats['bytes_received']  += self.bytes_per_block

        if self.stats['blocks_received'] % 100 == 0:
            self.stats_updated.emit(self.stats.copy())

    def _handle_error(self, error: Exception):
        """Registra y emite errores del loop principal."""
        if not self._stop_flag:
            self.logger.error(f"❌ Error en IQProcessor: {error}")
            self.stats['errors'] += 1
            self.error_occurred.emit(str(error))
            time.sleep(0.01)

    # -----------------------------------------------------------------------
    # PRIVADOS — LECTURA DE HARDWARE
    # -----------------------------------------------------------------------
    def _rebuild_raw_buffer(self, size: int):
        """
        Crea raw_buffer e int16_view juntos de forma atómica.
        CORRECCIÓN 2: garantiza que int16_view siempre apunta al raw_buffer actual.
        """
        self.raw_buffer = bytearray(size)
        self.int16_view = np.frombuffer(self.raw_buffer, dtype=np.int16)

    def _read_samples(self) -> bool:
        """
        Lee un bloque de muestras raw en self.raw_buffer.
        CORRECCIONES 3 y 4: usa únicamente read_samples() del contrato SDRDevice.
        """
        try:
            if hasattr(self.bladerf, 'read_samples'):
                return self.bladerf.read_samples(
                    self.raw_buffer, self.samples_per_block
                )
            self.logger.error(
                "❌ El objeto SDR no implementa read_samples(). "
                "Verifica que se está usando SDRDevice o una clase compatible."
            )
            return False
        except Exception as exc:
            self.logger.error(f"Error leyendo muestras: {exc}")
            return False

    def _read_and_discard(self):
        """
        Lee y descarta un bloque para mantener el stream limpio.
        CORRECCIÓN 3: usa read_samples() del contrato.
        """
        try:
            if hasattr(self.bladerf, 'read_samples'):
                self.bladerf.read_samples(self.raw_buffer, self.samples_per_block)
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # PRIVADOS — CONVERSIÓN IQ (método legacy conservado)
    # -----------------------------------------------------------------------
    def _bytes_to_complex_dual(self, viz_buffer, rec_buffer):
        """
        Método conservado para compatibilidad con código externo que
        pudiera llamarlo directamente. En v3 el loop usa _write_to_viz()
        y _write_to_recording() por separado.
        """
        try:
            needed_samples = min(len(viz_buffer), self.samples_per_block)
            samples        = self.int16_view[:needed_samples * 2]

            if len(samples) < 2:
                return

            iq_pairs = samples.reshape(-1, 2)
            n        = min(needed_samples, iq_pairs.shape[0])

            i_norm = iq_pairs[:n, 0].astype(np.float32) / 2048.0
            q_norm = iq_pairs[:n, 1].astype(np.float32) / 2048.0

            viz_buffer[:n].real = i_norm
            viz_buffer[:n].imag = q_norm

            if rec_buffer is not None:
                rec_buffer[:n].real = i_norm
                rec_buffer[:n].imag = q_norm

        except Exception as exc:
            self.logger.error(f"Error en conversión dual: {exc}")
            viz_buffer.fill(0)
            if rec_buffer is not None:
                rec_buffer.fill(0)

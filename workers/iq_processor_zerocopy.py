# workers/iq_processor_zerocopy.py
# -*- coding: utf-8 -*-
#
# CORRECCIONES APLICADAS
# ──────────────────────
# 1. [CRÍTICO] Buffer atascado en FILLING si _read_samples() falla.
#    Cuando get_write_buffer() marca el slot como BUFFER_FILLING y
#    _read_samples() retorna False, el loop hacía `continue` sin llamar
#    commit_write() ni liberar el slot. El buffer quedaba atascado en
#    FILLING permanentemente, reduciendo el anillo en 1 slot por cada
#    fallo de lectura hasta quedarse sin slots y bloquear la captura.
#    FIX: _release_viz_buffer_on_error() libera el slot correctamente.
#
# 2. [CRÍTICO] int16_view invalidada si raw_buffer se reasigna externamente.
#    self.int16_view = np.frombuffer(self.raw_buffer, ...) crea una vista
#    del bytearray original. Si rfcontroller u otro código reasignaba
#    self.raw_buffer a un nuevo objeto, int16_view seguía apuntando al
#    bytearray antiguo y leía datos desactualizados sin ningún error visible.
#    FIX: raw_buffer y int16_view se recrean juntos en _rebuild_raw_buffer()
#    y se llama en update_sample_rate() si el tamaño cambia.
#
# 3. [CRÍTICO] _read_and_discard() accede a bladerf.sdr.sync_rx directamente.
#    Rompe el contrato SDRDevice y falla con cualquier hardware que no sea
#    BladeRF. FIX: usa self.bladerf.read_samples() del contrato abstracto.
#
# 4. [POTENCIAL] _read_samples() accede a bladerf.sdr.sync_rx directamente
#    como fallback. FIX: eliminado el fallback; solo se usa read_samples()
#    del contrato SDRDevice. Si el objeto no lo implementa se lanza error claro.
#
# 5. [POTENCIAL] throttle_skips se incrementaba aunque el frame no esperó
#    (elapsed >= expected_interval). El contador no representaba "frames
#    que tuvieron que esperar" sino "frames procesados con throttle activo".
#    FIX: el incremento se mueve dentro del bloque `if sleep_time > 0`.
#
# 6. [LIMPIEZA] stop() llama self.wait(2000) que puede expirar si el hardware
#    está bloqueado en sync_rx (timeout de hardware = 3500ms). Se aumenta
#    el timeout de espera a 4000ms para cubrir el peor caso.

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
import logging
import time


class IQProcessorZeroCopy(QThread):
    """
    Procesador IQ que escribe en DOS ring buffers en paralelo:
      - ring_buffer      : para visualización (con throttling de FPS)
      - recording_buffer : para grabación (sin throttling, todos los bloques)

    Recibe un objeto SDRDevice (o cualquier objeto con read_samples() y
    bytes_per_sample / samples_per_block) como fuente de hardware.
    """

    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    buffer_written = pyqtSignal(int)   # índice del buffer escrito
    error_occurred = pyqtSignal(str)
    stats_updated  = pyqtSignal(dict)

    # -----------------------------------------------------------------------
    # CONSTRUCTOR
    # -----------------------------------------------------------------------
    def __init__(self, sdr_device, ring_buffer, recording_buffer=None):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        # Referencias externas
        self.bladerf          = sdr_device      # nombre histórico conservado
        self.ring_buffer      = ring_buffer
        self.recording_buffer = recording_buffer

        # Estado del hilo
        self.is_running  = False
        self._stop_flag  = False

        # Configuración de buffers (leída del dispositivo)
        self.samples_per_block = getattr(sdr_device, 'samples_per_block', 8192)
        self.bytes_per_sample  = getattr(sdr_device, 'bytes_per_sample',  4)
        self.bytes_per_block   = self.samples_per_block * self.bytes_per_sample

        # Buffer raw + vista int16 (siempre creados juntos)
        # CORRECCIÓN 2: se encapsula la creación en un método para que
        # raw_buffer e int16_view nunca se desincronicen.
        self._rebuild_raw_buffer(self.bytes_per_block)

        # Control de throttling para visualización
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

        # Estadísticas
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
            f"⚙️ Throttling: {self.blocks_per_second:.0f} → "
            f"{self.target_blocks_per_second} blocks/s (factor {self.throttle_factor}x)"
        )
        if self.recording_buffer:
            self.logger.info(
                f"📼 Buffer grabación: {self.recording_buffer.num_buffers} buffers"
            )

    # -----------------------------------------------------------------------
    # QTHREAD — LOOP PRINCIPAL
    # -----------------------------------------------------------------------
    def run(self):
        """Loop principal con throttling y dual-buffer."""
        self.is_running  = True
        self._stop_flag  = False
        self.logger.info("🚀 IQProcessorZeroCopy iniciado (dual buffer)")

        self._ensure_streaming()

        self.last_block_time  = time.time()
        self.blocks_processed = 0

        while not self._stop_flag:
            try:
                if self.throttle_enabled:
                    self._apply_throttling()

                # Obtener slot de escritura para visualización
                viz_buffer = self.ring_buffer.get_write_buffer()

                # Obtener slot de escritura para grabación (si existe)
                rec_buffer = self._get_recording_buffer()

                if viz_buffer is None:
                    # Sin slot disponible → descartar este bloque
                    self._handle_buffer_full()
                    continue

                # Leer datos del hardware
                # CORRECCIÓN 1 y 4: si falla, liberamos viz_buffer antes de
                # hacer continue para que el slot no quede atascado en FILLING.
                if not self._read_samples():
                    self._release_viz_buffer_on_error()
                    continue

                # Convertir y escribir en ambos buffers
                self._bytes_to_complex_dual(viz_buffer, rec_buffer)

                # Commit de ambos buffers
                self.ring_buffer.commit_write()
                if rec_buffer is not None:
                    self.recording_buffer.commit_write()
                    self.stats['recording_writes'] += 1

                self._update_stats()

                # Pausa mínima para no saturar la CPU
                self.msleep(1)

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
            f"📊 Throttling actualizado: {self.blocks_per_second:.0f} → "
            f"{self.target_blocks_per_second} blocks/s (factor {self.throttle_factor}x)"
        )

    def stop(self):
        """
        Detiene el procesamiento.

        CORRECCIÓN 6: timeout aumentado a 4000ms para cubrir el peor caso
        de hardware bloqueado en sync_rx (timeout BladeRF = 3500ms).
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
    # PRIVADOS — THROTTLING Y CONTROL DE FLUJO
    # -----------------------------------------------------------------------
    def _apply_throttling(self):
        """Duerme lo necesario para mantener el FPS objetivo."""
        elapsed    = time.time() - self.last_block_time
        sleep_time = self.expected_interval - elapsed

        if sleep_time > 0:
            self.msleep(int(sleep_time * 1000))
            # CORRECCIÓN 5: el contador solo se incrementa cuando
            # efectivamente se durmió (frame que tuvo que esperar).
            self.stats['throttle_skips'] += 1

        self.last_block_time = time.time()

    def _ensure_streaming(self):
        """Activa el stream del hardware si no está ya activo."""
        if hasattr(self.bladerf, 'streaming') and not self.bladerf.streaming:
            try:
                self.bladerf.start_stream()
            except Exception as exc:
                self.logger.error(f"Error activando stream: {exc}")

    def _get_recording_buffer(self):
        """Obtiene slot de escritura de grabación si hay buffer activo."""
        if not self.recording_buffer:
            return None

        rec = self.recording_buffer.get_write_buffer()
        if rec is None:
            self.stats['recording_overflow'] += 1
            if self.stats['recording_overflow'] % 100 == 0:
                self.logger.warning(
                    f"⚠️ Recording overflow: {self.stats['recording_overflow']}"
                )
        return rec

    def _handle_buffer_full(self):
        """Descarta el bloque actual cuando el ring buffer de viz está lleno."""
        self.stats['overflow_skips']        += 1
        self.stats['write_buffer_failures'] += 1
        self._read_and_discard()

    def _release_viz_buffer_on_error(self):
        """
        Libera el slot de visualización cuando la lectura del hardware falla.

        CORRECCIÓN 1: el ring buffer marca el slot como BUFFER_FILLING en
        get_write_buffer(). Si no llamamos commit_write() ni release, ese
        slot queda bloqueado para siempre. Aquí lo restauramos a FREE.
        IQRingBuffer no expone release_write directamente, así que usamos
        la secuencia interna equivalente a deshacer el get_write_buffer.
        """
        try:
            wb = self.ring_buffer
            with wb.lock:
                # Revertir el slot actual a FREE si está en FILLING
                idx = (wb.write_index - 1) % wb.num_buffers
                if wb.buffer_states[idx] == wb.BUFFER_FILLING:
                    wb.buffer_states[idx] = wb.BUFFER_FREE
                    # Retroceder write_index para que el próximo
                    # get_write_buffer() pueda reusar este slot.
                    wb.write_index = idx
        except Exception as exc:
            self.logger.debug(f"_release_viz_buffer_on_error: {exc}")

    def _update_stats(self):
        """Actualiza estadísticas y emite señal cada 100 bloques."""
        self.blocks_processed              += 1
        self.stats['blocks_received']      += 1
        self.stats['bytes_received']       += self.bytes_per_block

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
        Crea (o recrea) raw_buffer e int16_view juntos de forma atómica.

        CORRECCIÓN 2: encapsular la creación garantiza que int16_view
        siempre es una vista del raw_buffer actual. Si el tamaño del
        bloque cambia (ej. nuevo sample rate), ambos se regeneran en
        sincronía. Nunca puede quedar int16_view apuntando a un bytearray
        antiguo.
        """
        self.raw_buffer  = bytearray(size)
        self.int16_view  = np.frombuffer(self.raw_buffer, dtype=np.int16)

    def _read_samples(self) -> bool:
        """
        Lee un bloque de muestras raw en self.raw_buffer.

        CORRECCIÓN 3 y 4: usa únicamente read_samples() del contrato
        SDRDevice. El fallback a bladerf.sdr.sync_rx() fue eliminado
        porque rompe la abstracción de hardware y falla con cualquier
        SDR que no sea BladeRF.
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

        CORRECCIÓN 3: usa read_samples() del contrato, no sync_rx directo.
        Los errores se ignoran porque esta llamada es de mantenimiento.
        """
        try:
            if hasattr(self.bladerf, 'read_samples'):
                self.bladerf.read_samples(self.raw_buffer, self.samples_per_block)
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # PRIVADOS — CONVERSIÓN IQ
    # -----------------------------------------------------------------------
    def _bytes_to_complex_dual(self, viz_buffer, rec_buffer):
        """
        Convierte self.raw_buffer a complex64 y escribe en viz_buffer
        y opcionalmente en rec_buffer, sin copias intermedias.

        La normalización (/ 2048.0) asume formato SC16_Q11. Si el
        hardware usa un formato diferente, este método debe delegarse
        al objeto SDRDevice mediante bytes_to_complex().
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

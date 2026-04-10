# workers/iq_recorder_simple.py
# -*- coding: utf-8 -*-
#
# CORRECCIONES
# ──────────────────────────────────────────────────────────────────────────
# BUG 4 [CRÍTICO] _check_limits solo comprobaba modo 'time'; el modo 'size'
#   nunca detenía la grabación → el archivo podía crecer ilimitadamente.
#   FIX: añadida la rama size en _check_limits usando self.bytes_written.
#
# BUG 5 [CRÍTICO] _convert_to_int16 mutaba el array original del ring buffer
#   con "iq_data.real *= 2048". Si FFTProcessor o el demodulador tenían una
#   referencia al mismo array (zero-copy), leían datos corrompidos.
#   FIX: se trabaja sobre una copia del array; el buffer original queda intacto.

import numpy as np
import os
import time
import threading
import queue
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal
import logging


class IQRecorderSimple(QThread):
    """
    Grabador IQ con 2 hilos (captura y escritura) y escritura directa a disco.

    Pipeline:
      ring_buffer → _capture_loop → write_queue → _write_loop → archivo .bin
      Metadata: archivo .meta con freq, SR, formato, duración real.
    """

    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal()
    stats_updated     = pyqtSignal(dict)

    def __init__(self, ring_buffer, sample_rate: float, freq_mhz: float):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        self.ring_buffer        = ring_buffer
        self.sample_rate        = float(sample_rate)
        self.freq_mhz           = float(freq_mhz)
        self.samples_per_buffer = ring_buffer.samples_per_buffer

        self.is_recording = False
        self._stop_flag   = False
        self._pause_flag  = False
        self.record_file  = None
        self.filename     = None
        self.meta_filename = None

        # Límites
        self.mode             = 'continuous'
        self.time_limit_sec   = 0
        self.size_limit_bytes = 0

        # Buffer de salida pre-asignado (FIX BUG 5: sólo para la copia)
        self.output_buffer = np.empty(self.samples_per_buffer * 2, dtype=np.int16)

        # Cola de escritura (limitada para controlar el uso de memoria)
        self.write_queue = queue.Queue(maxsize=5000)

        # Control de parada
        self.stop_event = threading.Event()

        self.capture_thread = None
        self.write_thread   = None

        # Estadísticas (protegidas por lock)
        self.stats_lock       = threading.Lock()
        self.bytes_written    = 0
        self.buffers_captured = 0
        self.start_time       = 0.0
        self.last_log_time    = 0.0

        self.blocks_per_second = self.sample_rate / self.samples_per_buffer

        self.logger.info(
            f"✅ IQRecorderSimple — SR={self.sample_rate/1e6:.1f} MHz  "
            f"buf={self.samples_per_buffer}  blk/s={self.blocks_per_second:.0f}"
        )

    # ──────────────────────────────────────────────────────────────────────
    # CONFIGURACIÓN Y CONTROL
    # ──────────────────────────────────────────────────────────────────────

    def configure_recording(self, filename: str, mode: str = 'continuous',
                            time_limit: int = 0, size_limit_mb: float = 0):
        self.filename         = filename
        self.meta_filename    = filename.replace('.bin', '.meta')
        self.mode             = mode
        self.time_limit_sec   = time_limit
        self.size_limit_bytes = size_limit_mb * 1024 * 1024

    def start_recording(self):
        if self.is_recording:
            return
        try:
            os.makedirs(os.path.dirname(self.filename) or '.', exist_ok=True)
            self.record_file = open(self.filename, 'wb')
            self._save_metadata()

            self.stop_event.clear()
            self.is_recording     = True
            self._stop_flag       = False
            self._pause_flag      = False
            self.start_time       = time.time()
            self.last_log_time    = self.start_time
            self.bytes_written    = 0
            self.buffers_captured = 0

            self._clear_queue()
            self._start_threads()
            self.start()              # hilo de monitoreo (QThread)

            self.recording_started.emit(self.filename)
            self.logger.info(f"⏺ Grabación iniciada: {self.filename}")
        except Exception as exc:
            self.logger.error(f"Error iniciando grabación: {exc}")
            import traceback; traceback.print_exc()

    def stop_recording(self):
        self.logger.info("⏹ Deteniendo grabación…")
        self._stop_flag = True
        self.stop_event.set()

    def pause_recording(self):
        self._pause_flag = True
        self.logger.info("⏸ Pausada")

    def resume_recording(self):
        self._pause_flag = False
        self.logger.info("▶ Reanudada")

    # ──────────────────────────────────────────────────────────────────────
    # HILO PRINCIPAL — MONITOR (QThread)
    # ──────────────────────────────────────────────────────────────────────

    def run(self):
        self.logger.info("🚀 Monitor iniciado")
        last_ui = time.time()

        while not self.stop_event.is_set() and self.is_recording:
            now = time.time()
            if now - last_ui >= 0.1:
                self._emit_stats()
                last_ui = now
            if now - self.last_log_time >= 1.0:
                self._log_stats()
                self.last_log_time = now
            if self._check_limits():
                self.stop_event.set()
                break
            time.sleep(0.05)

        self._join_threads()

        if self.record_file:
            self._update_metadata_duration()
            self.record_file.close()
            self.record_file = None

        self.is_recording = False
        self.recording_stopped.emit()
        self.logger.info("⏹ Monitor detenido")

    # ──────────────────────────────────────────────────────────────────────
    # HILOS DE CAPTURA Y ESCRITURA
    # ──────────────────────────────────────────────────────────────────────

    def _start_threads(self):
        self.capture_thread = threading.Thread(
            target=self._capture_loop, name="IQCapture", daemon=True
        )
        self.write_thread = threading.Thread(
            target=self._write_loop, name="IQWrite", daemon=True
        )
        self.capture_thread.start()
        self.write_thread.start()

    def _join_threads(self, timeout: float = 3.0):
        for t in (self.capture_thread, self.write_thread):
            if t and t.is_alive():
                t.join(timeout=timeout)

    def _clear_queue(self):
        while not self.write_queue.empty():
            try: self.write_queue.get_nowait()
            except queue.Empty: break

    def _capture_loop(self):
        """Hilo 1: lee del ring_buffer y convierte a int16."""
        self.logger.info("📥 Captura iniciada")
        local_count = 0

        while not self.stop_event.is_set():
            if self._pause_flag:
                time.sleep(0.01)
                continue

            result = self.ring_buffer.get_read_buffer(timeout_ms=100)
            if result is None:
                time.sleep(0.001)
                continue

            iq_data, buf_idx = result

            # FIX BUG 5: convertir sin mutar el buffer original
            iq_int16 = self._convert_to_int16(iq_data)

            try:
                self.write_queue.put(iq_int16, timeout=0.1)
                local_count += 1
            except queue.Full:
                self.logger.warning("⚠️ Cola de escritura llena — buffer descartado")

            self.ring_buffer.release_read(buf_idx)

            if local_count >= 100:
                with self.stats_lock:
                    self.buffers_captured += local_count
                local_count = 0

            if self._check_limits():
                self.stop_event.set()
                break

        if local_count > 0:
            with self.stats_lock:
                self.buffers_captured += local_count

        self.write_queue.put(None)   # señal de fin para el hilo de escritura
        self.logger.info("⏹ Captura detenida")

    def _convert_to_int16(self, iq_data: np.ndarray) -> np.ndarray:
        """
        FIX BUG 5: trabaja sobre una COPIA del array para no mutar el
        buffer del ring que otros workers pueden estar leyendo simultáneamente.
        """
        real = np.round(iq_data.real * 2048.0).astype(np.int16)
        imag = np.round(iq_data.imag * 2048.0).astype(np.int16)

        out = self.output_buffer          # array pre-asignado (reutilizado)
        out[0::2] = real
        out[1::2] = imag
        return out.copy()                 # copia explícita antes de encolar

    def _write_loop(self):
        """Hilo 2: escribe buffers int16 a disco."""
        self.logger.info("💾 Escritura iniciada")
        bufs_written   = 0
        local_bytes    = 0

        while not self.stop_event.is_set() or not self.write_queue.empty():
            try:
                item = self.write_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:     # señal de fin
                break

            self.record_file.write(item.tobytes())
            self.record_file.flush()

            bufs_written  += 1
            local_bytes   += item.nbytes

            if bufs_written % 100 == 0:
                with self.stats_lock:
                    self.bytes_written = local_bytes

        # Sincronizar contador final
        with self.stats_lock:
            self.bytes_written = local_bytes

        self.logger.info(
            f"⏹ Escritura detenida — {bufs_written} bufs, "
            f"{local_bytes/1e6:.1f} MB"
        )

    # ──────────────────────────────────────────────────────────────────────
    # ESTADÍSTICAS Y LÍMITES
    # ──────────────────────────────────────────────────────────────────────

    def _check_limits(self) -> bool:
        """
        FIX BUG 4: implementa tanto modo 'time' como modo 'size'.
        """
        if self.mode == 'time' and self.time_limit_sec > 0:
            if time.time() - self.start_time >= self.time_limit_sec:
                self.logger.info("⏱ Límite de tiempo alcanzado")
                return True

        if self.mode == 'size' and self.size_limit_bytes > 0:
            with self.stats_lock:
                written = self.bytes_written
            if written >= self.size_limit_bytes:
                self.logger.info(
                    f"📦 Límite de tamaño alcanzado "
                    f"({written/1e6:.1f} MB ≥ "
                    f"{self.size_limit_bytes/1e6:.1f} MB)"
                )
                return True

        return False

    def _emit_stats(self):
        with self.stats_lock:
            elapsed = time.time() - self.start_time if self.start_time else 0
            stats = {
                'bytes_written':              self.bytes_written,
                'buffers_written':            self.buffers_captured,
                'elapsed_time':               elapsed,
                'file_size_mb':               self.bytes_written / 1e6,
                'buffers_per_sec':            self.buffers_captured,
                'expected_buffers_per_sec':   self.blocks_per_second,
            }
        self.stats_updated.emit(stats)

    def _log_stats(self):
        with self.stats_lock:
            actual = self.buffers_captured
            self.buffers_captured = 0
        pct = (actual / self.blocks_per_second * 100) if self.blocks_per_second > 0 else 0
        self.logger.info(
            f"📊 {actual}/{self.blocks_per_second:.0f} bufs/s  "
            f"({pct:.0f}%)  {self.bytes_written/1e6:.1f} MB"
        )

    # ──────────────────────────────────────────────────────────────────────
    # METADATA
    # ──────────────────────────────────────────────────────────────────────

    def _save_metadata(self):
        try:
            with open(self.meta_filename, 'w') as f:
                f.write(f"Filename: {os.path.basename(self.filename)}\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Frequency: {self.freq_mhz} MHz\n")
                f.write(f"Sample Rate: {self.sample_rate/1e6} MHz\n")
                f.write(f"Mode: {self.mode}\n")
                f.write(f"Format: int16 IQ interleaved\n")
                f.write(f"Bytes per sample: 4\n")
                f.write(f"Samples per buffer: {self.samples_per_buffer}\n")
        except Exception as exc:
            self.logger.error(f"Error guardando metadata: {exc}")

    def _update_metadata_duration(self):
        """Añade duración real y tamaño al archivo .meta al cerrar."""
        try:
            elapsed = time.time() - self.start_time if self.start_time else 0
            with self.stats_lock:
                mb = self.bytes_written / 1e6
            with open(self.meta_filename, 'a') as f:
                f.write(f"Duration: {elapsed:.2f} s\n")
                f.write(f"File size: {mb:.2f} MB\n")
        except Exception as exc:
            self.logger.error(f"Error actualizando metadata: {exc}")

# workers/iq_recorder_simple.py
# -*- coding: utf-8 -*-

import numpy as np
import os
import time
import threading
import queue
import json
from datetime import datetime, timezone
from PyQt5.QtCore import QThread, pyqtSignal
import logging


class IQRecorderSimple(QThread):
    """
    Grabador IQ con soporte SigMF y fallback a .bin/.meta
    """

    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal()
    stats_updated = pyqtSignal(dict)

    def __init__(self, ring_buffer, sample_rate: float, freq_hz: float):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        self.ring_buffer = ring_buffer
        self.sample_rate = float(sample_rate)
        self.freq_hz = float(freq_hz)
        self.samples_per_buffer = ring_buffer.samples_per_buffer

        self.is_recording = False
        self._stop_flag = False
        self._pause_flag = False
        self.data_file = None
        self.sigmf_data_file = None
        self.sigmf_meta_file = None
        self.fallback_bin_file = None
        self.fallback_meta_file = None

        # Límites
        self.mode = 'continuous'
        self.time_limit_sec = 0
        self.size_limit_bytes = 0

        # Buffer de salida
        self.output_buffer = np.empty(self.samples_per_buffer * 2, dtype=np.int16)

        # Cola de escritura
        self.write_queue = queue.Queue(maxsize=5000)
        self.stop_event = threading.Event()

        self.capture_thread = None
        self.write_thread = None

        # Estadísticas
        self.stats_lock = threading.Lock()
        self.bytes_written = 0
        self.buffers_captured = 0
        self.start_time = 0.0
        self.last_log_time = 0.0
        self.samples_written = 0

        self.blocks_per_second = self.sample_rate / self.samples_per_buffer

        self.logger.info(
            f"✅ IQRecorderSimple — SR={self.sample_rate/1e6:.1f} MHz  "
            f"buf={self.samples_per_buffer}  blk/s={self.blocks_per_second:.0f}"
        )

    # ------------------------------------------------------------------
    # CONFIGURACIÓN
    # ------------------------------------------------------------------

    def configure_recording(self, base_filename: str, mode: str = 'continuous',
                            time_limit: int = 0, size_limit_mb: float = 0):
        """
        Configura la grabación.
        base_filename: nombre base sin extensión (ej: recordings/IQ_2400MHz_56MSPS_TIME10s_20260323_141111)
        """
        self.sigmf_data_file = f"{base_filename}.sigmf-data"
        self.sigmf_meta_file = f"{base_filename}.sigmf-meta"
        self.fallback_bin_file = f"{base_filename}.bin"
        self.fallback_meta_file = f"{base_filename}.meta"
        self.mode = mode
        self.time_limit_sec = time_limit
        self.size_limit_bytes = size_limit_mb * 1024 * 1024
        self.logger.info(f"📁 Archivo base: {base_filename}")

    # ------------------------------------------------------------------
    # INICIO DE GRABACIÓN
    # ------------------------------------------------------------------

    def start_recording(self):
        if self.is_recording:
            return
        try:
            os.makedirs(os.path.dirname(self.sigmf_data_file) or '.', exist_ok=True)
            
            # PASO 1: Crear archivo de datos vacío
            self.data_file = open(self.sigmf_data_file, 'wb')
            
            # PASO 2: Crear metadata SigMF (con el archivo de datos ya existente)
            sigmf_success = self._create_sigmf_metadata()
            
            # PASO 3: Siempre crear fallback .bin/.meta para compatibilidad
            self._create_fallback_metadata()
            
            if not sigmf_success:
                self.logger.warning("⚠️ SigMF metadata creation failed, using fallback format only")

            self.stop_event.clear()
            self.is_recording = True
            self._stop_flag = False
            self._pause_flag = False
            self.start_time = time.time()
            self.last_log_time = self.start_time
            self.bytes_written = 0
            self.buffers_captured = 0
            self.samples_written = 0

            self._clear_queue()
            self._start_threads()
            self.start()

            # Emitir señal con el archivo .bin (compatible con reproductor legacy)
            self.recording_started.emit(self.fallback_bin_file)
            self.logger.info(f"⏺ Grabación iniciada: {self.sigmf_data_file}")

        except Exception as exc:
            self.logger.error(f"Error iniciando grabación: {exc}")
            import traceback
            traceback.print_exc()

    def _create_sigmf_metadata(self):
        """
        Crea el archivo .sigmf-meta manualmente con JSON.
        Esto evita problemas con la API de SigMF.
        """
        try:
            # Crear estructura SigMF manualmente
            metadata = {
                "global": {
                    "core:datatype": "ci16_le",  # complex int16 little-endian
                    "core:sample_rate": self.sample_rate,
                    "core:hw": "BladeRF 2.0 micro",
                    "core:author": "SIMANEEM SDR Analyzer",
                    "core:version": "1.0.0",
                    "core:description": f"Grabación SDR - Modo: {self.mode}",
                },
                "captures": [
                    {
                        "core:sample_start": 0,
                        "core:frequency": self.freq_hz,
                        "core:datetime": datetime.now(timezone.utc).isoformat(),
                    }
                ],
                "annotations": []
            }
            
            # Guardar archivo JSON
            with open(self.sigmf_meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"📄 Metadatos SigMF guardados: {self.sigmf_meta_file}")
            self.logger.info(f"   Sample Rate: {self.sample_rate/1e6:.2f} MHz")
            self.logger.info(f"   Frequency: {self.freq_hz/1e6:.3f} MHz")
            self.logger.info(f"   Datatype: ci16_le (complex int16)")
            
            return True
            
        except Exception as exc:
            self.logger.error(f"Error guardando metadatos SigMF: {exc}")
            return False

    def _create_fallback_metadata(self):
        """Guardar metadata en formato .meta para compatibilidad"""
        try:
            with open(self.fallback_meta_file, 'w', encoding='utf-8') as f:
                f.write(f"Filename: {os.path.basename(self.fallback_bin_file)}\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Frequency: {self.freq_hz/1e6:.3f} MHz\n")
                f.write(f"Sample Rate: {self.sample_rate/1e6:.2f} MHz\n")
                f.write(f"Mode: {self.mode}\n")
                f.write(f"Format: int16 IQ interleaved\n")
                f.write(f"Bytes per sample: 4\n")
                f.write(f"Samples per buffer: {self.samples_per_buffer}\n")
            self.logger.info(f"📄 Metadata compatibilidad guardada: {self.fallback_meta_file}")
        except Exception as exc:
            self.logger.error(f"Error guardando metadata compatibilidad: {exc}")

    def _update_sigmf_metadata(self):
        """Actualiza el archivo .sigmf-meta con duración real y anotaciones"""
        try:
            if not os.path.exists(self.sigmf_meta_file):
                self.logger.warning(f"⚠️ Archivo .sigmf-meta no existe, no se puede actualizar")
                return
            
            # Leer archivo existente
            with open(self.sigmf_meta_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # Asegurar que annotations existe
            if 'annotations' not in metadata:
                metadata['annotations'] = []
            
            elapsed = time.time() - self.start_time if self.start_time else 0
            
            # Añadir anotación
            metadata['annotations'].append({
                "core:sample_start": 0,
                "core:sample_count": int(self.samples_written),
                "core:description": f"Grabación completada - Duración real: {elapsed:.2f}s",
                "core:freq_lower_edge": self.freq_hz - self.sample_rate/2,
                "core:freq_upper_edge": self.freq_hz + self.sample_rate/2,
            })
            
            # Guardar archivo actualizado
            with open(self.sigmf_meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"📊 Metadata SigMF actualizada: {self.samples_written} muestras, {elapsed:.1f}s")
            
        except Exception as exc:
            self.logger.error(f"Error actualizando metadata SigMF: {exc}")

    def _update_fallback_metadata(self):
        """Actualiza metadata de compatibilidad"""
        try:
            elapsed = time.time() - self.start_time if self.start_time else 0
            with open(self.fallback_meta_file, 'a', encoding='utf-8') as f:
                f.write(f"Duration: {elapsed:.2f} s\n")
                f.write(f"File size: {self.bytes_written/1e6:.2f} MB\n")
                f.write(f"Samples: {self.samples_written}\n")
        except Exception as exc:
            self.logger.error(f"Error actualizando metadata compatibilidad: {exc}")

    # ------------------------------------------------------------------
    # MÉTODOS DE CONTROL
    # ------------------------------------------------------------------

    def stop_recording(self):
        self.logger.info("⏹ Deteniendo grabación...")
        self._stop_flag = True
        self.stop_event.set()

    def pause_recording(self):
        self._pause_flag = True
        self.logger.info("⏸ Pausada")

    def resume_recording(self):
        self._pause_flag = False
        self.logger.info("▶ Reanudada")

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

        if self.data_file:
            self._update_sigmf_metadata()
            self._update_fallback_metadata()
            self.data_file.close()
            self.data_file = None

            # También crear archivo .bin para compatibilidad (copiar datos)
            self._create_bin_copy()

        self.is_recording = False
        self.recording_stopped.emit()
        self.logger.info("⏹ Monitor detenido")

    def _create_bin_copy(self):
        """Crea una copia .bin del archivo .sigmf-data para compatibilidad"""
        try:
            import shutil
            if os.path.exists(self.sigmf_data_file) and not os.path.exists(self.fallback_bin_file):
                shutil.copy2(self.sigmf_data_file, self.fallback_bin_file)
                self.logger.info(f"📋 Copia .bin creada: {self.fallback_bin_file}")
        except Exception as exc:
            self.logger.error(f"Error creando copia .bin: {exc}")

    # ------------------------------------------------------------------
    # MÉTODOS DE CAPTURA Y ESCRITURA
    # ------------------------------------------------------------------

    def _start_threads(self):
        self.capture_thread = threading.Thread(target=self._capture_loop, name="IQCapture", daemon=True)
        self.write_thread = threading.Thread(target=self._write_loop, name="IQWrite", daemon=True)
        self.capture_thread.start()
        self.write_thread.start()

    def _join_threads(self, timeout: float = 3.0):
        for t in (self.capture_thread, self.write_thread):
            if t and t.is_alive():
                t.join(timeout=timeout)

    def _clear_queue(self):
        while not self.write_queue.empty():
            try:
                self.write_queue.get_nowait()
            except queue.Empty:
                break

    def _capture_loop(self):
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

            iq_int16 = self._convert_to_int16(iq_data)

            try:
                self.write_queue.put(iq_int16, timeout=0.1)
                local_count += 1
                self.samples_written += len(iq_data)
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

        self.write_queue.put(None)
        self.logger.info("⏹ Captura detenida")

    def _convert_to_int16(self, iq_data: np.ndarray) -> np.ndarray:
        """Convierte IQ a int16 interleaved"""
        real = np.round(iq_data.real * 2048.0).astype(np.int16)
        imag = np.round(iq_data.imag * 2048.0).astype(np.int16)

        out = self.output_buffer
        out[0::2] = real
        out[1::2] = imag
        return out.copy()

    def _write_loop(self):
        self.logger.info("💾 Escritura iniciada")
        bufs_written = 0
        local_bytes = 0

        while not self.stop_event.is_set() or not self.write_queue.empty():
            try:
                item = self.write_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                break

            self.data_file.write(item.tobytes())
            self.data_file.flush()

            bufs_written += 1
            local_bytes += item.nbytes

            if bufs_written % 100 == 0:
                with self.stats_lock:
                    self.bytes_written = local_bytes

        with self.stats_lock:
            self.bytes_written = local_bytes

        self.logger.info(
            f"⏹ Escritura detenida — {bufs_written} bufs, "
            f"{local_bytes/1e6:.1f} MB, {self.samples_written} muestras"
        )

    def _check_limits(self) -> bool:
        if self.mode == 'time' and self.time_limit_sec > 0:
            if time.time() - self.start_time >= self.time_limit_sec:
                self.logger.info("⏱ Límite de tiempo alcanzado")
                return True

        if self.mode == 'size' and self.size_limit_bytes > 0:
            with self.stats_lock:
                written = self.bytes_written
            if written >= self.size_limit_bytes:
                self.logger.info(f"📦 Límite de tamaño alcanzado ({written/1e6:.1f} MB)")
                return True

        return False

    def _emit_stats(self):
        with self.stats_lock:
            elapsed = time.time() - self.start_time if self.start_time else 0
            stats = {
                'bytes_written': self.bytes_written,
                'buffers_written': self.buffers_captured,
                'elapsed_time': elapsed,
                'file_size_mb': self.bytes_written / 1e6,
                'samples_written': self.samples_written,
                'expected_buffers_per_sec': self.blocks_per_second,
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
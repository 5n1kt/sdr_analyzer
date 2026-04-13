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

    CORRECCIONES v2:
    ─────────────────
    1. _write_loop: fsync() explícito al cerrar el archivo → previene truncamiento
       por page-cache del kernel en Lubuntu/ext4.
    2. _write_loop: bytes_written se actualiza en CADA buffer (no cada 100) para
       que _check_limits() en modo SIZE sea exacto.
    3. _update_sigmf_metadata: sample_count se calcula desde bytes_written reales
       (no desde samples_written del capture loop, que puede estar desfasado por
       la cola asíncrona).
    4. _create_bin_copy: se elimina — el reproductor ya abre .sigmf-data
       directamente; la copia .bin era redundante y podía quedar incompleta si
       el proceso era interrumpido antes de terminar shutil.copy2.
    """

    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal()
    stats_updated = pyqtSignal(dict)

    def __init__(self, ring_buffer, sample_rate: float, freq_hz: float):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        self.ring_buffer = ring_buffer
        self.iq_processor = None   # referencia para attach/detach del recording_buffer
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

        # Buffer de salida pre-alocado
        self.output_buffer = np.empty(self.samples_per_buffer * 2, dtype=np.int16)

        # Cola de escritura
        self.write_queue = queue.Queue(maxsize=5000)
        self.stop_event = threading.Event()

        self.capture_thread = None
        self.write_thread = None

        # Estadísticas — bytes_written es la fuente de verdad para tamaño real
        self.stats_lock = threading.Lock()
        self.bytes_written = 0          # bytes efectivamente llegados a disco
        self.buffers_captured = 0
        self.start_time = 0.0
        self.last_log_time = 0.0
        self.samples_written = 0        # muestras complejas capturadas (para log)

        self.blocks_per_second = self.sample_rate / self.samples_per_buffer

        self.logger.info(
            f"✅ IQRecorderSimple — SR={self.sample_rate/1e6:.1f} MHz  "
            f"buf={self.samples_per_buffer}  blk/s={self.blocks_per_second:.0f}"
        )

    # ------------------------------------------------------------------
    # CONFIGURACIÓN
    # ------------------------------------------------------------------

    def set_processor(self, iq_processor):
        """Registra referencia al IQProcessorZeroCopy para attach/detach del buffer."""
        self.iq_processor = iq_processor

    def configure_recording(self, base_filename: str, mode: str = 'continuous',
                            time_limit: int = 0, size_limit_mb: float = 0):
        """
        Configura la grabación.
        base_filename: nombre base sin extensión
            ej: recordings/IQ_2400MHz_2MSPS_TIME10s_20260323_141111
        """
        self.sigmf_data_file  = f"{base_filename}.sigmf-data"
        self.sigmf_meta_file  = f"{base_filename}.sigmf-meta"
        self.fallback_bin_file  = f"{base_filename}.bin"
        self.fallback_meta_file = f"{base_filename}.meta"
        self.mode = mode
        self.time_limit_sec   = time_limit
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

            # PASO 1: Abrir archivo de datos en modo escritura binaria
            self.data_file = open(self.sigmf_data_file, 'wb')

            # PASO 2: Crear metadata SigMF inicial
            sigmf_success = self._create_sigmf_metadata()
            if not sigmf_success:
                self.logger.warning("⚠️ SigMF metadata creation failed, using fallback format only")

            # PASO 3: Crear fallback .meta para compatibilidad con reproductores legacy
            self._create_fallback_metadata()

            self.stop_event.clear()
            self.is_recording  = True
            self._stop_flag    = False
            self._pause_flag   = False
            self.start_time    = time.time()
            self.last_log_time = self.start_time
            self.bytes_written = 0
            self.buffers_captured = 0
            self.samples_written  = 0

            # Activar escritura en recording_buffer ANTES de iniciar threads
            # para evitar race condition: _capture_loop no debe arrancar con
            # recording_active=False y perder los primeros bloques del hardware.
            if self.iq_processor and hasattr(self.iq_processor, "attach_recording_buffer"):
                self.iq_processor.attach_recording_buffer(self.ring_buffer)

            self._clear_queue()
            self._start_threads()
            self.start()   # inicia el QThread (run = monitor de stats/límites)

            # Emitir señal con el archivo .sigmf-data (fuente de verdad)
            self.recording_started.emit(self.sigmf_data_file)
            self.logger.info(f"⏺ Grabación iniciada: {self.sigmf_data_file}")

        except Exception as exc:
            self.logger.error(f"Error iniciando grabación: {exc}")
            import traceback
            traceback.print_exc()

    def _create_sigmf_metadata(self):
        """
        Crea el archivo .sigmf-meta con JSON válido.
        """
        try:
            metadata = {
                "global": {
                    "core:datatype":    "ci16_le",
                    "core:sample_rate": self.sample_rate,
                    "core:hw":          "BladeRF 2.0 micro",
                    "core:author":      "SIMANEEM SDR Analyzer",
                    "core:version":     "1.0.0",
                    "core:description": f"Grabación SDR - Modo: {self.mode}",
                },
                "captures": [
                    {
                        "core:sample_start": 0,
                        "core:frequency":    self.freq_hz,
                        "core:datetime":     datetime.now(timezone.utc).isoformat(),
                    }
                ],
                "annotations": []
            }

            with open(self.sigmf_meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            self.logger.info(f"📄 Metadatos SigMF guardados: {self.sigmf_meta_file}")
            self.logger.info(f"   Sample Rate: {self.sample_rate/1e6:.2f} MHz")
            self.logger.info(f"   Frequency:   {self.freq_hz/1e6:.3f} MHz")
            self.logger.info(f"   Datatype:    ci16_le (complex int16)")
            return True

        except Exception as exc:
            self.logger.error(f"Error guardando metadatos SigMF: {exc}")
            return False

    def _create_fallback_metadata(self):
        """Guarda metadata en formato .meta para reproductores legacy."""
        try:
            with open(self.fallback_meta_file, 'w', encoding='utf-8') as f:
                f.write(f"Filename: {os.path.basename(self.sigmf_data_file)}\n")
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
        """
        Actualiza .sigmf-meta con duración y sample_count reales al finalizar.

        CORRECCIÓN: sample_count se calcula desde bytes_written (bytes reales
        confirmados a disco), NO desde samples_written del capture loop.
        La diferencia puede ser significativa cuando la cola de escritura
        todavía tiene datos pendientes al momento de contabilizar.
        """
        try:
            if not os.path.exists(self.sigmf_meta_file):
                self.logger.warning("⚠️ .sigmf-meta no existe, no se puede actualizar")
                return

            with open(self.sigmf_meta_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            if 'annotations' not in metadata:
                metadata['annotations'] = []

            elapsed = time.time() - self.start_time if self.start_time else 0

            # ── CLAVE: derivar sample_count desde bytes reales en disco ──────
            # Formato ci16_le: 2 bytes I + 2 bytes Q = 4 bytes por muestra compleja
            real_sample_count = self.bytes_written // 4
            # ─────────────────────────────────────────────────────────────────

            metadata['annotations'].append({
                "core:sample_start": 0,
                "core:sample_count": real_sample_count,
                "core:description":  f"Grabación completada - Duración real: {elapsed:.2f}s",
                "core:freq_lower_edge": self.freq_hz - self.sample_rate / 2,
                "core:freq_upper_edge": self.freq_hz + self.sample_rate / 2,
            })

            with open(self.sigmf_meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            self.logger.info(
                f"📊 Metadata SigMF actualizada: "
                f"{real_sample_count:,} muestras reales | "
                f"{self.bytes_written/1e6:.2f} MB | {elapsed:.1f}s"
            )

        except Exception as exc:
            self.logger.error(f"Error actualizando metadata SigMF: {exc}")

    def _update_fallback_metadata(self):
        """Actualiza el .meta de compatibilidad con datos finales."""
        try:
            elapsed = time.time() - self.start_time if self.start_time else 0
            with open(self.fallback_meta_file, 'a', encoding='utf-8') as f:
                f.write(f"Duration: {elapsed:.2f} s\n")
                f.write(f"File size: {self.bytes_written/1e6:.2f} MB\n")
                f.write(f"Samples: {self.bytes_written // 4}\n")
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
        """Monitor de stats y límites (corre en el QThread)."""
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
            # Actualizar metadata ANTES de cerrar el archivo para que
            # bytes_written refleje exactamente lo que llegó a disco.
            self._update_sigmf_metadata()
            self._update_fallback_metadata()

            # ── CORRECCIÓN 1: fsync explícito ──────────────────────────────
            # En Linux/ext4, flush() vacía el buffer de Python pero el kernel
            # puede retener el contenido en page-cache. Si el proceso termina
            # antes de que el OS lo escriba, el archivo queda truncado.
            # fsync() bloquea hasta que el OS confirma escritura física.
            try:
                self.data_file.flush()
                os.fsync(self.data_file.fileno())
                self.logger.info("✅ fsync completado — datos garantizados en disco")
            except OSError as exc:
                self.logger.warning(f"⚠️ fsync falló (ignorable si FS no lo soporta): {exc}")

            self.data_file.close()
            self.data_file = None

        self.is_recording = False
        # Desactivar escritura en recording_buffer ANTES de emitir señal
        # Esto es inmediato — no espera el event loop del widget Qt
        if self.iq_processor and hasattr(self.iq_processor, "detach_recording_buffer"):
            self.iq_processor.detach_recording_buffer()
        self.recording_stopped.emit()
        self.logger.info("⏹ Monitor detenido")

    # ------------------------------------------------------------------
    # CAPTURA Y ESCRITURA
    # ------------------------------------------------------------------

    def _start_threads(self):
        self.capture_thread = threading.Thread(
            target=self._capture_loop, name="IQCapture", daemon=True)
        self.write_thread = threading.Thread(
            target=self._write_loop, name="IQWrite", daemon=True)
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

        # Señal de fin para que _write_loop drene la cola y termine
        self.write_queue.put(None)
        self.logger.info("⏹ Captura detenida")

    def _convert_to_int16(self, iq_data: np.ndarray) -> np.ndarray:
        """Convierte IQ complejo normalizado a int16 interleaved (ci16_le)."""
        real = np.round(iq_data.real * 2048.0).astype(np.int16)
        imag = np.round(iq_data.imag * 2048.0).astype(np.int16)
        out = self.output_buffer
        out[0::2] = real
        out[1::2] = imag
        return out.copy()

    def _write_loop(self):
        """
        Hilo dedicado a escritura a disco.

        CORRECCIÓN 2: bytes_written se actualiza en CADA buffer, no cada 100.
        Esto garantiza que _check_limits() en modo SIZE reacciona con exactitud
        al límite configurado, sin sobrepasar hasta ~megabytes de margen.
        """
        self.logger.info("💾 Escritura iniciada")
        bufs_written = 0
        local_bytes  = 0

        while not self.stop_event.is_set() or not self.write_queue.empty():
            try:
                item = self.write_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                break

            raw = item.tobytes()
            self.data_file.write(raw)
            # flush por buffer (sin fsync — el fsync final lo hace run())
            self.data_file.flush()

            bufs_written += 1
            local_bytes  += len(raw)

            # ── CORRECCIÓN 2: actualizar bytes_written en cada buffer ────────
            with self.stats_lock:
                self.bytes_written = local_bytes
            # ─────────────────────────────────────────────────────────────────

        # Asegurar que el valor final quede registrado
        with self.stats_lock:
            self.bytes_written = local_bytes

        self.logger.info(
            f"⏹ Escritura detenida — {bufs_written} bufs, "
            f"{local_bytes/1e6:.2f} MB, {local_bytes//4:,} muestras reales"
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
                self.logger.info(f"📦 Límite de tamaño alcanzado ({written/1e6:.2f} MB)")
                return True

        return False

    def _emit_stats(self):
        with self.stats_lock:
            elapsed = time.time() - self.start_time if self.start_time else 0
            stats = {
                'bytes_written':             self.bytes_written,
                'buffers_written':           self.buffers_captured,
                'elapsed_time':              elapsed,
                'file_size_mb':              self.bytes_written / 1e6,
                'samples_written':           self.bytes_written // 4,
                'expected_buffers_per_sec':  self.blocks_per_second,
            }
        self.stats_updated.emit(stats)

    def _log_stats(self):
        with self.stats_lock:
            actual = self.buffers_captured
            self.buffers_captured = 0
        pct = (actual / self.blocks_per_second * 100) if self.blocks_per_second > 0 else 0
        self.logger.info(
            f"📊 {actual}/{self.blocks_per_second:.0f} bufs/s  "
            f"({pct:.0f}%)  {self.bytes_written/1e6:.2f} MB"
        )

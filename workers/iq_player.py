# workers/iq_player.py
# -*- coding: utf-8 -*-

import numpy as np
import os
import time
import re
from PyQt5.QtCore import QThread, pyqtSignal
import logging


class IQPlayer(QThread):
    """
    Hilo de reproducción que lee archivos IQ raw y los inyecta en el pipeline.
    Soporta formatos: .bin (con .meta) y .sigmf-data (con .sigmf-meta)
    """

    playback_started = pyqtSignal()
    playback_paused = pyqtSignal()
    playback_stopped = pyqtSignal()
    playback_finished = pyqtSignal()
    progress_updated = pyqtSignal(float, float)
    buffer_ready = pyqtSignal(np.ndarray)
    error_occurred = pyqtSignal(str)
    metadata_loaded = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        self.filename = None
        self.file = None
        self.total_bytes = 0
        self.position = 0

        self.sample_rate = 2e6
        self.freq_mhz = 100.0

        self.samples_per_buffer = 8192
        self.bytes_per_buffer = self.samples_per_buffer * 4
        self.speed = 1.0
        self.loop = False

        self.is_playing = False
        self.is_paused = False
        self._stop_flag = False

        self.read_buffer = bytearray(self.bytes_per_buffer)

        self.metadata = {
            'frequency': 100.0,
            'sample_rate': 2e6,
            'duration': 0,
            'timestamp': '',
            'file_size_mb': 0
        }

        self.target_blocks_per_second = 30
        self.expected_interval = 1.0 / self.target_blocks_per_second

        self.logger.info("✅ IQPlayer creado")

    def __del__(self):
        self.close()

    # ------------------------------------------------------------------
    # CARGA DE ARCHIVOS - DETECCIÓN AUTOMÁTICA DE FORMATO
    # ------------------------------------------------------------------

    # workers/iq_player.py - Añadir soporte para leer SigMF

    def load_file(self, filename):
        """Carga archivo IQ con soporte para SigMF y formato legacy"""
        try:
            self.filename = filename
            
            # Detectar formato por extensión
            if filename.endswith('.sigmf-data') or os.path.exists(filename.replace('.sigmf-data', '.sigmf-meta')):
                return self._load_sigmf_file(filename)
            elif filename.endswith('.bin') or filename.endswith('.sigmf-meta'):
                # Si es .meta, buscar el .bin correspondiente
                if filename.endswith('.meta'):
                    filename = filename.replace('.meta', '.bin')
                return self._load_raw_file(filename)
            else:
                # Intentar como raw
                return self._load_raw_file(filename)
                
        except Exception as e:
            self.logger.error(f"Error cargando archivo: {e}")
            return False

    def _load_sigmf_file(self, filename):
        """Carga archivo SigMF usando JSON manual (robusto)"""
        try:
            import json
            
            # Buscar archivo .sigmf-meta
            base_name = filename.replace('.sigmf-data', '')
            meta_file = base_name + '.sigmf-meta'
            
            if not os.path.exists(meta_file):
                self.logger.warning(f"⚠️ Archivo .sigmf-meta no encontrado: {meta_file}")
                return self._load_raw_file(filename.replace('.sigmf-data', '.bin'))
            
            # Leer metadata
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            
            # Extraer sample_rate
            if 'global' in meta and 'core:sample_rate' in meta['global']:
                self.sample_rate = float(meta['global']['core:sample_rate'])
                self.metadata['sample_rate'] = self.sample_rate
                self.logger.info(f"📡 Sample Rate: {self.sample_rate/1e6:.2f} MHz")
            
            # Extraer frecuencia
            if 'captures' in meta and len(meta['captures']) > 0:
                if 'core:frequency' in meta['captures'][0]:
                    self.freq_mhz = float(meta['captures'][0]['core:frequency']) / 1e6
                    self.metadata['frequency'] = self.freq_mhz
                    self.logger.info(f"📡 Frecuencia: {self.freq_mhz:.3f} MHz")
            
            # Abrir archivo de datos
            self.file = open(filename, 'rb')
            self.file.seek(0, 2)
            self.total_bytes = self.file.tell()
            self.position = 0
            self.file.seek(0)
            
            self.metadata['file_size_mb'] = self.total_bytes / 1e6


            #self._calculate_duration()
            # ===== CALCULAR DURACIÓN CORRECTAMENTE =====
            # Formato: int16 IQ interleaved = 4 bytes por muestra compleja
            samples = self.total_bytes / 4
            self.metadata['duration'] = samples / self.sample_rate if self.sample_rate > 0 else 0
            
            # Si hay anotación con sample_count, usarla para verificar
            if 'annotations' in meta and len(meta['annotations']) > 0:
                for ann in meta['annotations']:
                    if 'core:sample_count' in ann:
                        ann_samples = ann['core:sample_count']
                        self.logger.info(f"📊 Anotación sample_count: {ann_samples:,} muestras")
                        # Usar el valor de anotación si es más preciso
                        if ann_samples > 0:
                            self.metadata['duration'] = ann_samples / self.sample_rate
            
            self.logger.info(f"📂 Archivo SigMF cargado: {filename}")
            self.logger.info(f"   Tamaño: {self.total_bytes/1e6:.2f} MB")
            self.logger.info(f"   Muestras: {samples/1e6:.2f}M")
            self.logger.info(f"   Sample Rate: {self.sample_rate/1e6:.2f} MHz")
            self.logger.info(f"   Duración: {self.metadata['duration']:.2f} s")

            self.metadata_loaded.emit(self.metadata)
            return True
            
        except Exception as e:
            self.logger.error(f"Error cargando SigMF: {e}")
            import traceback
            traceback.print_exc()
            return False

    

    def _load_raw_file(self, filename):
        """
        Carga un archivo IQ raw (.bin) con su metadata asociada (.meta)
        """
        try:
            # Asegurar extensión .bin
            if not filename.endswith('.bin'):
                filename = filename.replace('.sigmf-data', '.bin')

            # Abrir archivo binario
            self.file = open(filename, 'rb')
            self.file.seek(0, 2)
            self.total_bytes = self.file.tell()
            self.position = 0
            self.file.seek(0)

            self.metadata['file_size_mb'] = self.total_bytes / 1e6

            # Buscar archivo de metadata (.meta)
            meta_file = filename.replace('.bin', '.meta')
            if os.path.exists(meta_file):
                self.logger.info(f"📄 Metadata encontrada: {os.path.basename(meta_file)}")
                self._load_metadata(meta_file)
            else:
                self.logger.info(f"⚠️ Sin archivo .meta, usando valores por defecto")
                self._infer_sample_rate_from_filename()

            # Calcular duración y verificar consistencia
            self._calculate_duration()

            # Log de información
            self.logger.info(f"📂 Archivo cargado: {filename}")
            self.logger.info(f"   Tamaño: {self.total_bytes/1e6:.1f} MB")
            self.logger.info(f"   Frecuencia: {self.metadata['frequency']} MHz")
            self.logger.info(f"   Sample Rate: {self.metadata['sample_rate']/1e6:.1f} MHz")
            self.logger.info(f"   Duración: {self.metadata['duration']:.2f} s")

            # Verificar coherencia
            if self.metadata['duration'] > 0 and self.total_bytes > 0:
                actual_samples = self.total_bytes / 4
                actual_sr = actual_samples / self.metadata['duration']

                self.logger.info("=" * 60)
                self.logger.info("🔍 VERIFICACIÓN DE COHERENCIA:")
                self.logger.info(f"   Tamaño archivo: {self.total_bytes/1e6:.2f} MB")
                self.logger.info(f"   Muestras (int16): {actual_samples/1e6:.2f}M")
                self.logger.info(f"   Duración metadata: {self.metadata['duration']:.2f} s")
                self.logger.info(f"   Sample Rate REAL: {actual_sr/1e6:.2f} MHz")
                self.logger.info(f"   Sample Rate metadata: {self.sample_rate/1e6:.2f} MHz")

                if abs(actual_sr - self.sample_rate) / max(self.sample_rate, 1) > 0.1:
                    self.logger.warning("⚠️ INCONSISTENCIA: El sample_rate real no coincide con metadata")
                    self.logger.warning(f"   Usando sample_rate real ({actual_sr/1e6:.2f} MHz) para reproducción correcta")
                    self.sample_rate = actual_sr
                    self.metadata['sample_rate'] = actual_sr
                    self.metadata['duration'] = self.total_bytes / (self.sample_rate * 4)
                    self.logger.info(f"   Duración recalculada: {self.metadata['duration']:.2f} s")
                self.logger.info("=" * 60)

            self.metadata_loaded.emit(self.metadata)
            return True

        except Exception as e:
            self.logger.error(f"Error cargando archivo raw: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _load_metadata(self, meta_file):
        """Carga metadata del archivo .meta con manejo robusto de encoding"""
        try:
            # Intentar con diferentes encodings
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'utf-16']
            content = None
            used_encoding = None

            for enc in encodings:
                try:
                    with open(meta_file, 'r', encoding=enc) as f:
                        content = f.read()
                    used_encoding = enc
                    self.logger.debug(f"Metadata leída con encoding: {enc}")
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue

            if content is None:
                # Último recurso: leer en modo binario e ignorar errores
                with open(meta_file, 'rb') as f:
                    raw = f.read()
                    # Reemplazar bytes no válidos
                    content = raw.decode('utf-8', errors='replace')
                    self.logger.warning("⚠️ Metadata leída con reemplazo de caracteres")

            # Parsear línea por línea
            for line in content.splitlines():
                line = line.strip()
                if not line or ':' not in line:
                    continue

                # Dividir solo en el primer ':'
                parts = line.split(':', 1)
                if len(parts) != 2:
                    continue
                    
                key = parts[0].strip()
                value = parts[1].strip()

                if 'Frequency' in key:
                    # Extraer el número antes de 'MHz'
                    try:
                        # Buscar número en el string
                        import re
                        match = re.search(r'([\d\.]+)', value)
                        if match:
                            self.metadata['frequency'] = float(match.group(1))
                            self.freq_mhz = float(match.group(1))
                            self.logger.debug(f"Frecuencia cargada: {self.freq_mhz} MHz")
                    except (ValueError, IndexError) as e:
                        self.logger.warning(f"No se pudo parsear frecuencia: {value}")
                        
                elif 'Sample Rate' in key:
                    try:
                        import re
                        match = re.search(r'([\d\.]+)', value)
                        if match:
                            sr_value = float(match.group(1))
                            self.metadata['sample_rate'] = sr_value * 1e6
                            self.sample_rate = sr_value * 1e6
                            self.logger.debug(f"Sample Rate cargado: {sr_value} MHz")
                    except (ValueError, IndexError) as e:
                        self.logger.warning(f"No se pudo parsear sample rate: {value}")
                        
                elif 'Duration' in key:
                    try:
                        import re
                        match = re.search(r'([\d\.]+)', value)
                        if match:
                            self.metadata['duration'] = float(match.group(1))
                            self.logger.debug(f"Duración cargada: {self.metadata['duration']} s")
                    except (ValueError, IndexError) as e:
                        self.logger.warning(f"No se pudo parsear duración: {value}")
                        
                elif 'Timestamp' in key:
                    self.metadata['timestamp'] = value

            # Validar que los valores sean razonables
            if self.freq_mhz < 1:
                self.logger.warning(f"⚠️ Frecuencia anormalmente baja: {self.freq_mhz} MHz, usando valor por defecto 100 MHz")
                self.freq_mhz = 100.0
                self.metadata['frequency'] = 100.0

        except Exception as e:
            self.logger.error(f"Error cargando metadata: {e}")
            import traceback
            traceback.print_exc()

    def _infer_sample_rate_from_filename(self):
        """Intenta inferir sample rate desde el nombre del archivo"""
        if not self.filename:
            return False

        try:
            match = re.search(r'(\d+)MSPS', self.filename, re.IGNORECASE)
            if match:
                sr_msps = float(match.group(1))
                self.sample_rate = sr_msps * 1e6
                self.metadata['sample_rate'] = self.sample_rate
                self.logger.info(f"📡 Sample rate inferido del nombre: {sr_msps:.0f} MSPS")
                return True

            match = re.search(r'(\d+)M', self.filename, re.IGNORECASE)
            if match:
                sr_msps = float(match.group(1))
                if sr_msps < 100:
                    self.sample_rate = sr_msps * 1e6
                    self.metadata['sample_rate'] = self.sample_rate
                    self.logger.info(f"📡 Sample rate inferido del nombre: {sr_msps:.0f} MSPS")
                    return True

        except Exception as e:
            self.logger.debug(f"No se pudo inferir sample rate: {e}")

        return False

    def _calculate_duration(self):
        """Calcula duración del archivo"""
        if self.sample_rate > 0 and self.total_bytes > 0:
            calculated_duration = self.total_bytes / (self.sample_rate * 4)

            if self.metadata['duration'] == 0:
                self.metadata['duration'] = calculated_duration
            else:
                if abs(self.metadata['duration'] - calculated_duration) > 0.1:
                    self.logger.debug(
                        f"Duración: metadata={self.metadata['duration']:.2f}s, "
                        f"calculada={calculated_duration:.2f}s"
                    )

    # ------------------------------------------------------------------
    # MÉTODOS DE CONTROL (sin cambios)
    # ------------------------------------------------------------------

    def configure(self, samples_per_buffer=8192, speed=1.0, loop=False):
        self.samples_per_buffer = samples_per_buffer
        self.bytes_per_buffer = samples_per_buffer * 4
        self.speed = speed
        self.loop = loop
        self.read_buffer = bytearray(self.bytes_per_buffer)

        if self.metadata['duration'] > 0 and self.total_bytes > 0:
            total_buffers = self.total_bytes / self.bytes_per_buffer
            desired_time = self.metadata['duration'] / speed
            self.target_blocks_per_second = total_buffers / desired_time
            self.expected_interval = 1.0 / self.target_blocks_per_second

            self.logger.info(f"⚙️ Configuración reproducción:")
            self.logger.info(f"   Speed: {speed}x")
            self.logger.info(f"   Duración archivo: {self.metadata['duration']:.1f} s")
            self.logger.info(f"   Tiempo deseado: {desired_time:.1f} s")
            self.logger.info(f"   Buffers/seg: {self.target_blocks_per_second:.1f}")
        else:
            self.target_blocks_per_second = 30 * speed
            self.expected_interval = 1.0 / self.target_blocks_per_second

    def start_playback(self):
        if not self.file:
            self.error_occurred.emit("No hay archivo cargado")
            return

        self.is_playing = True
        self.is_paused = False
        self._stop_flag = False
        self.start()
        self.playback_started.emit()
        self.logger.info("▶ Reproducción iniciada")

    def pause_playback(self):
        self.is_paused = True
        self.playback_paused.emit()
        self.logger.info("⏸ Reproducción pausada")

    def resume_playback(self):
        self.is_paused = False
        self.playback_started.emit()
        self.logger.info("▶ Reproducción reanudada")

    def stop_playback(self):
        self._stop_flag = True
        self.is_playing = False

    def seek(self, position_bytes):
        if self.file:
            self.position = max(0, min(position_bytes, self.total_bytes - self.bytes_per_buffer))
            self.file.seek(self.position)
            self.progress_updated.emit(self.position, self.total_bytes)



    def close(self):
        """Cierra el archivo y libera memoria, incluyendo archivos temporales SigMF"""
        self._stop_flag = True
        self.wait(2000)
        
        if self.file:
            self.file.close()
            self.file = None
        
        # Limpiar archivo temporal si existe
        if hasattr(self, '_temp_file_path') and self._temp_file_path:
            try:
                os.unlink(self._temp_file_path)
            except:
                pass
        
        self.logger.info("📂 Archivo cerrado")


    # ------------------------------------------------------------------
    # MÉTODOS DE REPRODUCCIÓN
    # ------------------------------------------------------------------

    def run(self):
        self.logger.info("🚀 Hilo de reproducción ejecutándose")

        last_block_time = time.time()
        blocks_sent = 0
        start_time = time.time()

        try:
            while not self._stop_flag and self.is_playing:
                if self.is_paused:
                    self.msleep(10)
                    continue

                current_time = time.time()
                elapsed = current_time - last_block_time

                if elapsed < self.expected_interval:
                    sleep_time = self.expected_interval - elapsed
                    if sleep_time > 0:
                        self.msleep(int(sleep_time * 1000))

                last_block_time = time.time()

                iq_data = self._read_next_buffer()

                if iq_data is None:
                    self.logger.info(f"🏁 Fin del archivo después de {blocks_sent} buffers")
                    break

                blocks_sent += 1
                self.buffer_ready.emit(iq_data)
                self.progress_updated.emit(float(self.position), float(self.total_bytes))

        except Exception as e:
            self.logger.error(f"Error en reproducción: {e}")
            self.error_occurred.emit(str(e))

        finally:
            self.is_playing = False

            if self.total_bytes > 0:
                self.progress_updated.emit(float(self.total_bytes), float(self.total_bytes))

            self.playback_finished.emit()
            self.playback_stopped.emit()

            elapsed_total = time.time() - start_time
            self.logger.info(f"⏹ Hilo detenido ({blocks_sent} buffers, {elapsed_total:.1f}s)")

    def _read_next_buffer(self):
        try:
            bytes_to_read = min(self.bytes_per_buffer, self.total_bytes - self.position)

            if bytes_to_read <= 0:
                if self.loop:
                    self.position = 0
                    self.file.seek(0)
                    bytes_to_read = self.bytes_per_buffer
                else:
                    return None

            self.read_buffer = self.file.read(bytes_to_read)
            self.position += len(self.read_buffer)

            if len(self.read_buffer) < self.bytes_per_buffer:
                self.read_buffer += b'\x00' * (self.bytes_per_buffer - len(self.read_buffer))

            return self._bytes_to_complex(self.read_buffer)

        except Exception as e:
            self.logger.error(f"Error leyendo buffer: {e}")
            return None

    def _bytes_to_complex(self, data):
        samples = np.frombuffer(data, dtype=np.int16)

        if len(samples) % 2 != 0:
            samples = samples[:-1]

        i_samples = samples[0::2].astype(np.float32) / 2048.0
        q_samples = samples[1::2].astype(np.float32) / 2048.0

        return (i_samples + 1j * q_samples).astype(np.complex64)
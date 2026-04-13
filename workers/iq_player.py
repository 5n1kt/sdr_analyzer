# workers/iq_player.py
# -*- coding: utf-8 -*-

import numpy as np
import os
import time
import re
import json
from PyQt5.QtCore import QThread, pyqtSignal
import logging


class IQPlayer(QThread):
    """
    Hilo de reproducción que lee archivos IQ raw y los inyecta en el pipeline.
    """

    playback_started  = pyqtSignal()
    playback_paused   = pyqtSignal()
    playback_stopped  = pyqtSignal()
    playback_finished = pyqtSignal()
    progress_updated  = pyqtSignal(float, float)
    buffer_ready      = pyqtSignal(np.ndarray)
    error_occurred    = pyqtSignal(str)
    metadata_loaded   = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        self.filename   = None
        self.file       = None
        self.total_bytes = 0
        self.position   = 0

        self.sample_rate = 2e6
        self.freq_mhz    = 100.0

        self.samples_per_buffer = 8192
        self.bytes_per_buffer   = self.samples_per_buffer * 4
        self.speed = 1.0
        self.loop  = False

        self.is_playing = False
        self.is_paused  = False
        self._stop_flag = False

        self.read_buffer = bytearray(self.bytes_per_buffer)

        self.metadata = {
            'frequency':   100.0,
            'sample_rate': 2e6,
            'duration':    0,
            'timestamp':   '',
            'file_size_mb': 0,
            'mode':        'CONT',  # NUEVO
            'format':      'ci16_le',
            'filename':    ''
        }

        self.target_blocks_per_second = 30
        self.expected_interval = 1.0 / self.target_blocks_per_second
        self._last_progress_emit_time = 0
        self._progress_emit_interval = 0.033  # 33ms entre emisiones (30 fps)
        self._last_position = 0
        self._last_emit_position = 0

        self.logger.info("✅ IQPlayer creado")

    def __del__(self):
        self.close()

    # ------------------------------------------------------------------
    # CARGA DE ARCHIVOS — DETECCIÓN AUTOMÁTICA DE FORMATO
    # ------------------------------------------------------------------

    def load_file(self, filename):
        """Carga archivo IQ con soporte para SigMF y formato legacy."""
        try:
            self.filename = filename
            self.metadata['filename'] = os.path.basename(filename)

            # Detectar formato por extensión
            if filename.endswith('.sigmf-data'):
                return self._load_sigmf_file(filename)
            elif filename.endswith('.bin'):
                return self._load_raw_file(filename)
            else:
                # Intentar detectar automáticamente
                if os.path.exists(filename.replace('.sigmf-data', '.sigmf-meta')):
                    return self._load_sigmf_file(filename)
                else:
                    return self._load_raw_file(filename)

        except Exception as e:
            self.logger.error(f"Error cargando archivo: {e}")
            import traceback
            traceback.print_exc()
            return False

    # workers/iq_player.py

    '''def _load_sigmf_file(self, filename):
        """
        Carga archivo SigMF con parsing completo de metadata.
        """
        try:
            # Normalizar nombre base
            base_name = filename.replace('.sigmf-data', '')
            data_file = base_name + '.sigmf-data'
            meta_file = base_name + '.sigmf-meta'

            if not os.path.exists(data_file):
                self.logger.error(f"❌ Archivo de datos no encontrado: {data_file}")
                return False

            # ===== LEER METADATA SIGMF =====
            mode = 'CONT'  # Valor por defecto
            if os.path.exists(meta_file):
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                # Extraer sample rate
                if 'global' in meta and 'core:sample_rate' in meta['global']:
                    self.sample_rate = float(meta['global']['core:sample_rate'])
                    self.metadata['sample_rate'] = self.sample_rate
                
                # Extraer frecuencia
                if 'captures' in meta and len(meta['captures']) > 0:
                    if 'core:frequency' in meta['captures'][0]:
                        freq_hz = float(meta['captures'][0]['core:frequency'])
                        self.freq_mhz = freq_hz / 1e6
                        self.metadata['frequency'] = self.freq_mhz
                
                # Extraer timestamp
                if 'captures' in meta and len(meta['captures']) > 0:
                    if 'core:datetime' in meta['captures'][0]:
                        self.metadata['timestamp'] = meta['captures'][0]['core:datetime']
                
                # ===== CORRECCIÓN: Extraer modo desde annotations =====
                mode = 'CONT'
                if 'annotations' in meta and len(meta['annotations']) > 0:
                    for ann in meta['annotations']:
                        if 'core:description' in ann:
                            desc = ann['core:description']
                            if 'TIME' in desc or 'time' in desc:
                                mode = 'TIME'
                                break
                            elif 'SIZE' in desc or 'size' in desc:
                                mode = 'SIZE'
                                break
                
                # También verificar en el nombre del archivo
                if mode == 'CONT':
                    if 'TIME' in base_name or 'time' in base_name:
                        mode = 'TIME'
                    elif 'SIZE' in base_name or 'size' in base_name:
                        mode = 'SIZE'
                
                self.metadata['mode'] = mode
                
            else:
                # Inferir modo desde nombre de archivo
                if 'TIME' in base_name:
                    mode = 'TIME'
                elif 'SIZE' in base_name:
                    mode = 'SIZE'
                self.metadata['mode'] = mode

            # ===== ABRIR ARCHIVO DE DATOS =====
            self.file = open(data_file, 'rb')
            self.file.seek(0, 2)
            self.total_bytes = self.file.tell()
            self.position = 0
            self.file.seek(0)

            self.metadata['file_size_mb'] = self.total_bytes / 1e6
            self.metadata['filename'] = os.path.basename(data_file)

            # ===== CALCULAR DURACIÓN REAL =====
            real_samples = self.total_bytes / 4
            self.metadata['duration'] = real_samples / self.sample_rate if self.sample_rate > 0 else 0
            self.metadata['total_bytes'] = self.total_bytes
            self.metadata['samples'] = int(real_samples)

            # ===== LOG COMPLETO =====
            self.logger.info("=" * 60)
            self.logger.info(f"📂 Archivo SigMF cargado: {os.path.basename(data_file)}")
            self.logger.info(f"   📊 Tamaño:     {self.total_bytes/1e6:.2f} MB")
            self.logger.info(f"   📊 Muestras:   {real_samples/1e6:.3f}M")
            self.logger.info(f"   📡 Frecuencia: {self.freq_mhz:.3f} MHz")
            self.logger.info(f"   📡 Sample Rate:{self.sample_rate/1e6:.2f} MHz")
            self.logger.info(f"   ⏱️  Duración:   {self.metadata['duration']:.3f} s")
            self.logger.info(f"   📁 Modo:       {mode}")
            self.logger.info("=" * 60)

            # Emitir metadata inmediatamente
            self.metadata_loaded.emit(self.metadata)
            
            return True

        except Exception as e:
            self.logger.error(f"Error cargando SigMF: {e}")
            import traceback
            traceback.print_exc()
            return False'''
    
    # workers/iq_player.py

    def _load_sigmf_file(self, filename):
        """
        Carga archivo SigMF con parsing completo de metadata.
        """
        try:
            # Normalizar nombre base
            base_name = filename.replace('.sigmf-data', '')
            data_file = base_name + '.sigmf-data'
            meta_file = base_name + '.sigmf-meta'

            if not os.path.exists(data_file):
                self.logger.error(f"❌ Archivo de datos no encontrado: {data_file}")
                return False

            # ===== LEER METADATA SIGMF =====
            mode = 'CONT'
            timestamp = ''
            
            if os.path.exists(meta_file):
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                # Extraer sample rate
                if 'global' in meta and 'core:sample_rate' in meta['global']:
                    self.sample_rate = float(meta['global']['core:sample_rate'])
                    self.metadata['sample_rate'] = self.sample_rate
                
                # Extraer frecuencia
                if 'captures' in meta and len(meta['captures']) > 0:
                    if 'core:frequency' in meta['captures'][0]:
                        freq_hz = float(meta['captures'][0]['core:frequency'])
                        self.freq_mhz = freq_hz / 1e6
                        self.metadata['frequency'] = self.freq_mhz
                    
                    # Extraer timestamp
                    if 'core:datetime' in meta['captures'][0]:
                        timestamp = meta['captures'][0]['core:datetime']
                        self.metadata['timestamp'] = timestamp
                
                # Extraer modo desde annotations
                if 'annotations' in meta and len(meta['annotations']) > 0:
                    for ann in meta['annotations']:
                        if 'core:description' in ann:
                            desc = ann['core:description']
                            if 'TIME' in desc:
                                mode = 'TIME'
                                break
                            elif 'SIZE' in desc:
                                mode = 'SIZE'
                                break
                
                # También verificar en el nombre del archivo
                if mode == 'CONT':
                    if 'TIME' in base_name:
                        mode = 'TIME'
                    elif 'SIZE' in base_name:
                        mode = 'SIZE'
                
                self.metadata['mode'] = mode
                
            else:
                # Inferir modo desde nombre de archivo
                if 'TIME' in base_name:
                    mode = 'TIME'
                elif 'SIZE' in base_name:
                    mode = 'SIZE'
                self.metadata['mode'] = mode

            # ===== ABRIR ARCHIVO DE DATOS =====
            self.file = open(data_file, 'rb')
            self.file.seek(0, 2)
            self.total_bytes = self.file.tell()
            self.position = 0
            self.file.seek(0)

            self.metadata['file_size_mb'] = self.total_bytes / 1e6
            self.metadata['filename'] = os.path.basename(data_file)

            # ===== CALCULAR DURACIÓN REAL =====
            real_samples = self.total_bytes / 4
            self.metadata['duration'] = real_samples / self.sample_rate if self.sample_rate > 0 else 0
            self.metadata['total_bytes'] = self.total_bytes
            self.metadata['samples'] = int(real_samples)
            self.metadata['timestamp'] = timestamp

            # ===== LOG COMPLETO =====
            self.logger.info("=" * 60)
            self.logger.info(f"📂 Archivo SigMF cargado: {os.path.basename(data_file)}")
            self.logger.info(f"   📊 Tamaño:     {self.total_bytes/1e6:.2f} MB")
            self.logger.info(f"   📊 Muestras:   {real_samples/1e6:.3f}M")
            self.logger.info(f"   📡 Frecuencia: {self.freq_mhz:.3f} MHz")
            self.logger.info(f"   📡 Sample Rate:{self.sample_rate/1e6:.2f} MHz")
            self.logger.info(f"   ⏱️  Duración:   {self.metadata['duration']:.3f} s")
            self.logger.info(f"   📁 Modo:       {mode}")
            self.logger.info("=" * 60)

            # Emitir metadata inmediatamente
            self.metadata_loaded.emit(self.metadata)
            
            return True

        except Exception as e:
            self.logger.error(f"Error cargando SigMF: {e}")
            import traceback
            traceback.print_exc()
            return False
        

    def _load_raw_file(self, filename):
        """
        Carga un archivo IQ raw (.bin) con su metadata asociada (.meta).
        CORRECCIÓN: Extrae correctamente frecuencia, sample_rate y modo.
        """
        try:
            # Asegurar extensión .bin
            if not filename.endswith('.bin'):
                filename = filename.replace('.sigmf-data', '.bin')
                if not os.path.exists(filename):
                    self.logger.error(f"❌ Archivo .bin no encontrado: {filename}")
                    return False

            # Abrir archivo de datos
            self.file = open(filename, 'rb')
            self.file.seek(0, 2)
            self.total_bytes = self.file.tell()
            self.position = 0
            self.file.seek(0)

            self.metadata['file_size_mb'] = self.total_bytes / 1e6

            # Buscar archivo .meta asociado
            meta_file = filename.replace('.bin', '.meta')
            if os.path.exists(meta_file):
                self.logger.info(f"📄 Metadata encontrada: {os.path.basename(meta_file)}")
                self._load_metadata_file(meta_file)
            else:
                self.logger.info("⚠️ Sin archivo .meta, usando valores por defecto")
                self._infer_metadata_from_filename(filename)

            # Calcular duración
            self.metadata['duration'] = self.total_bytes / (self.sample_rate * 4) if self.sample_rate > 0 else 0

            # Log completo
            self.logger.info("=" * 60)
            self.logger.info(f"📂 Archivo cargado: {os.path.basename(filename)}")
            self.logger.info(f"   📊 Tamaño:        {self.total_bytes/1e6:.2f} MB")
            self.logger.info(f"   📡 Frecuencia:    {self.freq_mhz:.3f} MHz")
            self.logger.info(f"   📡 Sample Rate:   {self.sample_rate/1e6:.2f} MHz")
            self.logger.info(f"   ⏱️  Duración:      {self.metadata['duration']:.3f} s")
            self.logger.info(f"   📁 Modo:          {self.metadata.get('mode', 'CONT')}")
            self.logger.info("=" * 60)

            self.metadata_loaded.emit(self.metadata)
            return True

        except Exception as e:
            self.logger.error(f"Error cargando archivo raw: {e}")
            import traceback
            traceback.print_exc()
            return False
        

    def _load_metadata_file(self, meta_file):
        """
        Carga metadata desde archivo .meta con formato legible.
        CORRECCIÓN: Extrae correctamente frecuencia, sample_rate y modo.
        """
        try:
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'utf-16']
            content = None

            for enc in encodings:
                try:
                    with open(meta_file, 'r', encoding=enc) as f:
                        content = f.read()
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue

            if content is None:
                with open(meta_file, 'rb') as f:
                    content = f.read().decode('utf-8', errors='replace')
                self.logger.warning("⚠️ Metadata leída con reemplazo de caracteres")

            # Parsear línea por línea
            for line in content.splitlines():
                line = line.strip()
                if not line or ':' not in line:
                    continue

                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                # ===== FRECUENCIA =====
                if 'Frequency' in key:
                    try:
                        # Extraer número y unidad
                        match = re.search(r'([\d\.]+)\s*(?:MHz|GHz)?', value, re.IGNORECASE)
                        if match:
                            freq_val = float(match.group(1))
                            # Detectar unidad
                            if 'GHz' in value:
                                self.freq_mhz = freq_val * 1000
                            else:
                                self.freq_mhz = freq_val
                            self.metadata['frequency'] = self.freq_mhz
                    except (ValueError, IndexError):
                        self.logger.warning(f"No se pudo parsear frecuencia: {value}")

                # ===== SAMPLE RATE =====
                elif 'Sample Rate' in key or 'SampleRate' in key:
                    try:
                        match = re.search(r'([\d\.]+)\s*(?:MHz|MSPS|kHz)?', value, re.IGNORECASE)
                        if match:
                            sr_val = float(match.group(1))
                            # Detectar unidad
                            if 'kHz' in value or 'KHz' in value:
                                self.sample_rate = sr_val * 1e3
                            elif 'MHz' in value or 'MSPS' in value:
                                self.sample_rate = sr_val * 1e6
                            else:
                                self.sample_rate = sr_val * 1e6  # Asumir MHz por defecto
                            self.metadata['sample_rate'] = self.sample_rate
                    except (ValueError, IndexError):
                        self.logger.warning(f"No se pudo parsear sample rate: {value}")

                # ===== MODO =====
                elif 'Mode' in key:
                    self.metadata['mode'] = value

                # ===== DURACIÓN =====
                elif 'Duration' in key:
                    try:
                        match = re.search(r'([\d\.]+)', value)
                        if match:
                            self.metadata['duration'] = float(match.group(1))
                    except (ValueError, IndexError):
                        pass

                # ===== TIMESTAMP =====
                elif 'Timestamp' in key:
                    self.metadata['timestamp'] = value

            # Validar valores
            if self.freq_mhz < 1 or self.freq_mhz > 6000:
                self.logger.warning(f"⚠️ Frecuencia anormal: {self.freq_mhz} MHz, usando 100 MHz")
                self.freq_mhz = 100.0
                self.metadata['frequency'] = 100.0

            if self.sample_rate <= 0 or self.sample_rate > 100e6:
                self.logger.warning(f"⚠️ Sample rate anormal: {self.sample_rate/1e6:.1f} MHz, usando 2 MHz")
                self.sample_rate = 2e6
                self.metadata['sample_rate'] = 2e6

        except Exception as e:
            self.logger.error(f"Error cargando metadata: {e}")
            import traceback
            traceback.print_exc()

    def _load_metadata(self, meta_file):
        """Carga metadata del archivo .meta con manejo robusto de encoding."""
        try:
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'utf-16']
            content = None

            for enc in encodings:
                try:
                    with open(meta_file, 'r', encoding=enc) as f:
                        content = f.read()
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue

            if content is None:
                with open(meta_file, 'rb') as f:
                    content = f.read().decode('utf-8', errors='replace')
                self.logger.warning("⚠️ Metadata leída con reemplazo de caracteres")

            for line in content.splitlines():
                line = line.strip()
                if not line or ':' not in line:
                    continue

                parts = line.split(':', 1)
                if len(parts) != 2:
                    continue

                key   = parts[0].strip()
                value = parts[1].strip()

                if 'Frequency' in key:
                    try:
                        match = re.search(r'([\d\.]+)', value)
                        if match:
                            self.metadata['frequency'] = float(match.group(1))
                            self.freq_mhz = float(match.group(1))
                    except (ValueError, IndexError):
                        self.logger.warning(f"No se pudo parsear frecuencia: {value}")

                elif 'Sample Rate' in key:
                    try:
                        match = re.search(r'([\d\.]+)', value)
                        if match:
                            sr_value = float(match.group(1))
                            self.metadata['sample_rate'] = sr_value * 1e6
                            self.sample_rate = sr_value * 1e6
                    except (ValueError, IndexError):
                        self.logger.warning(f"No se pudo parsear sample rate: {value}")

                elif 'Duration' in key:
                    try:
                        match = re.search(r'([\d\.]+)', value)
                        if match:
                            self.metadata['duration'] = float(match.group(1))
                    except (ValueError, IndexError):
                        self.logger.warning(f"No se pudo parsear duración: {value}")

                elif 'Timestamp' in key:
                    self.metadata['timestamp'] = value

            if self.freq_mhz < 1:
                self.logger.warning(
                    f"⚠️ Frecuencia anormalmente baja: {self.freq_mhz} MHz — usando 100 MHz")
                self.freq_mhz = 100.0
                self.metadata['frequency'] = 100.0

        except Exception as e:
            self.logger.error(f"Error cargando metadata: {e}")
            import traceback
            traceback.print_exc()

    def _infer_metadata_from_filename(self, filename):
        """
        Infiere frecuencia, sample rate y modo desde el nombre del archivo.
        Formato esperado: IQ_2400MHz_56MSPS_TIME10s_20260330_083456
        """
        try:
            basename = os.path.basename(filename)
            
            # ===== FRECUENCIA =====
            match = re.search(r'(\d+)\s*MHz', basename, re.IGNORECASE)
            if match:
                self.freq_mhz = float(match.group(1))
                self.metadata['frequency'] = self.freq_mhz
                self.logger.info(f"📡 Frecuencia inferida: {self.freq_mhz} MHz")
            
            # ===== SAMPLE RATE =====
            match = re.search(r'(\d+(?:\.\d+)?)\s*MSPS', basename, re.IGNORECASE)
            if match:
                self.sample_rate = float(match.group(1)) * 1e6
                self.metadata['sample_rate'] = self.sample_rate
                self.logger.info(f"📡 Sample Rate inferido: {self.sample_rate/1e6:.1f} MSPS")
            else:
                match = re.search(r'(\d+(?:\.\d+)?)M', basename, re.IGNORECASE)
                if match:
                    sr_val = float(match.group(1))
                    if sr_val < 100:  # MSPS razonable
                        self.sample_rate = sr_val * 1e6
                        self.metadata['sample_rate'] = self.sample_rate
                        self.logger.info(f"📡 Sample Rate inferido: {self.sample_rate/1e6:.1f} MSPS")
            
            # ===== MODO =====
            if 'TIME' in basename:
                self.metadata['mode'] = 'TIME'
            elif 'SIZE' in basename:
                self.metadata['mode'] = 'SIZE'
            elif 'CONT' in basename:
                self.metadata['mode'] = 'CONT'
            
        except Exception as e:
            self.logger.debug(f"No se pudo inferir metadata: {e}")

    def _calculate_duration(self):
        """Calcula duración desde el tamaño real del archivo."""
        if self.sample_rate > 0 and self.total_bytes > 0:
            calculated = self.total_bytes / (self.sample_rate * 4)
            if self.metadata['duration'] == 0:
                self.metadata['duration'] = calculated
            elif abs(self.metadata['duration'] - calculated) > 0.1:
                self.logger.debug(
                    f"Duración: metadata={self.metadata['duration']:.2f}s, "
                    f"calculada={calculated:.2f}s"
                )

    # ------------------------------------------------------------------
    # MÉTODOS DE CONTROL
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
            self.logger.info(f"   Speed:           {speed}x")
            self.logger.info(f"   Duración archivo: {self.metadata['duration']:.2f} s")
            self.logger.info(f"   Tiempo deseado:   {desired_time:.2f} s")
            self.logger.info(f"   Buffers/seg:      {self.target_blocks_per_second:.1f}")
        else:
            self.target_blocks_per_second = 30 * speed
            self.expected_interval = 1.0 / self.target_blocks_per_second

    def start_playback(self):
        if not self.file:
            self.error_occurred.emit("No hay archivo cargado")
            return
        self.is_playing = True
        self.is_paused  = False
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

    '''def seek(self, position_bytes):
        if self.file:
            # Alinear al límite de buffer para evitar lecturas parciales
            aligned = (position_bytes // self.bytes_per_buffer) * self.bytes_per_buffer
            self.position = max(0, min(aligned, self.total_bytes - self.bytes_per_buffer))
            self.file.seek(self.position)
            self.progress_updated.emit(self.position, self.total_bytes)'''


    def seek(self, position_bytes):
        """
        Salta a una posición específica en el archivo.
        Mejorado para manejar pausa y estados.
        
        Args:
            position_bytes: Posición en bytes (debe estar alineada a buffer)
        """
        if self.file is None:
            self.logger.warning("⚠️ No se puede hacer seek: archivo no cargado")
            return
        
        # Alinear al límite de buffer
        aligned = (position_bytes // self.bytes_per_buffer) * self.bytes_per_buffer
        
        # Asegurar que no se salga del rango
        if aligned < 0:
            aligned = 0
        if aligned > self.total_bytes - self.bytes_per_buffer:
            aligned = max(0, self.total_bytes - self.bytes_per_buffer)
        
        # Guardar estado de reproducción para restaurar después
        was_playing = self.is_playing and not self.is_paused
        
        # Si está reproduciendo, pausar temporalmente para hacer seek
        if was_playing:
            self.is_playing = False
            self.is_paused = False
            # Pequeña pausa para que el hilo se detenga
            self.msleep(10)
        
        # Realizar seek
        try:
            self.file.seek(aligned)
            self.position = aligned
            
            # Limpiar buffer de lectura
            self.read_buffer = bytearray(self.bytes_per_buffer)
            
            self.logger.info(f"🎯 Seek completado a {aligned} bytes ({aligned/self.total_bytes*100:.1f}%)")
            
            # Emitir progreso actualizado
            self.progress_updated.emit(float(self.position), float(self.total_bytes))
            
        except Exception as e:
            self.logger.error(f"Error en seek: {e}")
            self.error_occurred.emit(f"Error en seek: {e}")
            return
        
        # Restaurar estado de reproducción si estaba reproduciendo
        if was_playing:
            self.is_playing = True
            self.is_paused = False
            self.logger.info("▶ Reproducción reanudada después de seek")

    def close(self):
        """Cierra el archivo y libera recursos."""
        self._stop_flag = True
        self.wait(2000)

        if self.file:
            self.file.close()
            self.file = None

        if hasattr(self, '_temp_file_path') and self._temp_file_path:
            try:
                os.unlink(self._temp_file_path)
            except Exception:
                pass

        self.logger.info("📂 Archivo cerrado")

    # ------------------------------------------------------------------
    # REPRODUCCIÓN
    # ------------------------------------------------------------------

    def run(self):
        self.logger.info("🚀 Hilo de reproducción ejecutándose")

        last_block_time = time.time()
        blocks_sent = 0
        start_time  = time.time()

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

                # ===== PROGRESO MEJORADO: emitir más frecuentemente =====
                now = time.time()

                self._last_position = self.position
                
                # Emitir si pasó el intervalo o si es el último buffer
                if (now - self._last_progress_emit_time) >= self._progress_emit_interval:
                    self.progress_updated.emit(float(self.position), float(self.total_bytes))
                    self._last_progress_emit_time = now
                    self._last_emit_position = self.position

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
            self.logger.info(
                f"⏹ Hilo detenido ({blocks_sent} buffers, {elapsed_total:.2f}s)")

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

            # Rellenar con ceros si el último bloque está incompleto
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

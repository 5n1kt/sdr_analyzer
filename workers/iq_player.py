# workers/iq_player.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import numpy as np
import os
import time
from PyQt5.QtCore import QThread, pyqtSignal
import logging


# =======================================================================
# REPRODUCTOR IQ SIMPLE
# =======================================================================
class IQPlayer(QThread):
    """
    Hilo de reproducción que lee archivos IQ raw y los inyecta en el pipeline.
    """
    
    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    playback_started = pyqtSignal()
    playback_paused = pyqtSignal()
    playback_stopped = pyqtSignal()
    playback_finished = pyqtSignal()
    progress_updated = pyqtSignal(float, float)  # (position_bytes, total_bytes)
    buffer_ready = pyqtSignal(np.ndarray)
    error_occurred = pyqtSignal(str)
    metadata_loaded = pyqtSignal(dict)
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        # Estado del archivo
        self.filename = None
        self.file = None
        self.total_bytes = 0
        self.position = 0
        
        # Parámetros del archivo
        self.sample_rate = 2e6
        self.freq_mhz = 100.0
        
        # Configuración de reproducción
        self.samples_per_buffer = 8192
        self.bytes_per_buffer = self.samples_per_buffer * 4  # int16 I+Q = 4 bytes/muestra
        self.speed = 1.0
        self.loop = False
        
        # Control de estado
        self.is_playing = False
        self.is_paused = False
        self._stop_flag = False
        
        # Buffer reutilizable
        self.read_buffer = bytearray(self.bytes_per_buffer)
        
        # Metadata
        self.metadata = {
            'frequency': 100.0,
            'sample_rate': 2e6,
            'duration': 0,
            'timestamp': '',
            'file_size_mb': 0
        }
        
        # Control de throttling
        self.target_blocks_per_second = 30
        self.expected_interval = 1.0 / self.target_blocks_per_second
        
        self.logger.info("✅ IQPlayer creado")
    
    def __del__(self):
        """Destructor - asegura cerrar archivo"""
        self.close()
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - CARGA DE ARCHIVOS
    # -----------------------------------------------------------------------
    def load_file(self, filename):
        """Carga un archivo IQ (raw .bin)"""
        try:
            self.filename = filename
            
            # Abrir archivo
            self.file = open(filename, 'rb')
            self.file.seek(0, 2)
            self.total_bytes = self.file.tell()
            self.position = 0
            self.file.seek(0)
            
            self.metadata['file_size_mb'] = self.total_bytes / 1e6
            
            # Buscar archivo de metadata
            meta_file = filename.replace('.bin', '.meta')
            if os.path.exists(meta_file):
                self.logger.info(f"📄 Metadata encontrada: {os.path.basename(meta_file)}")
                self._load_metadata(meta_file)
            
            # Calcular duración
            self._calculate_duration()
            
            self.logger.info(f"📂 Archivo cargado: {filename}")
            self.logger.info(f"   Tamaño: {self.total_bytes/1e6:.1f} MB")
            self.logger.info(f"   Frecuencia: {self.metadata['frequency']} MHz")
            self.logger.info(f"   Sample Rate: {self.metadata['sample_rate']/1e6:.1f} MHz")
            self.logger.info(f"   Duración: {self.metadata['duration']:.2f} s")
            
            # Emitir metadata
            self.metadata_loaded.emit(self.metadata)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error cargando archivo: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - CONFIGURACIÓN
    # -----------------------------------------------------------------------
    def configure(self, samples_per_buffer=8192, speed=1.0, loop=False):
        """Configura parámetros de reproducción"""
        self.samples_per_buffer = samples_per_buffer
        self.bytes_per_buffer = samples_per_buffer * 4
        self.speed = speed
        self.loop = loop
        
        # Calcular throttling basado en duración real
        if self.metadata['duration'] > 0 and self.total_bytes > 0:
            total_buffers = self.total_bytes / self.bytes_per_buffer
            desired_time = self.metadata['duration'] / speed
            self.target_blocks_per_second = (total_buffers / desired_time) * 0.95
            self.expected_interval = 1.0 / self.target_blocks_per_second
            
            self.logger.info(f"⚙️ Configuración reproducción:")
            self.logger.info(f"   Speed: {speed}x")
            self.logger.info(f"   Duración archivo: {self.metadata['duration']:.1f} s")
            self.logger.info(f"   Tiempo deseado: {desired_time:.1f} s")
            self.logger.info(f"   Buffers/seg: {self.target_blocks_per_second:.1f}")
        else:
            self.target_blocks_per_second = 30 * speed
            self.expected_interval = 1.0 / self.target_blocks_per_second
            self.logger.info(f"⚙️ Configuración estimada: {self.target_blocks_per_second:.0f} buffers/s")
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - CONTROL DE REPRODUCCIÓN
    # -----------------------------------------------------------------------
    def start_playback(self):
        """Inicia la reproducción"""
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
        """Pausa la reproducción"""
        self.is_paused = True
        self.playback_paused.emit()
        self.logger.info("⏸ Reproducción pausada")
    
    def resume_playback(self):
        """Reanuda la reproducción"""
        self.is_paused = False
        self.playback_started.emit()
        self.logger.info("▶ Reproducción reanudada")
    
    def stop_playback(self):
        """Detiene la reproducción"""
        self._stop_flag = True
        self.is_playing = False
    
    def seek(self, position_bytes):
        """Mueve la posición de reproducción"""
        if self.file:
            self.position = max(
                0, 
                min(position_bytes, self.total_bytes - self.bytes_per_buffer)
            )
            self.file.seek(self.position)
            self.progress_updated.emit(self.position, self.total_bytes)
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - LIMPIEZA
    # -----------------------------------------------------------------------
    def close(self):
        """Cierra el archivo y libera memoria"""
        self._stop_flag = True
        self.wait(2000)
        
        if self.file:
            self.file.close()
            self.file = None
        
        self.logger.info("📂 Archivo cerrado")
    
    # -----------------------------------------------------------------------
    # QTHREAD - MÉTODO PRINCIPAL
    # -----------------------------------------------------------------------
    def run(self):
        """Loop principal de reproducción"""
        self.logger.info("🚀 Hilo de reproducción ejecutándose")
        
        last_block_time = time.time()
        blocks_sent = 0
        start_time = time.time()
        
        try:
            while not self._stop_flag and self.is_playing:
                # Verificar pausa
                if self.is_paused:
                    self.msleep(10)
                    continue
                
                # Throttling
                current_time = time.time()
                elapsed = current_time - last_block_time
                
                if elapsed < self.expected_interval:
                    sleep_time = self.expected_interval - elapsed
                    if sleep_time > 0:
                        self.msleep(int(sleep_time * 1000))
                
                last_block_time = time.time()
                
                # Leer siguiente buffer
                iq_data = self._read_next_buffer()
                
                if iq_data is None:
                    self.logger.info(f"🏁 Fin del archivo después de {blocks_sent} buffers")
                    break
                
                blocks_sent += 1
                self.buffer_ready.emit(iq_data)
                
                # Actualizar progreso
                progress_ratio = self.position / self.total_bytes if self.total_bytes > 0 else 0
                self.progress_updated.emit(progress_ratio, 1.0)
        
        except Exception as e:
            self.logger.error(f"Error en reproducción: {e}")
            self.error_occurred.emit(str(e))
        
        finally:
            self.is_playing = False
            self.playback_finished.emit()
            self.playback_stopped.emit()
            
            elapsed_total = time.time() - start_time
            self.logger.info(f"⏹ Hilo detenido ({blocks_sent} buffers, {elapsed_total:.1f}s)")
    
    # -----------------------------------------------------------------------
    # MÉTODOS PRIVADOS
    # -----------------------------------------------------------------------
    def _load_metadata(self, meta_file):
        """Carga metadata del archivo .meta"""
        try:
            with open(meta_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    if 'Frequency:' in line:
                        parts = line.split(':')[1].strip().split()
                        self.metadata['frequency'] = float(parts[0])
                        self.freq_mhz = float(parts[0])
                    
                    elif 'Sample Rate:' in line:
                        parts = line.split(':')[1].strip().split()
                        sr_value = float(parts[0])
                        self.metadata['sample_rate'] = sr_value * 1e6
                        self.sample_rate = sr_value * 1e6
                    
                    elif 'Duration:' in line:
                        parts = line.split(':')[1].strip().split()
                        self.metadata['duration'] = float(parts[0])
                    
                    elif 'Timestamp:' in line:
                        self.metadata['timestamp'] = line.split(':')[1].strip()
        except Exception as e:
            self.logger.error(f"Error cargando metadata: {e}")
    
    def _calculate_duration(self):
        """Calcula duración del archivo"""
        if self.sample_rate > 0 and self.total_bytes > 0:
            calculated_duration = self.total_bytes / (self.sample_rate * 4)
            
            if self.metadata['duration'] == 0:
                self.metadata['duration'] = calculated_duration
            else:
                if abs(self.metadata['duration'] - calculated_duration) > 0.1:
                    self.logger.warning(
                        f"⚠️ Duración inconsistente: metadata={self.metadata['duration']:.2f}s, "
                        f"calculada={calculated_duration:.2f}s"
                    )
    
    def _read_next_buffer(self):
        """Lee el siguiente buffer del archivo raw"""
        try:
            bytes_to_read = min(
                self.bytes_per_buffer,
                self.total_bytes - self.position
            )
            
            if bytes_to_read <= 0:
                if self.loop:
                    self.position = 0
                    self.file.seek(0)
                    bytes_to_read = self.bytes_per_buffer
                else:
                    return None
            
            # Leer del archivo
            self.read_buffer = self.file.read(bytes_to_read)
            self.position += len(self.read_buffer)
            
            # Padding si es necesario
            if len(self.read_buffer) < self.bytes_per_buffer:
                self.read_buffer += b'\x00' * (
                    self.bytes_per_buffer - len(self.read_buffer)
                )
            
            return self._bytes_to_complex(self.read_buffer)
            
        except Exception as e:
            self.logger.error(f"Error leyendo buffer: {e}")
            return None
    
    def _bytes_to_complex(self, data):
        """Convierte bytes int16 interleaved a complex64"""
        samples = np.frombuffer(data, dtype=np.int16)
        
        if len(samples) % 2 != 0:
            samples = samples[:-1]
        
        i_samples = samples[0::2].astype(np.float32) / 2048.0
        q_samples = samples[1::2].astype(np.float32) / 2048.0
        
        return (i_samples + 1j * q_samples).astype(np.complex64)
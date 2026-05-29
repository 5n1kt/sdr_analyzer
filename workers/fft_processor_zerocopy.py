# -*- coding: utf-8 -*-

"""
FFT Processor with Zero-Copy Architecture - Versión C++ Optimizada
===================================================================
Versión que usa el módulo dsp_core en C++ para máximo rendimiento.
"""

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
import logging
import time
import threading

from workers.shared_buffer import IQRingBuffer

# Importar módulo C++ optimizado
try:
    import dsp_core
    DSP_CORE_AVAILABLE = True
    print("✅ dsp_core C++ module loaded")
except ImportError as e:
    DSP_CORE_AVAILABLE = False
    print(f"⚠️ dsp_core not available: {e}. Using fallback.")


class FFTProcessorZeroCopy(QThread):
    """
    FFT processor that reads from ring buffer and emits power spectra.
    Versión optimizada con backend C++.
    """
    
    fft_data_ready = pyqtSignal(np.ndarray)
    stats_updated = pyqtSignal(dict)
    
    FLOOR_DB = -120.0
    EPSILON = 1e-12
    MAX_FPS = 30
    MIN_UPDATE_MS = 33
    
    def __init__(self, ring_buffer: IQRingBuffer, sample_rate: float = 2e6):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        self.ring_buffer = ring_buffer
        
        self.is_running = False
        self._stop_flag = False
        
        # Configuración
        self._settings_lock = threading.Lock()
        self.fft_size = 1024
        self.window_type = 'Hann'
        self.averaging = 1
        self.overlap = 50
        self.sample_rate = sample_rate
        
        # Frame rate control
        self._last_update_time = 0.0
        self._frame_pending = False
        
        # Estadísticas
        self.stats = {
            'fft_frames': 0,
            'buffers_processed': 0,
            'skipped_buffers': 0,
            'dropped_frames': 0,
            'avg_process_time_ms': 0.0,
            'actual_averaging': 1,
            'target_averaging': 1,
            'using_cpp': DSP_CORE_AVAILABLE,
        }
        
        # Inicializar procesador C++ si está disponible
        if DSP_CORE_AVAILABLE:
            self._init_cpp_processor()
        else:
            self.cpp_processor = None
            self.logger.info("🐍 Using Python backend (C++ disabled for debugging)")
        
        self.logger.info(f"✅ FFTProcessorZeroCopy initialized (C++ backend: {DSP_CORE_AVAILABLE})")
    
    def _init_cpp_processor(self):
        """Inicializa el procesador C++ con la configuración actual."""
        if not DSP_CORE_AVAILABLE:
            self.cpp_processor = None
            return
        
        try:
            self.cpp_processor = dsp_core.FFTProcessor()
            
            config = dsp_core.FFTConfig()
            config.fft_size = self.fft_size
            config.window_type = self.window_type.lower()
            config.averaging = self.averaging
            config.overlap = self.overlap
            config.sample_rate = self.sample_rate
            config.floor_db = self.FLOOR_DB
            
            # === DEPURACIÓN ===
            self.logger.info(f"🔧 Configuring C++ processor with fft_size={self.fft_size}")
            # =================
            
            self.cpp_processor.configure(config)
            self.logger.info("✅ C++ FFT processor configured")
            
            # === VERIFICAR QUE EL PLAN SE CREÓ ===
            stats = self.cpp_processor.get_stats()
            self.logger.info(f"📊 C++ processor stats after config: fft_size={stats.fft_size}")
            # =====================================
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize C++ processor: {e}")
            self.cpp_processor = None
            self.stats['using_cpp'] = False
    
    def _update_cpp_config(self):
        """Actualiza la configuración del procesador C++."""
        if not DSP_CORE_AVAILABLE or self.cpp_processor is None:
            self.logger.debug("C++ backend not available, skipping config update")
            return
        
        try:
            config = dsp_core.FFTConfig()
            config.fft_size = self.fft_size
            config.window_type = self.window_type.lower()
            config.averaging = self.averaging
            config.overlap = self.overlap
            config.sample_rate = self.sample_rate
            config.floor_db = self.FLOOR_DB
            
            self.cpp_processor.configure(config)
        except Exception as e:
            self.logger.error(f"Failed to update C++ config: {e}")
    
    # ------------------------------------------------------------------------
    # THREAD MAIN LOOP
    # ------------------------------------------------------------------------
    
    def run(self):
        self.is_running = True
        self._stop_flag = False
        self.logger.info("🚀 FFTProcessorZeroCopy started (C++ accelerated)")
        
        while not self._stop_flag:
            try:
                result = self.ring_buffer.get_read_buffer(timeout_ms=500)
                if result is None:
                    continue
                
                iq_buffer, buffer_idx = result
                
                # Copiar buffer (necesario para liberar el slot rápidamente)
                iq_copy = iq_buffer.copy()
                self.ring_buffer.release_read(buffer_idx)
                
                self.stats['buffers_processed'] += 1
                
                # Procesar FFT (usando C++ si está disponible)
                t0 = time.perf_counter()
                
                if DSP_CORE_AVAILABLE:
                    # Usar procesador C++ optimizado
                    fft_result = self._process_with_cpp(iq_copy)
                else:
                    # Fallback a implementación Python
                    fft_result = self._process_buffer_python(iq_copy)


                # === COMPARACIÓN ===
                '''if self.stats['fft_frames'] == 1:
                    py_result = self._process_buffer_python(iq_copy)
                    self.logger.info(f"📊 Python result - min: {py_result.min():.1f}, max: {py_result.max():.1f}")
                    self.logger.info(f"📊 C++ result   - min: {fft_result.min():.1f}, max: {fft_result.max():.1f}")'''
                # ===================

                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                self._update_avg_time(elapsed_ms)
                
                self._send_result_if_needed(fft_result)
                
                if self.stats['buffers_processed'] % 100 == 0:
                    self.stats_updated.emit(self.stats.copy())
                
            except Exception as exc:
                if not self._stop_flag:
                    self.logger.error(f"❌ Error in FFTProcessor: {exc}")
        
        self.is_running = False
        self.logger.info("⏹️ FFTProcessorZeroCopy stopped")
    
    def _process_with_cpp(self, iq_data: np.ndarray) -> np.ndarray:
        """Procesa FFT usando el módulo C++ optimizado."""
        if not DSP_CORE_AVAILABLE or self.cpp_processor is None:
            # Fallback a Python
            return self._process_buffer_python(iq_data)
        
        try:
            with self._settings_lock:
                # Actualizar configuración si cambió
                if (self.cpp_processor.get_stats().fft_size != self.fft_size or
                    self.stats['target_averaging'] != self.averaging):
                    self._update_cpp_config()
            
            # Convertir a tipo esperado por C++
            iq_contiguous = np.ascontiguousarray(iq_data, dtype=np.complex64)

            # En _process_with_cpp, antes de llamar a C++:
            #self.logger.info(f"🔍 Input data - shape: {iq_contiguous.shape}, dtype: {iq_contiguous.dtype}")
            #self.logger.info(f"   min: {iq_contiguous.real.min():.4f}, max: {iq_contiguous.real.max():.4f}")
            
            if self.averaging > 1:
                result = self.cpp_processor.process_welch(iq_contiguous)
            else:
                result = self.cpp_processor.process(iq_contiguous)

            # === DEPURACIÓN ===
            if self.stats['fft_frames'] % 30 == 0:
                self.logger.info(f"📊 C++ FFT result - shape: {result.shape}, min: {result.min():.1f}, max: {result.max():.1f}")
            # =================
            
            # Actualizar estadísticas
            cpp_stats = self.cpp_processor.get_stats()
            self.stats['actual_averaging'] = cpp_stats.averaging_actual
            self.stats['target_averaging'] = cpp_stats.averaging_target
            
            return result
        except Exception as e:
            self.logger.error(f"❌ C++ processing error: {e}, falling back to Python")
            return self._process_buffer_python(iq_data)
    
    def _process_buffer_python(self, iq_data: np.ndarray) -> np.ndarray:
        """
        Procesa FFT usando implementación Python (fallback).
        """
        with self._settings_lock:
            fft_size = self.fft_size
            window_type = self.window_type
            averaging = self.averaging
            overlap = self.overlap
        
        if len(iq_data) < fft_size:
            return None
        
        # Calcular ventana
        window = self._get_window_python(fft_size, window_type)
        step = max(1, int(fft_size * (1 - overlap / 100)))
        max_segments = (len(iq_data) - fft_size) // step + 1
        num_segments = max(1, min(averaging, max_segments))
        
        self.stats['actual_averaging'] = num_segments
        
        accum = np.zeros(fft_size, dtype=np.float64)
        
        for i in range(num_segments):
            start = i * step
            segment = iq_data[start:start + fft_size] * window
            fft_seg = np.fft.fftshift(np.fft.fft(segment))
            accum += np.abs(fft_seg) ** 2
        
        power = accum / num_segments
        
        # Normalizar
        window_power = np.sum(window.astype(np.float64) ** 2)
        power_normalized = power / (window_power * fft_size)
        
        # Convertir a dB
        power_normalized = np.maximum(power_normalized, self.EPSILON)
        power_dbfs = 10.0 * np.log10(power_normalized)
        np.maximum(power_dbfs, self.FLOOR_DB, out=power_dbfs)
        
        return power_dbfs.astype(np.float32)
    
    def _get_window_python(self, fft_size: int, window_type: str) -> np.ndarray:
        """Calcula ventana en Python (fallback)."""
        if window_type == 'Rectangular':
            return np.ones(fft_size, dtype=np.float32)
        elif window_type == 'Hann':
            return np.hanning(fft_size).astype(np.float32)
        elif window_type == 'Hamming':
            return np.hamming(fft_size).astype(np.float32)
        elif window_type == 'Blackman':
            return np.blackman(fft_size).astype(np.float32)
        elif window_type == 'Kaiser':
            return np.kaiser(fft_size, 14).astype(np.float32)
        else:
            return np.hanning(fft_size).astype(np.float32)
    
    def _update_avg_time(self, process_time_ms: float) -> None:
        self.stats['avg_process_time_ms'] = (
            0.95 * self.stats['avg_process_time_ms'] +
            0.05 * process_time_ms
        )
    
    def _send_result_if_needed(self, fft_result: np.ndarray) -> None:
        if fft_result is None:
            return
        
        # === DEPURACIÓN ===
        if self.stats['fft_frames'] % 30 == 0:
            self.logger.info(f"📤 Emitting FFT frame {self.stats['fft_frames']}")
        # =================
            
        now_ms = time.perf_counter() * 1000.0
        
        if (now_ms - self._last_update_time) >= self.MIN_UPDATE_MS:
            if self._frame_pending:
                self.stats['dropped_frames'] += 1
                self.stats['skipped_buffers'] += 1
                return
            
            self._frame_pending = True
            self._last_update_time = now_ms
            self.stats['fft_frames'] += 1
            self.fft_data_ready.emit(fft_result)
        else:
            self.stats['skipped_buffers'] += 1
    
    # ------------------------------------------------------------------------
    # PUBLIC METHODS
    # ------------------------------------------------------------------------
    
    def update_settings(self, settings: dict) -> bool:
        restart_needed = False
        
        with self._settings_lock:
            if 'fft_size' in settings and settings['fft_size'] != self.fft_size:
                self.fft_size = settings['fft_size']
                restart_needed = True
                self.logger.info(f"📏 FFT size changed to {self.fft_size}")
            
            if 'window' in settings:
                self.window_type = settings['window']
            
            if 'averaging' in settings:
                self.averaging = max(1, int(settings['averaging']))
                self.stats['target_averaging'] = self.averaging
            
            if 'overlap' in settings:
                self.overlap = max(0, min(99, int(settings['overlap'])))
            
            if 'sample_rate' in settings:
                self.sample_rate = float(settings['sample_rate'])
        
        # Actualizar configuración C++ si está disponible
        if DSP_CORE_AVAILABLE and self.cpp_processor is not None and not restart_needed:
            self._update_cpp_config()
        
        return restart_needed
    
    def stop(self, immediate: bool = False) -> None:
        self._stop_flag = True
        if not immediate:
            if not self.wait(2000):
                self.logger.warning("⚠️ FFTProcessor not responding in 2s — forcing termination")
                self.terminate()
                self.wait(200)
        self.logger.info("⏹️ FFTProcessorZeroCopy stopped")
    
    def on_frame_consumed(self) -> None:
        self._frame_pending = False
        if DSP_CORE_AVAILABLE and self.cpp_processor:
            self.cpp_processor.on_frame_consumed()
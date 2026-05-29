# -*- coding: utf-8 -*-

"""
FFT Processor with Zero-Copy Architecture
==========================================
Reads IQ samples from ring buffer and computes power spectrum.

Features:
    - Configurable FFT size, window type, averaging, and overlap
    - Pre-computed windows for performance
    - Dynamic window caching for different FFT sizes
    - Frame rate throttling (max 30 fps)
    - Statistics reporting (actual averaging, dropped frames)

CORRECTIONS APPLIED:
    1. Pre-computed windows for all common FFT sizes
    2. Proper handling of averaging when not enough data available
    3. on_frame_consumed() to signal frame consumption to controller
"""

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
import logging
import time
import threading

from workers.shared_buffer import IQRingBuffer


# ============================================================================
# FFT PROCESSOR
# ============================================================================

class FFTProcessorZeroCopy(QThread):
    """
    FFT processor that reads from ring buffer and emits power spectra.
    
    Signals:
        fft_data_ready: Emitted with power spectrum array (dB)
        stats_updated: Emitted periodically with processing statistics
    """
    
    # ------------------------------------------------------------------------
    # SIGNALS
    # ------------------------------------------------------------------------
    fft_data_ready = pyqtSignal(np.ndarray)
    stats_updated = pyqtSignal(dict)
    
    # ------------------------------------------------------------------------
    # CONSTANTS
    # ------------------------------------------------------------------------
    FLOOR_DB = -120.0
    EPSILON = 1e-12
    MAX_FPS = 30
    MIN_UPDATE_MS = 33      # Minimum milliseconds between frames
    _PRECALC_SIZES = [256, 512, 1024, 2048, 4096, 8192, 16384]
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, ring_buffer: IQRingBuffer, sample_rate: float = 2e6):
        """
        Initialize FFT processor.
        
        Args:
            ring_buffer: IQRingBuffer containing IQ samples
            sample_rate: Current sample rate in Hz
        """
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        self.ring_buffer = ring_buffer
        
        # Thread control
        self.is_running = False
        self._stop_flag = False
        
        # Configuration (protected by lock)
        self._settings_lock = threading.Lock()
        self.fft_size = 1024
        self.window_type = 'Hann'
        self.averaging = 1
        self.overlap = 50
        self.sample_rate = sample_rate
        
        # Pre-computed windows cache
        self.windows = self._precompute_windows()
        
        # FFT accumulator for averaging
        self.fft_accum = np.zeros(self.fft_size, dtype=np.float64)
        
        # Frame rate control
        self._last_update_time = 0.0
        self._frame_pending = False
        
        # Statistics
        self.stats = {
            'fft_frames': 0,
            'buffers_processed': 0,
            'skipped_buffers': 0,
            'dropped_frames': 0,
            'avg_process_time_ms': 0.0,
            'actual_averaging': 1,
            'target_averaging': 1,
        }
        
        self.logger.info("✅ FFTProcessorZeroCopy created")
    
    # ------------------------------------------------------------------------
    # THREAD MAIN LOOP
    # ------------------------------------------------------------------------
    
    def run(self):
        """
        Main processing loop.
        
        Reads buffers from ring buffer, computes FFT, and emits results
        at a controlled frame rate (max 30 fps).
        """
        self.is_running = True
        self._stop_flag = False
        self.logger.info("🚀 FFTProcessorZeroCopy started")
        
        while not self._stop_flag:
            try:
                # Get buffer from ring buffer (timeout 500ms)
                result = self.ring_buffer.get_read_buffer(timeout_ms=500)   #100
                if result is None:
                    continue
                
                iq_buffer, buffer_idx = result
                
                # Copy buffer (we need to release the slot quickly)
                iq_copy = iq_buffer.copy()
                self.ring_buffer.release_read(buffer_idx)
                
                self.stats['buffers_processed'] += 1
                
                # Process FFT
                t0 = time.perf_counter()
                fft_result = self._process_buffer(iq_copy)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                
                self._update_avg_time(elapsed_ms)
                
                # Send result if frame rate allows
                self._send_result_if_needed(fft_result)
                
                # Emit stats periodically
                if self.stats['buffers_processed'] % 100 == 0:
                    self.stats_updated.emit(self.stats.copy())
                
            except Exception as exc:
                if not self._stop_flag:
                    self.logger.error(f"❌ Error in FFTProcessor: {exc}")
        
        self.is_running = False
        self.logger.info("⏹️ FFTProcessorZeroCopy stopped")
    
    # ------------------------------------------------------------------------
    # PUBLIC METHODS
    # ------------------------------------------------------------------------
    
    def update_settings(self, settings: dict) -> bool:
        """
        Update FFT configuration.
        
        Returns:
            True if restart is needed (FFT size changed)
        """
        restart_needed = False
        
        with self._settings_lock:
            # Check for FFT size change (requires restart)
            if 'fft_size' in settings and settings['fft_size'] != self.fft_size:
                self.fft_size = settings['fft_size']
                self.fft_accum = np.zeros(self.fft_size, dtype=np.float64)
                restart_needed = True
                self.logger.info(f"📏 FFT size changed to {self.fft_size}")
            
            # Update other settings (apply immediately)
            if 'window' in settings:
                self.window_type = settings['window']
            
            if 'averaging' in settings:
                self.averaging = max(1, int(settings['averaging']))
                self.stats['target_averaging'] = self.averaging
            
            if 'overlap' in settings:
                self.overlap = max(0, min(99, int(settings['overlap'])))
            
            if 'sample_rate' in settings:
                self.sample_rate = float(settings['sample_rate'])
        
        return restart_needed
    
    def stop(self, immediate: bool = False) -> None:
        """
        Stop processing.
        
        Args:
            immediate: If True, force termination after timeout
        """
        self._stop_flag = True
        if not immediate:
            if not self.wait(2000):
                self.logger.warning("⚠️ FFTProcessor not responding in 2s — forcing termination")
                self.terminate()
                self.wait(200)
        self.logger.info("⏹️ FFTProcessorZeroCopy stopped")
    
    def on_frame_consumed(self) -> None:
        """
        Called when the emitted frame has been consumed.
        
        This allows the processor to send the next frame.
        """
        self._frame_pending = False
    
    # ------------------------------------------------------------------------
    # PRIVATE METHODS - WINDOW MANAGEMENT
    # ------------------------------------------------------------------------
    
    def _precompute_windows(self) -> dict:
        """Pre-compute windows for all common FFT sizes."""
        windows = {}
        for size in self._PRECALC_SIZES:
            windows[size] = self._build_window_set(size)
        return windows
    
    def _build_window_set(self, size: int) -> dict:
        """Build all window types for a given size."""
        return {
            'Rectangular': np.ones(size, dtype=np.float32),
            'Hann': np.hanning(size).astype(np.float32),
            'Hamming': np.hamming(size).astype(np.float32),
            'Blackman': np.blackman(size).astype(np.float32),
            'Kaiser': np.kaiser(size, 14).astype(np.float32),
        }
    
    def _get_window(self, fft_size: int, window_type: str) -> np.ndarray:
        """Get window array for given size and type."""
        # Cache window for this size if not already cached
        if fft_size not in self.windows:
            self.logger.info(f"⚙️ Computing windows for fft_size={fft_size}")
            self.windows[fft_size] = self._build_window_set(fft_size)
        
        normalized_type = window_type.capitalize()
        window_set = self.windows[fft_size]
        
        if normalized_type not in window_set:
            self.logger.warning(f"⚠️ Unknown window '{window_type}', using Hann")
            normalized_type = 'Hann'
        
        return window_set[normalized_type]
    
    # ------------------------------------------------------------------------
    # PRIVATE METHODS - FFT PROCESSING
    # ------------------------------------------------------------------------
    
    def _process_buffer(self, iq_data: np.ndarray) -> np.ndarray:
        """
        Process IQ buffer and return power spectrum in dB.
        
        Uses Welch's method with configurable overlap and averaging.
        """
        with self._settings_lock:
            fft_size = self.fft_size
            window_type = self.window_type
            averaging = self.averaging
            overlap = self.overlap
            
            # Re-allocate accumulator if size changed
            if self.fft_accum.size != fft_size:
                self.fft_accum = np.zeros(fft_size, dtype=np.float64)
        
        # Not enough samples for FFT
        if len(iq_data) < fft_size:
            return None
        
        # Get window
        window = self._get_window(fft_size, window_type)
        
        # Calculate step based on overlap
        step = max(1, int(fft_size * (1 - overlap / 100)))
        max_segments = (len(iq_data) - fft_size) // step + 1
        
        # Actual averaging is limited by available data
        num_segments = max(1, min(averaging, max_segments))
        
        # Update statistics with actual averaging
        with self._settings_lock:
            self.stats['actual_averaging'] = num_segments
        
        # Accumulate FFTs
        self.fft_accum.fill(0.0)
        
        for i in range(num_segments):
            start = i * step
            segment = iq_data[start:start + fft_size] * window
            
            # Compute FFT with shift
            fft_seg = np.fft.fftshift(np.fft.fft(segment))
            self.fft_accum += np.abs(fft_seg) ** 2
        
        # Average
        power = self.fft_accum / num_segments
        
        # Normalize for window power and FFT length
        window_power = np.sum(window.astype(np.float64) ** 2)
        power_normalized = power / (window_power * fft_size)
        
        # Convert to dB
        power_normalized = np.maximum(power_normalized, self.EPSILON)
        power_dbfs = 10.0 * np.log10(power_normalized)
        np.maximum(power_dbfs, self.FLOOR_DB, out=power_dbfs)
        
        return power_dbfs.astype(np.float32)
    
    def _update_avg_time(self, process_time_ms: float) -> None:
        """Update moving average of processing time."""
        self.stats['avg_process_time_ms'] = (
            0.95 * self.stats['avg_process_time_ms'] +
            0.05 * process_time_ms
        )
    
    def _send_result_if_needed(self, fft_result: np.ndarray) -> None:
        """
        Send FFT result if frame rate allows.
        
        Uses MIN_UPDATE_MS to throttle to max 30 fps.
        """
        if fft_result is None:
            return
        
        now_ms = time.perf_counter() * 1000.0
        
        # Check if enough time has passed
        if (now_ms - self._last_update_time) >= self.MIN_UPDATE_MS:
            # Check if previous frame is still pending
            if self._frame_pending:
                self.stats['dropped_frames'] += 1
                self.stats['skipped_buffers'] += 1
                return
            
            # Send new frame
            self._frame_pending = True
            self._last_update_time = now_ms
            self.stats['fft_frames'] += 1
            self.fft_data_ready.emit(fft_result)
        else:
            self.stats['skipped_buffers'] += 1
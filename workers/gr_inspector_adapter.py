# -*- coding: utf-8 -*-

"""
GR-Inspector Adapter - CFAR Signal Detection
=============================================
Adapts the CFAR detector for integration with the SDR pipeline.

Features:
    - CFAR (Constant False Alarm Rate) detection
    - Multiple peak detection per block
    - Bandwidth measurement at -3dB with interpolation
    - Noise floor estimation with median
    - Prominence-based peak filtering

CORRECTIONS APPLIED:
    1. Spectrum normalized to dBFS (relative to ADC saturation)
    2. BW measured at -3dB with linear interpolation
    3. Noise floor estimated with median (more robust than percentile 10)
    4. find_peaks uses prominence to avoid side lobe detections
    5. Multiple peaks detected per block (not just strongest)
    6. Accumulation buffer uses deque (avoid O(n²) concatenation)
"""

import numpy as np
import time
import logging
from collections import deque
from scipy.signal import find_peaks, windows as sp_windows

from PyQt5.QtCore import QThread, pyqtSignal

try:
    from utils.signal_classifier import SignalClassifier
    CLASSIFIER_AVAILABLE = True
except ImportError:
    CLASSIFIER_AVAILABLE = False


# ============================================================================
# CFAR DETECTOR
# ============================================================================

class CFARDetector:
    """
    CFAR (Constant False Alarm Rate) detector for IQ signals.
    
    Detects signals by analyzing power spectrum with adaptive threshold.
    """
    
    # Window cache for performance
    _WINDOW_CACHE = {}
    
    def __init__(
        self,
        sample_rate: float = 2e6,
        threshold_db: float = 6.0,
        min_bw_hz: float = 10e3,
        max_bw_hz: float = 10e6,
        fft_size: int = 4096,
        guard_cells: int = 4,
        training_cells: int = 16,
    ):
        """
        Initialize CFAR detector.
        
        Args:
            sample_rate: Sample rate in Hz
            threshold_db: SNR threshold in dB
            min_bw_hz: Minimum bandwidth to detect
            max_bw_hz: Maximum bandwidth to detect
            fft_size: FFT size for spectrum analysis
            guard_cells: Guard cells around peak
            training_cells: Training cells for noise estimation
        """
        self.sample_rate = sample_rate
        self.threshold_db = threshold_db
        self.min_bw_hz = min_bw_hz
        self.max_bw_hz = max_bw_hz
        self.fft_size = fft_size
        self.guard_cells = guard_cells
        self.training_cells = training_cells
        self.logger = logging.getLogger(__name__)
        
        # Noise floor history (moving average)
        self._noise_history = deque(maxlen=20)
        self.noise_floor_db = -100.0
        
        # Frequency resolution
        self._freq_per_bin = sample_rate / fft_size
    
    def update_sample_rate(self, sample_rate: float) -> None:
        """Update sample rate and recalculate frequency resolution."""
        self.sample_rate = sample_rate
        self._freq_per_bin = sample_rate / self.fft_size
        self._noise_history.clear()
    
    def process_block(self, iq_data: np.ndarray, center_freq_mhz: float) -> list:
        """
        Process IQ block and return detections.
        
        Args:
            iq_data: Complex IQ samples (normalized)
            center_freq_mhz: Center frequency in MHz
        
        Returns:
            List of detection dictionaries
        """
        if len(iq_data) < self.fft_size:
            return []
        
        try:
            # Compute spectrum in dBFS
            spectrum_dbfs = self._compute_spectrum(iq_data)
            
            # Estimate noise floor
            self._update_noise_floor(spectrum_dbfs)
            
            # Detect peaks above threshold
            peaks = self._find_signal_peaks(spectrum_dbfs)
            
            # Build detections
            detections = []
            for peak_bin in peaks:
                det = self._build_detection(spectrum_dbfs, peak_bin, center_freq_mhz)
                if det is not None:
                    detections.append(det)
            
            return detections
            
        except Exception as exc:
            self.logger.error(f"CFARDetector error: {exc}")
            return []
    
    def _get_window(self, size: int) -> np.ndarray:
        """Get Blackman-Harris window (cached)."""
        if size not in self._WINDOW_CACHE:
            self._WINDOW_CACHE[size] = sp_windows.blackmanharris(size).astype(np.float32)
        return self._WINDOW_CACHE[size]
    
    def _compute_spectrum(self, iq_data: np.ndarray) -> np.ndarray:
        """
        Compute power spectrum in dBFS.
        
        Uses Welch method with 50% overlap and Blackman-Harris window.
        """
        win = self._get_window(self.fft_size)
        step = self.fft_size // 2
        n_seg = min(8, (len(iq_data) - self.fft_size) // step + 1)
        
        accum = np.zeros(self.fft_size, dtype=np.float64)
        win_power = np.sum(win ** 2)
        
        for i in range(n_seg):
            seg = iq_data[i * step : i * step + self.fft_size]
            fft_v = np.fft.fftshift(np.fft.fft(seg * win))
            accum += np.abs(fft_v) ** 2
        
        power_norm = accum / (n_seg * win_power * self.fft_size)
        power_norm = np.maximum(power_norm, 1e-12)
        return 10.0 * np.log10(power_norm).astype(np.float32)
    
    def _update_noise_floor(self, spectrum_dbfs: np.ndarray) -> None:
        """Estimate noise floor using median of lowest 30% bins."""
        sorted_bins = np.sort(spectrum_dbfs)
        cutoff = max(1, len(sorted_bins) * 30 // 100)
        noise_est = float(np.median(sorted_bins[:cutoff]))
        self._noise_history.append(noise_est)
        self.noise_floor_db = float(np.mean(self._noise_history))
    
    def _find_signal_peaks(self, spectrum_dbfs: np.ndarray) -> np.ndarray:
        """Find peaks above threshold with prominence filtering."""
        min_height = self.noise_floor_db + self.threshold_db
        min_dist_bins = max(2, int(self.min_bw_hz / self._freq_per_bin))
        min_prom = self.threshold_db / 2.0
        
        peaks, _ = find_peaks(
            spectrum_dbfs,
            height=min_height,
            distance=min_dist_bins,
            prominence=min_prom,
        )
        return peaks
    
    def _measure_bandwidth_3db(self, spectrum_dbfs: np.ndarray, peak_bin: int) -> tuple:
        """Measure -3dB bandwidth with linear interpolation."""
        peak_power = float(spectrum_dbfs[peak_bin])
        half_power = peak_power - 3.0
        n = len(spectrum_dbfs)
        
        # Left edge
        left_bin = peak_bin
        while left_bin > 0 and spectrum_dbfs[left_bin] > half_power:
            left_bin -= 1
        
        if left_bin < peak_bin:
            y0, y1 = float(spectrum_dbfs[left_bin]), float(spectrum_dbfs[left_bin + 1])
            left_frac = (half_power - y0) / (y1 - y0) if abs(y1 - y0) > 1e-6 else 0.0
            left_exact = left_bin + left_frac
        else:
            left_exact = float(left_bin)
        
        # Right edge
        right_bin = peak_bin
        while right_bin < n - 1 and spectrum_dbfs[right_bin] > half_power:
            right_bin += 1
        
        if right_bin > peak_bin:
            y0, y1 = float(spectrum_dbfs[right_bin - 1]), float(spectrum_dbfs[right_bin])
            right_frac = (half_power - y0) / (y1 - y0) if abs(y1 - y0) > 1e-6 else 1.0
            right_exact = (right_bin - 1) + right_frac
        else:
            right_exact = float(right_bin)
        
        bw_hz = (right_exact - left_exact) * self._freq_per_bin
        bw_hz = float(np.clip(bw_hz, self.min_bw_hz, self.max_bw_hz))
        return bw_hz, left_bin, right_bin
    
    def _peak_bin_to_freq_offset_hz(self, peak_bin: int) -> float:
        """Convert FFT bin to frequency offset in Hz."""
        return (peak_bin - self.fft_size // 2) * self._freq_per_bin
    
    def _build_detection(self, spectrum_dbfs: np.ndarray, peak_bin: int,
                         center_freq_mhz: float) -> dict:
        """Build detection dictionary from a peak."""
        peak_power_dbfs = float(spectrum_dbfs[peak_bin])
        snr_db = peak_power_dbfs - self.noise_floor_db
        
        # Measure bandwidth
        bw_hz, _, _ = self._measure_bandwidth_3db(spectrum_dbfs, peak_bin)
        
        if bw_hz < self.min_bw_hz or bw_hz > self.max_bw_hz:
            return None
        
        # Calculate center frequency
        offset_hz = self._peak_bin_to_freq_offset_hz(peak_bin)
        peak_freq_mhz = center_freq_mhz + offset_hz / 1e6
        
        # Classify signal type
        if CLASSIFIER_AVAILABLE:
            sig_type, type_info = SignalClassifier.classify(bw_hz)
            type_name = type_info['name']
            type_color = type_info['color']
        else:
            bw_khz = bw_hz / 1000
            if bw_khz < 200:
                sig_type, type_name, type_color = "NARROW", "📻 Narrow", "#00ff00"
            elif bw_khz < 2000:
                sig_type, type_name, type_color = "MEDIUM", "📺 Medium", "#ffff00"
            else:
                sig_type, type_name, type_color = "WIDE", "📡 Wide", "#ff8800"
        
        return {
            'center_freq_mhz': round(peak_freq_mhz, 4),
            'bandwidth_hz': bw_hz,
            'bandwidth_khz': bw_hz / 1000,
            'power_db': peak_power_dbfs,
            'snr_db': snr_db,
            'signal_type': sig_type,
            'type_name': type_name,
            'type_color': type_color,
            'confidence': float(np.clip(0.5 + snr_db / 30.0, 0.1, 0.99)),
            'timestamp': time.time(),
            'simulated': False,
            'detector': 'cfar',
            'noise_floor_db': self.noise_floor_db,
        }


# ============================================================================
# GR-INSPECTOR ADAPTER (QThread)
# ============================================================================

class GRInspectorAdapter(QThread):
    """
    Adapter that consumes IQ data and produces detections.
    
    Signals:
        detection_result: Emitted for each detection
        inspector_ready: Emitted when detector is ready
        stats_updated: Emitted with (samples, detections)
        scan_progress: Emitted with (current_index, total_frequencies)
        values_updated: Emitted with (threshold, noise_floor)
    """
    
    detection_result = pyqtSignal(dict)
    inspector_ready = pyqtSignal(bool)
    stats_updated = pyqtSignal(int, int)
    scan_progress = pyqtSignal(int, int)
    values_updated = pyqtSignal(float, float)
    
    TARGET_BUFFER_SIZE = 131072
    MIN_SCAN_INTERVAL = 500
    
    def __init__(self, ring_buffer, sample_rate: float = 2e6):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.ring_buffer = ring_buffer
        self.sample_rate = sample_rate
        
        # State
        self.is_running = False
        self._stop_flag = False
        self._pause_flag = False
        self.current_freq_mhz = 0.0
        self.freq_index = 0
        self.total_freqs = 0
        
        # Accumulation buffer (deque for efficiency)
        self._block_queue = deque()
        self._queued_samples = 0
        
        # Configuration
        self.threshold_db = 6.0
        self.min_bw_hz = 10e3
        self.max_bw_hz = 10e6
        
        # Statistics
        self.samples_processed = 0
        self.detections_found = 0
        self._last_log_time = time.time()
        self._last_stats_time = time.time()
        
        # CFAR Detector
        self.cfar = CFARDetector(
            sample_rate=sample_rate,
            threshold_db=self.threshold_db,
            min_bw_hz=self.min_bw_hz,
            max_bw_hz=self.max_bw_hz,
        )
        
        self.logger.info(f"✅ GRInspectorAdapter created — CFAR ready")
    
    # ------------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------------
    
    def set_current_frequency(self, freq_mhz: float) -> None:
        """Set current center frequency."""
        self.current_freq_mhz = freq_mhz
    
    def set_scan_progress(self, index: int, total: int) -> None:
        """Set scan progress for progress bar."""
        self.freq_index = index
        self.total_freqs = total
    
    def configure(self, config: dict) -> None:
        """Configure detector parameters."""
        self.threshold_db = config.get('threshold_db', self.threshold_db)
        self.min_bw_hz = config.get('min_bw_hz', self.min_bw_hz)
        self.max_bw_hz = config.get('max_bw_hz', self.max_bw_hz)
        
        self.cfar.threshold_db = self.threshold_db
        self.cfar.min_bw_hz = self.min_bw_hz
        self.cfar.max_bw_hz = self.max_bw_hz
    
    def update_sample_rate(self, sample_rate: float) -> None:
        """Update sample rate."""
        self.sample_rate = sample_rate
        self.cfar.update_sample_rate(sample_rate)
    
    def start_processing(self) -> None:
        """Start processing thread."""
        if self.is_running:
            return
        self.is_running = True
        self._stop_flag = False
        self._pause_flag = False
        self._block_queue.clear()
        self._queued_samples = 0
        self.start()
        self.logger.info("▶ Adapter started")
    
    def stop_processing(self) -> None:
        """Stop processing."""
        self._stop_flag = True
        self.is_running = False
    
    def pause_processing(self) -> None:
        """Pause processing."""
        self._pause_flag = True
    
    def resume_processing(self) -> None:
        """Resume processing."""
        self._pause_flag = False
    
    # ------------------------------------------------------------------------
    # QTHREAD MAIN LOOP
    # ------------------------------------------------------------------------
    
    def run(self) -> None:
        """Main processing loop."""
        self.logger.info("🚀 GRInspectorAdapter thread started")
        self.inspector_ready.emit(True)
        
        last_values_time = time.time()
        
        while not self._stop_flag:
            try:
                if self._pause_flag:
                    self.msleep(100)
                    continue
                
                t0 = time.time()
                
                # Get buffer from ring
                result = self.ring_buffer.get_read_buffer(timeout_ms=50)
                if result is None:
                    self.msleep(10)
                    continue
                
                iq_data, buf_idx = result
                self.samples_processed += len(iq_data)
                
                # Accumulate
                self._block_queue.append(iq_data.copy())
                self._queued_samples += len(iq_data)
                self.ring_buffer.release_read(buf_idx)
                
                # Process when enough samples
                while self._queued_samples >= self.TARGET_BUFFER_SIZE:
                    block = self._collect_block()
                    detections = self._process_block(block)
                    
                    for det in detections:
                        self.detections_found += 1
                        self.detection_result.emit(det)
                
                # Emit stats every second
                now = time.time()
                if now - self._last_stats_time >= 1.0:
                    self.stats_updated.emit(self.samples_processed, self.detections_found)
                    if self.total_freqs > 0:
                        self.scan_progress.emit(self.freq_index, self.total_freqs)
                    self._last_stats_time = now
                
                # Emit values every 200ms
                if now - last_values_time >= 0.2:
                    self.values_updated.emit(self.cfar.threshold_db, self.cfar.noise_floor_db)
                    last_values_time = now
                
                # Log every 10 seconds
                if now - self._last_log_time >= 10.0:
                    self.logger.info(
                        f"📊 CFAR: {self.samples_processed/1e6:.1f}M samples — "
                        f"{self.detections_found} detections"
                    )
                    self._last_log_time = now
                
                # Soft throttle
                elapsed = time.time() - t0
                if elapsed < 0.02:
                    self.msleep(int((0.02 - elapsed) * 1000))
                
            except Exception as exc:
                self.logger.error(f"❌ Error in adapter: {exc}")
                self.msleep(100)
        
        self.logger.info(f"⏹ Adapter stopped — {self.samples_processed:,} samples, {self.detections_found} detections")
    
    def _collect_block(self) -> np.ndarray:
        """Collect exactly TARGET_BUFFER_SIZE samples from queue."""
        needed = self.TARGET_BUFFER_SIZE
        parts = []
        gathered = 0
        
        while gathered < needed and self._block_queue:
            chunk = self._block_queue[0]
            remaining = needed - gathered
            
            if len(chunk) <= remaining:
                parts.append(chunk)
                gathered += len(chunk)
                self._block_queue.popleft()
                self._queued_samples -= len(chunk)
            else:
                parts.append(chunk[:remaining])
                self._block_queue[0] = chunk[remaining:]
                self._queued_samples -= remaining
                gathered = remaining
        
        return np.concatenate(parts) if parts else np.array([], dtype=np.complex64)
    
    def _process_block(self, iq_data: np.ndarray) -> list:
        """Process block with CFAR detector."""
        if len(iq_data) == 0:
            return []
        return self.cfar.process_block(iq_data, self.current_freq_mhz)
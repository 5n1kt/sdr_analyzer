# -*- coding: utf-8 -*-

"""
BladeRF 2.0 micro Driver
=========================
Concrete implementation of SDRDevice for BladeRF 2.0 micro hardware.

All libbladeRF-specific code is encapsulated here.
No controller, worker, or widget should import this module directly.
Use SDRDeviceFactory to obtain instances.

Corrections from original BladeRFManager
----------------------------------------
1. ADC saturation threshold: 2047/2048 ≈ 0.9995 (was 0.9)
2. Automatic gain reduction after 3 consecutive saturations in Manual mode
3. close() calls self.sdr.close() before releasing reference
4. Ranges exposed as SDRRange, not proprietary libbladeRF types
5. gain_modes exposed as list[str], not enum objects
6. set_frequency() unifies fast frequency change as part of contract
7. read_samples() centralizes sync_rx — workers never access sdr.sync_rx directly
"""

import numpy as np
import logging
import time
import threading
from typing import List, Optional

from sdr.sdr_device import SDRDevice, SDRRange

try:
    from bladerf import _bladerf
    BLADERF_AVAILABLE = True
except ImportError:
    BLADERF_AVAILABLE = False


# ============================================================================
# GAIN MODE MAPPING
# ============================================================================

# Bidirectional mapping between readable strings and libbladeRF constants.
# This ensures no external code needs to import _bladerf.
_GAIN_MODE_TO_INT = {
    'Manual':   1,
    'Default':  0,
    'Fast AGC': 2,
    'Slow AGC': 3,
    'Hybrid':   4,
}
_INT_TO_GAIN_MODE = {v: k for k, v in _GAIN_MODE_TO_INT.items()}


# ============================================================================
# BLADERF DEVICE IMPLEMENTATION
# ============================================================================

class BladeRFDevice(SDRDevice):
    """
    Driver for BladeRF 2.0 micro.
    
    Implements the complete SDRDevice contract.
    All libbladeRF API (_bladerf.*) is private to this class.
    """
    
    # ------------------------------------------------------------------------
    # CLASS CONSTANTS
    # ------------------------------------------------------------------------
    _BYTES_PER_SAMPLE     = 4          # SC16_Q11: 2 bytes I + 2 bytes Q
    _DEFAULT_SPB          = 8192       # Default samples per block
    _SC16_Q11_SCALE       = 2048.0     # 2^11 - divisor for SC16_Q11 format
    _ADC_SATURATION       = 2047.0 / 2048.0   # ≈ 0.9995 (12-bit ADC)
    _SATURATION_DB_STEP   = 6.0        # dB to reduce per saturation event
    _SATURATION_COUNT_MAX = 3          # Consecutive saturations before action
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Private libbladeRF objects
        self._sdr = None
        self._rx_ch = None
        self._lock = threading.Lock()
        
        # Public state
        self._is_initialized = False
        self._streaming = False
        
        # Current RF parameters
        self._frequency = 100e6
        self._sample_rate = 2e6
        self._bandwidth = 1e6
        self._gain = 50.0
        self._gain_mode = 'Manual'
        
        # Buffer configuration
        self._buffer_size = 8192
        self._num_buffers = 16
        self._num_transfers = 8
        
        # Ranges (populated in initialize())
        self._freq_range = SDRRange(70e6, 6e9, 1.0)
        self._sample_rate_range = SDRRange(160e3, 61.44e6, 1.0)
        self._bandwidth_range = SDRRange(200e3, 56e6, 1.0)
        self._gain_range = SDRRange(0.0, 73.0, 1.0)
        self._gain_modes_list = list(_GAIN_MODE_TO_INT.keys())
        
        # Saturation control
        self._saturation_count = 0
    
    def __del__(self):
        self.close()
    
    # ------------------------------------------------------------------------
    # STATE PROPERTIES
    # ------------------------------------------------------------------------
    
    @property
    def frequency(self) -> float:
        return self._frequency
    
    @property
    def sample_rate(self) -> float:
        return self._sample_rate
    
    @property
    def bandwidth(self) -> float:
        return self._bandwidth
    
    @property
    def gain(self) -> float:
        return self._gain
    
    @property
    def gain_mode(self) -> str:
        return self._gain_mode
    
    @property
    def is_initialized(self) -> bool:
        return self._is_initialized
    
    @property
    def streaming(self) -> bool:
        return self._streaming
    
    # ------------------------------------------------------------------------
    # CAPABILITY PROPERTIES
    # ------------------------------------------------------------------------
    
    @property
    def freq_range(self) -> SDRRange:
        return self._freq_range
    
    @property
    def sample_rate_range(self) -> SDRRange:
        return self._sample_rate_range
    
    @property
    def bandwidth_range(self) -> SDRRange:
        return self._bandwidth_range
    
    @property
    def gain_range(self) -> SDRRange:
        return self._gain_range
    
    @property
    def gain_modes(self) -> List[str]:
        return self._gain_modes_list
    
    # ------------------------------------------------------------------------
    # METADATA
    # ------------------------------------------------------------------------
    
    @property
    def device_name(self) -> str:
        return 'BladeRF 2.0 micro'
    
    @property
    def samples_per_block(self) -> int:
        return self._DEFAULT_SPB
    
    @property
    def bytes_per_sample(self) -> int:
        return self._BYTES_PER_SAMPLE
    
    # ------------------------------------------------------------------------
    # LIFECYCLE METHODS
    # ------------------------------------------------------------------------
    
    def initialize(self) -> bool:
        """Opens and initializes the BladeRF device."""
        if not BLADERF_AVAILABLE:
            raise RuntimeError(
                "The 'bladerf' library is not installed. "
                "Run: pip install bladerf"
            )
        
        with self._lock:
            try:
                # Scan for devices
                devices = _bladerf.get_device_list()
                if not devices:
                    raise RuntimeError("No BladeRF device found")
                
                self.logger.info(f"Device found: {devices[0]}")
                
                # Create device and channel objects
                self._sdr = _bladerf.BladeRF()
                self._rx_ch = self._sdr.Channel(_bladerf.CHANNEL_RX(0))
                
                self.logger.info(f"libbladeRF version : {_bladerf.version()}")
                self.logger.info(f"Firmware           : {self._sdr.get_fw_version()}")
                self.logger.info(f"FPGA               : {self._sdr.get_fpga_version()}")
                
                # Convert proprietary ranges to SDRRange
                _fr = self._rx_ch.frequency_range
                _srr = self._rx_ch.sample_rate_range
                _bwr = self._rx_ch.bandwidth_range
                _gr = self._sdr.get_gain_range(_bladerf.CHANNEL_RX(0))
                
                self._freq_range = SDRRange(_fr.min, _fr.max, getattr(_fr, 'step', 1.0))
                self._sample_rate_range = SDRRange(_srr.min, _srr.max, getattr(_srr, 'step', 1.0))
                self._bandwidth_range = SDRRange(_bwr.min, _bwr.max, getattr(_bwr, 'step', 1.0))
                self._gain_range = SDRRange(_gr.min, _gr.max, getattr(_gr, 'step', 1.0))
                
                # Convert gain_modes to strings
                raw_modes = self._rx_ch.gain_modes
                self._gain_modes_list = [
                    _INT_TO_GAIN_MODE.get(
                        m.value if hasattr(m, 'value') else int(m),
                        str(m)
                    )
                    for m in raw_modes
                ]
                
                self.logger.info(
                    f"Frequency range   : "
                    f"{self._freq_range.min/1e6:.0f} – {self._freq_range.max/1e6:.0f} MHz"
                )
                self.logger.info(
                    f"Sample rate range : "
                    f"{self._sample_rate_range.min/1e6:.1f} – "
                    f"{self._sample_rate_range.max/1e6:.1f} MSPS"
                )
                self.logger.info(
                    f"Gain range        : "
                    f"{self._gain_range.min:.0f} – {self._gain_range.max:.0f} dB"
                )
                self.logger.info(f"Gain modes        : {self._gain_modes_list}")
                
                # Apply initial settings
                self._apply_rf_settings()
                self._setup_sync_stream()
                
                self._is_initialized = True
                self.logger.info("✅ BladeRF 2.0 initialized successfully")
                return True
                
            except Exception as exc:
                self.logger.error(f"❌ Error initializing BladeRF: {exc}")
                raise
    
    def configure(self, params: dict) -> bool:
        """
        Applies RF parameters.
        
        If only frequency changes, uses fast path without stream restart.
        """
        with self._lock:
            # Fast path: frequency only
            if set(params.keys()) == {'frequency'}:
                return self._set_frequency_nolock(params['frequency'])
            
            was_streaming = self._streaming
            
            try:
                # Stop stream if active
                if was_streaming:
                    self._stop_stream_nolock()
                
                # Update parameters
                if 'frequency' in params and params['frequency'] is not None:
                    self._frequency = self._freq_range.clamp(params['frequency'])
                
                if 'sample_rate' in params and params['sample_rate'] is not None:
                    self._sample_rate = self._sample_rate_range.clamp(params['sample_rate'])
                
                if 'bandwidth' in params and params['bandwidth'] is not None:
                    self._bandwidth = self._bandwidth_range.clamp(params['bandwidth'])
                
                if 'gain' in params and params['gain'] is not None:
                    self._gain = self._gain_range.clamp(params['gain'])
                
                if 'gain_mode' in params and params['gain_mode'] is not None:
                    mode = params['gain_mode']
                    if isinstance(mode, str) and mode in _GAIN_MODE_TO_INT:
                        self._gain_mode = mode
                    elif isinstance(mode, int) and mode in _INT_TO_GAIN_MODE:
                        self._gain_mode = _INT_TO_GAIN_MODE[mode]
                
                # Apply settings
                self._apply_rf_settings()
                self._setup_sync_stream()
                
                # Restart stream if it was active
                if was_streaming:
                    self._start_stream_nolock()
                
                return True
                
            except Exception as exc:
                self.logger.error(f"❌ Error configuring BladeRF: {exc}")
                return False
    
    def set_frequency(self, hz: float) -> bool:
        """Fast frequency change without restarting the stream."""
        with self._lock:
            return self._set_frequency_nolock(hz)
    
    def start_stream(self) -> None:
        """Starts sample streaming."""
        with self._lock:
            self._start_stream_nolock()
    
    def stop_stream(self) -> None:
        """Stops sample streaming."""
        with self._lock:
            self._stop_stream_nolock()
    
    def read_samples(self, buffer: bytearray, num_samples: int) -> bool:
        """
        Reads raw samples into buffer.
        
        Handles TimeoutError (restarts stream) and DeviceError (reconnects).
        """
        if not self._is_initialized:
            raise RuntimeError("BladeRF not initialized")
        
        with self._lock:
            if not self._streaming:
                self._start_stream_nolock()
        
        try:
            self._sdr.sync_rx(buffer, num_samples)
            return True
            
        except _bladerf.TimeoutError:
            self.logger.warning("⚠️ Timeout in sync_rx — restarting stream")
            with self._lock:
                self._stop_stream_nolock()
                self._setup_sync_stream()
                self._start_stream_nolock()
            self._sdr.sync_rx(buffer, num_samples)
            return True
            
        except _bladerf.DeviceError as exc:
            self.logger.error(f"❌ Device error: {exc} — reconnecting")
            self.close()
            time.sleep(1.0)
            self.initialize()
            raise RuntimeError(f"Device reinitialized after error: {exc}")
    
    def bytes_to_complex(self, buffer: bytearray, num_samples: int) -> np.ndarray:
        """
        Converts SC16_Q11 buffer to normalized complex64.
        
        Division by 2048 (2^11) yields range [-1.0, +1.0].
        Checks for saturation and automatically reduces gain if needed.
        """
        samples = np.frombuffer(buffer, dtype=np.int16, count=num_samples * 2)
        i_samples = samples[0::2].astype(np.float32)
        q_samples = samples[1::2].astype(np.float32)
        iq_data = (i_samples + 1j * q_samples) / self._SC16_Q11_SCALE
        
        self._check_saturation(iq_data)
        return iq_data
    
    def close(self) -> None:
        """Releases all hardware resources."""
        with self._lock:
            self._stop_stream_nolock()
            
            if self._rx_ch:
                try:
                    self._rx_ch.enable = False
                except Exception:
                    pass
                self._rx_ch = None
            
            if self._sdr:
                try:
                    self._sdr.close()  # Explicit close
                except Exception:
                    pass
                self._sdr = None
            
            self._is_initialized = False
            self.logger.info("BladeRF disconnected")
    
    # ------------------------------------------------------------------------
    # PRIVATE METHODS (call with lock acquired)
    # ------------------------------------------------------------------------
    
    def _set_frequency_nolock(self, hz: float) -> bool:
        """Fast frequency change (lock must be held)."""
        try:
            if not self._is_initialized or self._rx_ch is None:
                self.logger.error("❌ BladeRF not initialized")
                return False
            
            hz = self._freq_range.clamp(hz)
            self._rx_ch.frequency = int(hz)
            self._frequency = hz
            self.logger.info(f"📡 Frequency → {hz/1e6:.3f} MHz")
            return True
            
        except Exception as exc:
            self.logger.error(f"❌ Error changing frequency: {exc}")
            return False
    
    def _apply_rf_settings(self) -> None:
        """Applies all RF parameters to hardware (lock must be held)."""
        mode_int = _GAIN_MODE_TO_INT.get(self._gain_mode, 1)
        
        self._rx_ch.frequency = int(self._frequency)
        self._rx_ch.sample_rate = int(self._sample_rate)
        self._rx_ch.bandwidth = int(self._bandwidth)
        self._rx_ch.gain_mode = mode_int
        self._rx_ch.gain = int(self._gain)
    
    def _setup_sync_stream(self) -> None:
        """Configures SC16_Q11 synchronous stream (lock must be held)."""
        self._sdr.sync_config(
            layout=_bladerf.ChannelLayout.RX_X1,
            fmt=_bladerf.Format.SC16_Q11,
            num_buffers=self._num_buffers,
            buffer_size=self._buffer_size,
            num_transfers=self._num_transfers,
            stream_timeout=3500
        )
        self.logger.info("Synchronous SC16_Q11 stream configured")
    
    def _start_stream_nolock(self) -> None:
        """Starts streaming (lock must be held)."""
        self._rx_ch.enable = True
        self._streaming = True
        self.logger.info("Streaming started")
    
    def _stop_stream_nolock(self) -> None:
        """Stops streaming (lock must be held)."""
        if self._rx_ch:
            try:
                self._rx_ch.enable = False
            except Exception:
                pass
        self._streaming = False
    
    def _check_saturation(self, iq_data: np.ndarray) -> None:
        """
        Detects ADC saturation and reduces gain if persistent.
        
        Uses real ADC threshold (2047/2048) instead of 0.9 to avoid
        false positives with strong but valid signals.
        """
        max_val = float(np.max(np.abs(iq_data)))
        
        if max_val >= self._ADC_SATURATION:
            self._saturation_count += 1
            self.logger.warning(
                f"⚠️ ADC saturation [{self._saturation_count}x]: "
                f"{max_val:.4f} ≥ {self._ADC_SATURATION:.4f}"
            )
            
            if (self._gain_mode == 'Manual'
                    and self._saturation_count >= self._SATURATION_COUNT_MAX):
                new_gain = self._gain_range.clamp(self._gain - self._SATURATION_DB_STEP)
                with self._lock:
                    self._rx_ch.gain = int(new_gain)
                    self._gain = new_gain
                self._saturation_count = 0
                self.logger.warning(f"🔧 Gain automatically reduced to {new_gain:.0f} dB")
        else:
            self._saturation_count = 0
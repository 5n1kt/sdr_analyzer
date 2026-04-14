# -*- coding: utf-8 -*-

"""
SDR Device Abstraction Layer
=============================
This module defines the abstract interface that all SDR hardware drivers must implement.

The rest of the system (controllers, workers, widgets) depends ONLY on this interface,
never on concrete implementations. This enables:
    - Hardware independence (BladeRF, RTL-SDR, HackRF, etc.)
    - Easy testing with mock devices
    - Clean separation of concerns

Contract for Ranges
-------------------
All ranges are exposed as SDRRange objects with uniform keys:
    - min: Minimum value (Hz for frequencies/rates, dB for gain)
    - max: Maximum value
    - step: Resolution (1.0 if not applicable)

This eliminates dependency on proprietary types (libbladeRF.RangeObject, etc.)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
import numpy as np


# ============================================================================
# DATA CLASS FOR RANGES
# ============================================================================

@dataclass
class SDRRange:
    """
    Range for an SDR parameter.
    
    Replaces proprietary range objects from libbladeRF and other SDR libraries.
    
    Attributes:
        min: Minimum value (Hz for frequencies/rates, dB for gain)
        max: Maximum value
        step: Resolution of the parameter (1.0 if not applicable)
    """
    min: float
    max: float
    step: float = 1.0
    
    def clamp(self, value: float) -> float:
        """Returns value clamped to [min, max]."""
        return float(max(self.min, min(value, self.max)))
    
    def contains(self, value: float) -> bool:
        """Returns True if value is within the range."""
        return self.min <= value <= self.max
    
    def __repr__(self) -> str:
        return f"SDRRange(min={self.min}, max={self.max}, step={self.step})"


# ============================================================================
# ABSTRACT SDR DEVICE INTERFACE
# ============================================================================

class SDRDevice(ABC):
    """
    Abstract interface for SDR hardware devices.
    
    All hardware drivers must implement this interface.
    Use SDRDeviceFactory to obtain instances, never instantiate directly.
    
    Usage:
        device = SDRDeviceFactory.create('bladerf')
        device.initialize()
        device.configure({'frequency': 100e6, 'sample_rate': 2e6})
        device.start_stream()
        
        # In a worker thread
        buffer = bytearray(8192 * 4)
        device.read_samples(buffer, 8192)
        iq_data = device.bytes_to_complex(buffer, 8192)
    """
    
    # ------------------------------------------------------------------------
    # STATE PROPERTIES (readable without initialization)
    # ------------------------------------------------------------------------
    
    @property
    @abstractmethod
    def frequency(self) -> float:
        """Current center frequency in Hz."""
        pass
    
    @property
    @abstractmethod
    def sample_rate(self) -> float:
        """Current sample rate in Hz."""
        pass
    
    @property
    @abstractmethod
    def bandwidth(self) -> float:
        """Current RF filter bandwidth in Hz."""
        pass
    
    @property
    @abstractmethod
    def gain(self) -> float:
        """Current gain in dB."""
        pass
    
    @property
    @abstractmethod
    def gain_mode(self) -> str:
        """Current gain mode as string (e.g., 'Manual', 'AGC')."""
        pass
    
    @property
    @abstractmethod
    def is_initialized(self) -> bool:
        """True if the device has been successfully initialized."""
        pass
    
    @property
    @abstractmethod
    def streaming(self) -> bool:
        """True if sample streaming is active."""
        pass
    
    # ------------------------------------------------------------------------
    # CAPABILITY PROPERTIES (available after initialize())
    # ------------------------------------------------------------------------
    
    @property
    @abstractmethod
    def freq_range(self) -> SDRRange:
        """Supported frequency range."""
        pass
    
    @property
    @abstractmethod
    def sample_rate_range(self) -> SDRRange:
        """Supported sample rate range."""
        pass
    
    @property
    @abstractmethod
    def bandwidth_range(self) -> SDRRange:
        """Supported bandwidth range."""
        pass
    
    @property
    @abstractmethod
    def gain_range(self) -> SDRRange:
        """Supported gain range."""
        pass
    
    @property
    @abstractmethod
    def gain_modes(self) -> List[str]:
        """List of available gain modes as strings."""
        pass
    
    # ------------------------------------------------------------------------
    # DEVICE METADATA
    # ------------------------------------------------------------------------
    
    @property
    @abstractmethod
    def device_name(self) -> str:
        """Human-readable device name (e.g., 'BladeRF 2.0 micro')."""
        pass
    
    @property
    @abstractmethod
    def samples_per_block(self) -> int:
        """Number of IQ samples per transfer block."""
        pass
    
    @property
    @abstractmethod
    def bytes_per_sample(self) -> int:
        """Number of bytes per IQ sample in raw buffer."""
        pass
    
    # ------------------------------------------------------------------------
    # LIFECYCLE METHODS
    # ------------------------------------------------------------------------
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        Opens the device and prepares it for operation.
        
        Returns:
            True if initialization was successful.
            
        Raises:
            RuntimeError: If hardware is not found or initialization fails.
        """
        pass
    
    @abstractmethod
    def configure(self, params: dict) -> bool:
        """
        Applies one or more RF parameters.
        
        Recognized parameters:
            frequency   : Hz (float)
            sample_rate : Hz (float)
            bandwidth   : Hz (float)
            gain        : dB (float)
            gain_mode   : str ('Manual', 'AGC', etc.)
        
        Unknown keys are ignored (no exception raised).
        
        Returns:
            True if all parameters were applied successfully.
        """
        pass
    
    @abstractmethod
    def set_frequency(self, hz: float) -> bool:
        """
        Changes frequency without restarting the stream.
        
        This is the fast frequency change method that all implementations
        must support (even if internally it's not faster than configure()).
        
        Returns:
            True if frequency change was successful.
        """
        pass
    
    @abstractmethod
    def start_stream(self) -> None:
        """Starts continuous sample reception."""
        pass
    
    @abstractmethod
    def stop_stream(self) -> None:
        """Stops sample reception."""
        pass
    
    @abstractmethod
    def read_samples(self, buffer: bytearray, num_samples: int) -> bool:
        """
        Reads `num_samples` raw IQ samples into `buffer`.
        
        The buffer format is implementation-specific (int16 interleaved, etc.).
        Callers should use bytes_to_complex() for normalized complex values.
        
        Returns:
            True if read was successful.
        """
        pass
    
    @abstractmethod
    def bytes_to_complex(self, buffer: bytearray, num_samples: int) -> np.ndarray:
        """
        Converts raw buffer to normalized complex64 array.
        
        Normalization ensures |max| ≈ 1.0 for a signal that saturates the ADC.
        Each implementation applies the correct divisor based on its sample format.
        
        Returns:
            np.ndarray of dtype complex64, shape (num_samples,)
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Releases all hardware resources."""
        pass
    
    # ------------------------------------------------------------------------
    # CONCRETE METHOD - Available in all implementations
    # ------------------------------------------------------------------------
    
    def receive_samples(self, num_samples: int = 4096) -> np.ndarray:
        """
        Reads samples and returns them as normalized complex64.
        
        Default implementation combines read_samples() + bytes_to_complex().
        Subclasses may override for custom logic (timeout handling, etc.).
        """
        buf = bytearray(num_samples * self.bytes_per_sample)
        if not self.read_samples(buf, num_samples):
            raise RuntimeError("read_samples() failed")
        return self.bytes_to_complex(buf, num_samples)
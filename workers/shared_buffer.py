# -*- coding: utf-8 -*-

"""
Circular Ring Buffer for IQ Samples
====================================
Thread-safe ring buffer for IQ sample transfer between producer and consumer threads.

Two modes:
    - Thread mode: uses threading.Lock and threading.Event
    - Shared memory mode: uses multiprocessing.Lock and shared_memory (for multi-process)
    
For IQProcessorZeroCopy and FFTProcessorZeroCopy, thread mode is sufficient
since all consumers are QThreads in the same process.

Buffer States:
    FREE     : Available for writing
    FILLING  : Being written by producer
    READY    : Ready for reading
    READING  : Being read by consumer
"""

import numpy as np
import threading
import logging
from multiprocessing import shared_memory, Lock as MP_Lock
from typing import Optional, Tuple


# ============================================================================
# RING BUFFER CLASS
# ============================================================================

class IQRingBuffer:
    """
    Circular ring buffer for IQ samples with thread-safe operations.
    
    Attributes:
        num_buffers: Number of buffers in the ring
        samples_per_buffer: Number of complex samples per buffer
        bytes_per_buffer: Size of each buffer in bytes (samples * 8 for complex64)
        use_shared_memory: Whether to use multiprocessing shared memory
    """
    
    # ------------------------------------------------------------------------
    # BUFFER STATES
    # ------------------------------------------------------------------------
    BUFFER_FREE = 0      # Available for writing
    BUFFER_FILLING = 1   # Being written
    BUFFER_READY = 2     # Ready for reading
    BUFFER_READING = 3   # Being read
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, num_buffers: int = 4, samples_per_buffer: int = 16384,
                 use_shared_memory: bool = False, shm_name: str = None):
        """
        Initialize the ring buffer.
        
        Args:
            num_buffers: Number of buffers in the ring
            samples_per_buffer: Complex samples per buffer
            use_shared_memory: If True, use shared memory for multi-process
            shm_name: Existing shared memory name (for reconnection)
        """
        self.logger = logging.getLogger(__name__)
        
        self.num_buffers = num_buffers
        self.samples_per_buffer = samples_per_buffer
        self.bytes_per_buffer = samples_per_buffer * 8  # complex64 = 8 bytes
        self.use_shared_memory = use_shared_memory
        self.shm_name = shm_name
        self.shm = None
        
        # Initialize memory
        if use_shared_memory:
            self._init_shared_memory()
        else:
            self._init_thread_memory()
        
        # Pointers and states
        self.buffer_states = [self.BUFFER_FREE] * num_buffers
        self.write_index = 0
        self.read_index = 0
        self.available_count = 0
        
        # Events for efficient waiting (thread mode only)
        if not use_shared_memory:
            self.data_available = threading.Event()
            self.buffer_freed = threading.Event()
        
        # Statistics
        self.total_buffers_written = 0
        self.total_buffers_read = 0
        self.overflow_count = 0
        
        self.logger.info(
            f"✅ RingBuffer created: {num_buffers}x{samples_per_buffer} samples"
        )
        if use_shared_memory:
            self.logger.info(f"   Mode: SHARED MEMORY")
    
    def __del__(self):
        self.close()
    
    # ------------------------------------------------------------------------
    # INITIALIZATION
    # ------------------------------------------------------------------------
    
    def _init_shared_memory(self):
        """Initialize buffers in shared memory (multi-process)."""
        total_bytes = self.num_buffers * self.bytes_per_buffer
        
        if self.shm_name is None:
            # Create new shared memory
            self.shm = shared_memory.SharedMemory(create=True, size=total_bytes)
            self.shm_name = self.shm.name
            self.logger.info(
                f"🔄 Shared memory created: {self.shm_name} "
                f"({total_bytes/1e6:.1f} MB)"
            )
        else:
            # Connect to existing shared memory
            self.shm = shared_memory.SharedMemory(name=self.shm_name)
            self.logger.info(f"🔄 Connected to shared memory: {self.shm_name}")
        
        # Create buffers as views into shared memory
        self.buffers = []
        for i in range(self.num_buffers):
            offset = i * self.bytes_per_buffer
            buffer = np.ndarray(
                (self.samples_per_buffer,),
                dtype=np.complex64,
                buffer=self.shm.buf[offset:offset + self.bytes_per_buffer]
            )
            self.buffers.append(buffer)
        
        # Lock for multi-process synchronization
        self.lock = MP_Lock()
    
    def _init_thread_memory(self):
        """Initialize buffers in regular memory (thread-only)."""
        self.buffers = []
        for i in range(self.num_buffers):
            buffer = np.empty(self.samples_per_buffer, dtype=np.complex64)
            self.buffers.append(buffer)
        
        # Lock for thread synchronization
        self.lock = threading.Lock()
    
    # ------------------------------------------------------------------------
    # INFORMATION METHODS
    # ------------------------------------------------------------------------
    
    def get_shared_memory_info(self) -> dict:
        """
        Returns information for connecting from another process.
        
        Returns:
            dict with shm_name, num_buffers, samples_per_buffer, dtype
        """
        if not self.use_shared_memory:
            raise RuntimeError("Ring buffer not in shared memory mode")
        return {
            'shm_name': self.shm_name,
            'num_buffers': self.num_buffers,
            'samples_per_buffer': self.samples_per_buffer,
            'dtype': np.complex64
        }
    
    def get_stats(self) -> dict:
        """
        Returns buffer statistics.
        
        Returns:
            dict with total_written, total_read, overflow, available, states
        """
        with self.lock:
            return {
                'total_written': self.total_buffers_written,
                'total_read': self.total_buffers_read,
                'overflow': self.overflow_count,
                'available': self.available_count,
                'states': self.buffer_states.copy()
            }
    
    # ------------------------------------------------------------------------
    # WRITE OPERATIONS
    # ------------------------------------------------------------------------
    
    '''def get_write_buffer(self) -> Optional[np.ndarray]:
        """
        Gets a buffer for writing.
        
        Returns:
            Buffer array if available, None if all buffers are busy.
        """
        with self.lock:
            # Check current write index
            if self.buffer_states[self.write_index] == self.BUFFER_FREE:
                buffer = self.buffers[self.write_index]
                self.buffer_states[self.write_index] = self.BUFFER_FILLING
                return buffer
            
            # Search for any free buffer
            for _ in range(self.num_buffers):
                self.write_index = (self.write_index + 1) % self.num_buffers
                if self.buffer_states[self.write_index] == self.BUFFER_FREE:
                    buffer = self.buffers[self.write_index]
                    self.buffer_states[self.write_index] = self.BUFFER_FILLING
                    return buffer
            
            # No free buffers - overflow
            self.overflow_count += 1
            if self.overflow_count % 100 == 0:
                self.logger.warning(f"⚠️ Ring buffer overflow: {self.overflow_count}")
            return None'''
        
    # workers/shared_buffer.py - En get_write_buffer

    def get_write_buffer(self, timeout_ms: int = 50) -> Optional[np.ndarray]:
        """
        Gets a buffer for writing with timeout.
        
        Args:
            timeout_ms: Timeout in milliseconds
        
        Returns:
            Buffer array if available, None if timeout or no free buffer
        """
        with self.lock:
            # Verificar si hay buffer libre
            if self.buffer_states[self.write_index] == self.BUFFER_FREE:
                buffer = self.buffers[self.write_index]
                self.buffer_states[self.write_index] = self.BUFFER_FILLING
                return buffer
            
            # Esperar a que se libere un buffer (solo en modo thread)
            if not self.use_shared_memory and timeout_ms > 0:
                self.buffer_freed.wait(timeout_ms / 1000.0)
                self.buffer_freed.clear()
            
            # Reintentar después de esperar
            for _ in range(self.num_buffers):
                self.write_index = (self.write_index + 1) % self.num_buffers
                if self.buffer_states[self.write_index] == self.BUFFER_FREE:
                    buffer = self.buffers[self.write_index]
                    self.buffer_states[self.write_index] = self.BUFFER_FILLING
                    return buffer
            
            # No hay buffers libres - overflow
            self.overflow_count += 1
            if self.overflow_count % 100 == 0:
                self.logger.warning(f"⚠️ Ring buffer overflow: {self.overflow_count}")
            return None
    
    def commit_write(self) -> bool:
        """
        Marks the current write buffer as ready for reading.
        
        Returns:
            True if successful, False if buffer not in FILLING state.
        """
        with self.lock:
            if self.buffer_states[self.write_index] != self.BUFFER_FILLING:
                return False
            
            self.buffer_states[self.write_index] = self.BUFFER_READY
            self.available_count += 1
            self.total_buffers_written += 1
            
            self.write_index = (self.write_index + 1) % self.num_buffers
            
            # Signal data available (thread mode only)
            if not self.use_shared_memory:
                self.data_available.set()
            
            return True
    
    # ------------------------------------------------------------------------
    # READ OPERATIONS
    # ------------------------------------------------------------------------
    
    def get_read_buffer(self, timeout_ms: int = 1000) -> Optional[Tuple[np.ndarray, int]]:
        """
        Gets the next buffer for reading.
        
        Args:
            timeout_ms: Timeout in milliseconds (thread mode only)
        
        Returns:
            Tuple (buffer, index) if available, None if timeout.
        """
        # Wait for data (thread mode only)
        if not self.use_shared_memory:
            if self.available_count == 0:
                self.data_available.wait(timeout_ms / 1000.0)
                self.data_available.clear()
        
        with self.lock:
            if self.available_count == 0:
                return None
            
            # Find the next READY buffer
            start_idx = self.read_index
            for i in range(self.num_buffers):
                idx = (start_idx + i) % self.num_buffers
                if self.buffer_states[idx] == self.BUFFER_READY:
                    self.buffer_states[idx] = self.BUFFER_READING
                    self.read_index = (idx + 1) % self.num_buffers
                    return (self.buffers[idx], idx)
            
            return None
    
    def release_read(self, buffer_index: int) -> bool:
        """
        Releases a buffer after reading.
        
        Args:
            buffer_index: Index of the buffer to release
        
        Returns:
            True if successful, False if buffer not in READING state.
        """
        with self.lock:
            if self.buffer_states[buffer_index] != self.BUFFER_READING:
                return False
            
            self.buffer_states[buffer_index] = self.BUFFER_FREE
            self.available_count -= 1
            self.total_buffers_read += 1
            
            # Signal buffer freed (thread mode only)
            if not self.use_shared_memory:
                self.buffer_freed.set()
            
            return True
    
    # ------------------------------------------------------------------------
    # MAINTENANCE
    # ------------------------------------------------------------------------
    
    def reset(self) -> None:
        """Resets the buffer to initial state."""
        with self.lock:
            self.buffer_states = [self.BUFFER_FREE] * self.num_buffers
            self.write_index = 0
            self.read_index = 0
            self.available_count = 0
            if not self.use_shared_memory:
                self.data_available.clear()
            self.logger.info("🔄 Ring buffer reset")
    
    def close(self) -> None:
        """Closes shared memory if in use."""
        if self.use_shared_memory and hasattr(self, 'shm') and self.shm:
            try:
                self.shm.close()
                self.shm.unlink()
                self.logger.info(f"🗑️ Shared memory freed: {self.shm_name}")
            except Exception:
                pass
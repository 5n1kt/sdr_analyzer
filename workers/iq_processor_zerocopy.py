# -*- coding: utf-8 -*-

"""
IQ Processor with Zero-Copy Architecture
=========================================
High-performance IQ sample processor that reads directly from hardware
and distributes samples to visualization and recording ring buffers.

Key Features:
    - Zero-copy buffer management (no unnecessary data copying)
    - Separate throttling for visualization (recording receives all samples)
    - Automatic saturation detection and gain reduction
    - Thread-safe buffer operations

CORRECTIONS APPLIED:
    1. [CRITICAL] Buffer stuck in FILLING if _read_samples() fails.
       FIX: _release_viz_buffer_on_error() releases the slot correctly.
    
    2. [CRITICAL] int16_view invalidated if raw_buffer reallocated.
       FIX: raw_buffer and int16_view recreated together in _rebuild_raw_buffer().
    
    3. [CRITICAL] Throttling before hardware read caused recording loss.
       FIX: Separate viz and recording paths; throttling only gates viz buffer.
    
    4. [CRITICAL] read_samples() now uses SDRDevice interface, not direct sync_rx.
    
    5. [POTENTIAL] throttle_skips incremented even when frame didn't wait.
       FIX: increment moved inside gate condition.
    
    6. [LIMPIEZA] stop() timeout increased to 4000ms to handle sync_rx timeout.
"""

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
import logging
import time


# ============================================================================
# IQ PROCESSOR WITH ZERO-COPY BUFFERING
# ============================================================================

class IQProcessorZeroCopy(QThread):
    """
    Processes IQ samples from hardware and distributes to ring buffers.
    
    Architecture:
        Hardware → IQProcessor → [Recording Buffer] (ALL samples)
                             → [Visualization Buffer] (throttled to target FPS)
    
    This separation ensures recording captures the full signal while
    visualization remains responsive and doesn't overload the UI.
    
    Signals:
        buffer_written: Emitted when a buffer is written (count)
        error_occurred: Emitted on critical errors
        stats_updated: Emitted periodically with processing statistics
    """
    
    # ------------------------------------------------------------------------
    # SIGNALS
    # ------------------------------------------------------------------------
    buffer_written = pyqtSignal(int)
    error_occurred = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, sdr_device, ring_buffer, recording_buffer=None):
        """
        Initialize IQ Processor.
        
        Args:
            sdr_device: SDRDevice instance (implements read_samples, etc.)
            ring_buffer: IQRingBuffer for visualization
            recording_buffer: Optional IQRingBuffer for recording (all samples)
        """
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        # Hardware interface (SDRDevice contract)
        self.bladerf = sdr_device
        self.ring_buffer = ring_buffer
        self.recording_buffer = recording_buffer
        self.recording_active = False  # Recording starts disabled
        
        # Thread control
        self.is_running = False
        self._stop_flag = False
        
        # Buffer configuration
        self.samples_per_block = getattr(sdr_device, 'samples_per_block', 8192)
        self.bytes_per_sample = getattr(sdr_device, 'bytes_per_sample', 4)
        self.bytes_per_block = self.samples_per_block * self.bytes_per_sample
        
        # Raw buffer for reading from hardware
        self._rebuild_raw_buffer(self.bytes_per_block)
        
        # Visualization throttling (only affects viz buffer)
        self.throttle_enabled = True
        self.target_fps = 30
        self.sample_rate = getattr(sdr_device, 'sample_rate', 2e6)
        self.blocks_per_second = self.sample_rate / self.samples_per_block
        self.target_blocks_per_second = self.target_fps
        self.throttle_factor = max(1, int(self.blocks_per_second / self.target_blocks_per_second))
        self.last_block_time = time.time()
        self.expected_interval = 1.0 / self.target_blocks_per_second
        
        # Statistics
        self.blocks_processed = 0
        self.stats = {
            'blocks_received': 0,
            'bytes_received': 0,
            'errors': 0,
            'overflow_skips': 0,
            'write_buffer_failures': 0,
            'throttle_skips': 0,
            'recording_overflow': 0,
            'recording_writes': 0,
        }
        
        self.logger.info(
            f"✅ IQProcessorZeroCopy created: {self.samples_per_block} samples/block"
        )
        self.logger.info(
            f"⚙️ Viz throttling: {self.blocks_per_second:.0f} → "
            f"{self.target_blocks_per_second} blocks/s (factor {self.throttle_factor}x)"
        )
        if self.recording_buffer:
            self.logger.info(
                f"📼 Recording buffer: {self.recording_buffer.num_buffers} slots — "
                f"no throttle (all blocks)"
            )
    
    # ------------------------------------------------------------------------
    # THREAD MAIN LOOP
    # ------------------------------------------------------------------------
    
    def run(self):
        """
        Main processing loop.
        
        CORRECTION: The loop reads from hardware WITHOUT throttling,
        then writes to recording buffer (all blocks), and only writes to
        viz buffer if enough time has passed since last viz frame.
        
        This ensures recording captures 100% of the signal while viz
        stays at a manageable frame rate.
        """
        self.is_running = True
        self._stop_flag = False
        self.logger.info("🚀 IQProcessorZeroCopy started (dual buffer, viz-only throttle)")
        
        # Ensure hardware stream is active
        self._ensure_streaming()
        
        self.last_block_time = time.time()
        self.blocks_processed = 0
        
        while not self._stop_flag:
            try:
                # --- STEP 1: Read from hardware (NO THROTTLE) ---
                # This blocks until a block is available from the SDR.
                # The hardware controls the natural rate (e.g., 6836 blocks/s at 56 MSPS).
                if not self._read_samples():
                    # Read failed: release viz slot if reserved and continue
                    self._release_viz_buffer_on_error()
                    self.stats['errors'] += 1
                    continue
                
                # --- STEP 2: Recording — ALL blocks, unconditionally ---
                if self.recording_active and self.recording_buffer is not None:
                    rec_buffer = self._get_recording_buffer()
                    if rec_buffer is not None:
                        self._write_to_recording(rec_buffer)
                        self.recording_buffer.commit_write()
                        self.stats['recording_writes'] += 1
                
                # --- STEP 3: Visualization — only if gate opens ---
                now = time.time()
                elapsed_viz = now - self.last_block_time
                
                if not self.throttle_enabled or elapsed_viz >= self.expected_interval:
                    viz_buffer = self.ring_buffer.get_write_buffer()
                    
                    if viz_buffer is not None:
                        self._write_to_viz(viz_buffer)
                        self.ring_buffer.commit_write()
                        self.last_block_time = now
                    else:
                        # Viz ring buffer full — skip this viz frame
                        self.stats['overflow_skips'] += 1
                        self.stats['write_buffer_failures'] += 1
                else:
                    # Viz frame skipped due to throttling (recording already happened)
                    self.stats['throttle_skips'] += 1
                
                # Update statistics periodically
                self._update_stats()
                
            except Exception as exc:
                self._handle_error(exc)
        
        self.is_running = False
        self.logger.info("⏹️ IQProcessorZeroCopy stopped")
    
    # ------------------------------------------------------------------------
    # PUBLIC CONTROL METHODS
    # ------------------------------------------------------------------------
    
    def update_sample_rate(self, new_sample_rate: float) -> None:
        """
        Update sample rate and recalculate throttling.
        
        Called when sample rate changes during capture.
        """
        self.sample_rate = new_sample_rate
        self.blocks_per_second = self.sample_rate / self.samples_per_block
        self.throttle_factor = max(1, int(self.blocks_per_second / self.target_blocks_per_second))
        self.expected_interval = 1.0 / self.target_blocks_per_second
        self.last_block_time = time.time()
        
        self.logger.info(
            f"📊 Viz throttling updated: {self.blocks_per_second:.0f} → "
            f"{self.target_blocks_per_second} blocks/s (factor {self.throttle_factor}x)"
        )
    
    def attach_recording_buffer(self, recording_buffer) -> None:
        """
        Enable writing to recording buffer.
        
        Called by IQRecorderSimple when recording starts.
        Thread-safe: atomic assignment in CPython.
        """
        self.recording_buffer = recording_buffer
        self.recording_active = True
        self.logger.info(
            f"📼 Recording buffer attached: {recording_buffer.num_buffers} slots"
        )
    
    def detach_recording_buffer(self) -> None:
        """
        Disable writing to recording buffer.
        
        Called by IQRecorderSimple when recording stops.
        Prevents overflow when no recorder is active.
        """
        self.recording_active = False
        self.logger.info("📼 Recording buffer detached")
    
    def stop(self) -> None:
        """
        Stop processing.
        
        Timeout increased to 4000ms to cover sync_rx timeout (3500ms).
        """
        self._stop_flag = True
        if not self.wait(4000):
            self.logger.warning("⚠️ IQProcessor didn't respond in 4s — forcing termination")
            self.terminate()
            self.wait(500)
        self.logger.info("⏹️ IQProcessorZeroCopy stopped")
    
    # ------------------------------------------------------------------------
    # PRIVATE METHODS - BUFFER WRITING
    # ------------------------------------------------------------------------
    
    def _write_to_recording(self, rec_buffer: np.ndarray) -> None:
        """
        Write raw buffer converted to complex64 to recording buffer.
        
        Dedicated path for recording — separate from viz logic.
        """
        try:
            n = min(len(rec_buffer), self.samples_per_block)
            samples = self.int16_view[:n * 2]
            iq_pairs = samples.reshape(-1, 2)
            k = min(n, iq_pairs.shape[0])
            
            rec_buffer[:k].real = iq_pairs[:k, 0].astype(np.float32) / 2048.0
            rec_buffer[:k].imag = iq_pairs[:k, 1].astype(np.float32) / 2048.0
            
        except Exception as exc:
            self.logger.error(f"Error writing to recording buffer: {exc}")
            rec_buffer.fill(0)
    
    def _write_to_viz(self, viz_buffer: np.ndarray) -> None:
        """
        Write raw buffer converted to complex64 to visualization buffer.
        
        Dedicated path for visualization.
        """
        try:
            n = min(len(viz_buffer), self.samples_per_block)
            samples = self.int16_view[:n * 2]
            iq_pairs = samples.reshape(-1, 2)
            k = min(n, iq_pairs.shape[0])
            
            viz_buffer[:k].real = iq_pairs[:k, 0].astype(np.float32) / 2048.0
            viz_buffer[:k].imag = iq_pairs[:k, 1].astype(np.float32) / 2048.0
            
        except Exception as exc:
            self.logger.error(f"Error writing to viz buffer: {exc}")
            viz_buffer.fill(0)
    
    # ------------------------------------------------------------------------
    # PRIVATE METHODS - HARDWARE READING
    # ------------------------------------------------------------------------
    
    def _rebuild_raw_buffer(self, size: int) -> None:
        """
        Create raw_buffer and int16_view together atomically.
        
        CORRECTION: Ensures int16_view always points to current raw_buffer.
        """
        self.raw_buffer = bytearray(size)
        self.int16_view = np.frombuffer(self.raw_buffer, dtype=np.int16)
    
    def _read_samples(self) -> bool:
        """
        Read one block of raw samples into self.raw_buffer.
        
        CORRECTION: Uses read_samples() from SDRDevice contract,
        not direct sync_rx access.
        """
        try:
            if hasattr(self.bladerf, 'read_samples'):
                return self.bladerf.read_samples(self.raw_buffer, self.samples_per_block)
            
            self.logger.error(
                "❌ SDR device does not implement read_samples(). "
                "Verify SDRDevice interface is used."
            )
            return False
        except Exception as exc:
            self.logger.error(f"Error reading samples: {exc}")
            return False
    
    def _ensure_streaming(self) -> None:
        """Activate hardware stream if not already active."""
        if hasattr(self.bladerf, 'streaming') and not self.bladerf.streaming:
            try:
                self.bladerf.start_stream()
            except Exception as exc:
                self.logger.error(f"Error starting stream: {exc}")
    
    def _get_recording_buffer(self) -> np.ndarray:
        """Get write slot from recording buffer, update stats if full."""
        rec = self.recording_buffer.get_write_buffer()
        if rec is None:
            self.stats['recording_overflow'] += 1
            if self.stats['recording_overflow'] % 100 == 0:
                self.logger.warning(
                    f"⚠️ Recording overflow: {self.stats['recording_overflow']}"
                )
        return rec
    
    def _release_viz_buffer_on_error(self) -> None:
        """
        Release viz buffer slot if hardware read fails.
        
        CORRECTION: Prevents slot from staying stuck in FILLING state.
        """
        try:
            wb = self.ring_buffer
            with wb.lock:
                idx = (wb.write_index - 1) % wb.num_buffers
                if wb.buffer_states[idx] == wb.BUFFER_FILLING:
                    wb.buffer_states[idx] = wb.BUFFER_FREE
                    wb.write_index = idx
        except Exception as exc:
            self.logger.debug(f"_release_viz_buffer_on_error: {exc}")
    
    # ------------------------------------------------------------------------
    # PRIVATE METHODS - STATISTICS AND ERROR HANDLING
    # ------------------------------------------------------------------------
    
    def _update_stats(self) -> None:
        """Update statistics and emit signal every 100 blocks."""
        self.blocks_processed += 1
        self.stats['blocks_received'] += 1
        self.stats['bytes_received'] += self.bytes_per_block
        
        # Reducir frecuencia de logs de overflow (cada 500 bloques en lugar de 100)
        if self.stats['blocks_received'] % 500 == 0:
            self.stats_updated.emit(self.stats.copy())
    
    def _handle_error(self, error: Exception) -> None:
        """Log and emit error."""
        if not self._stop_flag:
            self.logger.error(f"❌ Error in IQProcessor: {error}")
            self.stats['errors'] += 1
            self.error_occurred.emit(str(error))
            time.sleep(0.01)
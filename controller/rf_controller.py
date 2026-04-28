# -*- coding: utf-8 -*-

"""
RF Controller - Hardware and Signal Reception Management
=========================================================
Manages all SDR hardware operations and the real-time signal reception pipeline.

This controller is responsible for:
    - Initializing SDR hardware via SDRDeviceFactory
    - Creating ring buffers for visualization and recording
    - Starting/stopping IQ and FFT processors
    - Handling RF parameter changes (frequency, sample rate, gain, etc.)
    - Monitoring buffer overflows and saturation

The controller uses the abstract SDRDevice interface, making it hardware-agnostic.
All bladeRF-specific code is isolated in sdr/bladerf_device.py.

Corrections Applied:
    1. Use SDRDeviceFactory for hardware initialization
    2. Recording buffer now uses threading.Lock (not shared memory)
    3. Buffer size calculation based on actual hardware rates
    4. Proper throttling separation between viz and recording
"""

import logging
import traceback
import numpy as np
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtCore import QTimer

from sdr.sdr_factory import SDRDeviceFactory
from workers.shared_buffer import IQRingBuffer
from workers.iq_processor_zerocopy import IQProcessorZeroCopy
from workers.fft_processor_zerocopy import FFTProcessorZeroCopy


# ============================================================================
# RF CONTROLLER
# ============================================================================

class RFController:
    """
    Controls all RF hardware operations and signal reception pipeline.
    
    Attributes:
        main: Reference to MainController for UI access
        logger: Logger instance
        overflow_check_timer: Timer for monitoring buffer overflows
    """
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, main_controller):
        """
        Initialize RF controller.
        
        Args:
            main_controller: Reference to the main application controller
        """
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.RFController")
        self.overflow_check_timer = None
    
    # ------------------------------------------------------------------------
    # HARDWARE INITIALIZATION
    # ------------------------------------------------------------------------
    
    def initialize_sdr(self, device_type: str = 'bladerf') -> None:
        """
        Initialize SDR hardware using the device factory.
        
        Args:
            device_type: Hardware identifier ('bladerf', 'rtlsdr', etc.)
        
        Raises:
            RuntimeError: If hardware initialization fails
        """
        try:
            self.logger.info(f"🔧 Initializing SDR: '{device_type}'...")
            
            # Create device instance via factory
            device = SDRDeviceFactory.create(device_type)
            device.initialize()
            
            # Store reference (kept as 'bladerf' for backward compatibility)
            self.main.bladerf = device
            
            # Update UI with device capabilities
            self._update_ui_with_ranges()
            
            self.logger.info(f"✅ {device.device_name} ready for operation")
            self.main.statusbar.showMessage(f"{device.device_name} connected")
            
            # Sync frequency spinner
            if hasattr(self.main, 'frequency_spinner'):
                self.main.frequency_spinner.setFrequency(device.frequency / 1e6)
            
        except Exception as exc:
            self._handle_initialization_error(exc)
    
    def _update_ui_with_ranges(self) -> None:
        """
        Pass hardware ranges to the RF widget.
        
        All ranges are SDRRange objects with .min, .max, .step attributes,
        which are compatible with RFControlsWidget.
        """
        if not hasattr(self.main, 'rf_widget'):
            return
        
        rf = self.main.rf_widget
        device = self.main.bladerf
        
        # Set ranges from device capabilities
        rf.set_frequency_range(device.freq_range)
        rf.set_gain_range(device.gain_range)
        rf.set_gain_modes(device.gain_modes)
        rf.set_sample_rate_range(device.sample_rate_range)
        rf.set_bandwidth_range(device.bandwidth_range)
        
        # Keep direct reference for widget compatibility
        rf.bladerf = device
    
    def _handle_initialization_error(self, error: Exception) -> None:
        """Handle hardware initialization errors gracefully."""
        self.logger.error(f"❌ Fatal error initializing SDR: {error}")
        traceback.print_exc()
        
        self.main.statusbar.showMessage(f"ERROR: {error}")
        QMessageBox.critical(
            self.main,
            "Hardware Error",
            f"Could not initialize SDR:\n{error}\n\n"
            "The application will continue in limited mode (playback only)."
        )
        self.main.bladerf = None
    
    # ------------------------------------------------------------------------
    # RECEPTION CONTROL
    # ------------------------------------------------------------------------
    
    def toggle_rx(self) -> None:
        """Toggle between start and stop reception."""
        if not self.main.is_running:
            self.start_rx()
        else:
            self.stop_rx()
    
    def start_rx(self) -> None:
        """
        Start real-time signal reception and processing.
        
        This method:
            1. Validates hardware availability
            2. Gets current configuration
            3. Creates ring buffers
            4. Creates IQ and FFT processors
            5. Starts processing threads
            6. Updates UI state
        """
        try:
            # Validate hardware
            if not self.main.bladerf:
                raise RuntimeError("SDR not available")
            
            # Check imports
            self._check_imports()
            
            # Get current settings
            fft_size = self._get_fft_size()
            rf_pending = self._get_rf_pending()
            params = self.main.rf_widget.get_settings()
            params.update(rf_pending)
            
            # Apply pending RF changes
            self.main.bladerf.configure(params)
            
            self.logger.info("=" * 60)
            self.logger.info("🚀 STARTING ZERO-COPY PIPELINE")
            self.logger.info("=" * 60)
            
            # Create ring buffers
            self._create_buffers(params)
            
            # Create processors
            self._create_processors(params, fft_size)
            
            # Initialize hold buffers
            self._init_hold_buffers(fft_size)
            
            # Start processors
            self.main.iq_processor.start()
            self.main.fft_processor.start()
            
            # Start audio demodulator if available
            if hasattr(self.main, 'audio_ctrl'):
                self.logger.info("🔊 Starting audio demodulator...")
                self.main.audio_ctrl.on_capture_started()
            else:
                self.logger.warning("⚠️ Audio controller not available")

            # Habilitar botón de grabación en barra superior
            if hasattr(self.main, 'set_record_button_enabled'):
                self.main.set_record_button_enabled(True)

            # Actualizar estado visual del botón (gris oscuro, listo para grabar)
            if hasattr(self.main, 'update_record_button_state'):
                self.main.update_record_button_state(False)

            # Actualizar indicador de modo
            if hasattr(self.main, 'update_mode_indicator'):
                self.main.update_mode_indicator('live')
                self.logger.info("📻 Indicador de modo: LIVE")
                    
            # Update state
            self.main.is_running = True
            self._update_ui_running_state(True, params)
            self._start_monitoring()
            
        except Exception as exc:
            self._handle_start_error(exc)
    
    def _check_imports(self) -> None:
        """Verify all required modules are importable."""
        try:
            from workers.shared_buffer import IQRingBuffer
            from workers.iq_processor_zerocopy import IQProcessorZeroCopy
            from workers.fft_processor_zerocopy import FFTProcessorZeroCopy
            self.logger.info("✅ All imports OK")
        except ImportError as exc:
            self.logger.error(f"❌ Import error: {exc}")
            raise
    
    def _get_fft_size(self) -> int:
        """Get current or pending FFT size from FFT widget."""
        if hasattr(self.main, 'fft_widget'):
            pending = self.main.fft_widget.get_pending_size()
            if pending:
                self.logger.info(f"🔄 Applying pending FFT size: {pending}")
                return int(pending)
            return self.main.fft_widget.get_settings()['fft_size']
        return 1024
    
    def _get_rf_pending(self) -> dict:
        """Get pending RF changes (sample rate, bandwidth) from RF widget."""
        if hasattr(self.main, 'rf_widget'):
            pending = self.main.rf_widget.get_pending_changes()
            if pending:
                self.logger.info(f"🔄 Applying pending RF changes: {pending}")
            return pending
        return {}
    
    def _create_buffers(self, params: dict) -> None:
        """
        Create ring buffers for visualization and recording.
        
        CORRECTION: Recording buffer now uses threading.Lock (use_shared_memory=False)
        and is sized to absorb REC_BUFFER_SECONDS of full-rate signal.
        
        Calculation:
            blocks_per_second = sample_rate / samples_per_block
            num_rec_buffers = max(256, blocks_per_second * REC_BUFFER_SECONDS)
        """
        device = self.main.bladerf
        samples_per_block = device.samples_per_block
        current_sr = device.sample_rate
        
        # --- Visualization buffer (throttled) ---
        #num_viz_buffers = 24 if current_sr > 40e6 else 12
        num_viz_buffers = 256 if current_sr > 40e6 else 128
        self.logger.info(f"📦 Viz buffer: {num_viz_buffers} slots × {samples_per_block} samples")
        
        # --- Recording buffer (full rate, sized for latency tolerance) ---
        REC_BUFFER_SECONDS = 5  # Buffer to absorb disk write latency
        blocks_per_second = current_sr / samples_per_block
        num_rec_buffers = max(256, int(blocks_per_second * REC_BUFFER_SECONDS + 0.5))
        
        self.logger.info(
            f"📦 Ring buffer (viz):      {num_viz_buffers} slots × {samples_per_block} samples"
        )
        self.logger.info(
            f"📦 Recording buffer:        {num_rec_buffers} slots × {samples_per_block} samples  "
            f"({num_rec_buffers * samples_per_block * 8 / 1e6:.1f} MB RAM)"
        )
        
        # Create visualization buffer (thread-safe)
        self.main.ring_buffer = IQRingBuffer(
            num_buffers=num_viz_buffers,
            samples_per_buffer=samples_per_block,
            use_shared_memory=False
        )
        
        # Create recording buffer (thread-safe, NOT shared memory)
        # CORRECTION: use_shared_memory=False prevents multiprocessing.Lock overhead
        self.main.recording_ring_buffer = IQRingBuffer(
            num_buffers=num_rec_buffers,
            samples_per_buffer=samples_per_block,
            use_shared_memory=False
        )
        
        # Notify IQ Manager
        if hasattr(self.main, 'iq_manager'):
            freq_mhz = self.main.bladerf.frequency / 1e6
            sr = self.main.bladerf.sample_rate
            self.main.iq_manager.set_rf_info(freq_mhz, sr)
            self.main.iq_manager.on_capture_started(self.main.recording_ring_buffer)
    
    def _create_processors(self, params: dict, fft_size: int) -> None:
        """
        Create IQ and FFT processor threads.
        
        IQProcessorZeroCopy handles reading from hardware and distributing
        samples to both visualization and recording buffers.
        """
        device = self.main.bladerf
        
        # IQ Processor (connects hardware to both buffers)
        self.main.iq_processor = IQProcessorZeroCopy(
            device,
            self.main.ring_buffer,
            self.main.recording_ring_buffer
        )
        
        # Configure throttling for visualization
        self._configure_throttling(params, device.samples_per_block)
        
        # FFT Processor (reads from visualization buffer)
        self.main.fft_processor = FFTProcessorZeroCopy(
            self.main.ring_buffer,
            sample_rate=params['sample_rate']
        )
        
        # Apply FFT settings
        fft_settings = self.main.fft_widget.get_settings()
        self.main.fft_processor.update_settings({
            'fft_size': fft_size,
            'window': fft_settings['window'],
            'averaging': fft_settings['averaging'],
            'overlap': fft_settings['overlap'],
            'sample_rate': params['sample_rate']
        })
        
        # Connect signals
        self.main.iq_processor.stats_updated.connect(self._on_iq_stats)
        self.main.fft_ctrl.connect_fft_processor(self.main.fft_processor)
    
    def _configure_throttling(self, params: dict, samples_per_block: int) -> None:
        """
        Configure visualization throttling in IQProcessor.
        
        The throttling only affects visualization buffer writes;
        recording buffer receives ALL samples at full hardware rate.
        """
        iqp = self.main.iq_processor
        iqp.throttle_enabled = True
        iqp.target_fps = 30
        iqp.sample_rate = params['sample_rate']
        iqp.blocks_per_second = params['sample_rate'] / samples_per_block
        iqp.throttle_factor = max(1, int(iqp.blocks_per_second / iqp.target_blocks_per_second))
        iqp.expected_interval = 1.0 / iqp.target_blocks_per_second
        
        self.logger.info(f"⚙️ Viz throttling: {iqp.throttle_factor}x ({iqp.blocks_per_second:.0f} → {iqp.target_blocks_per_second} blocks/s)")
    
    def _init_hold_buffers(self, fft_size: int) -> None:
        """Initialize max/min hold buffers with extreme values."""
        self.main.max_hold = np.full(fft_size, self.main.FLOOR_DB)
        self.main.min_hold = np.full(fft_size, self.main.CEILING_DB)
    
    def _update_ui_running_state(self, running: bool, params: dict = None) -> None:
        """Update UI elements based on reception state."""
        btn = self.main.pushButton_start_stop_main
        
        if running:
            btn.setText("Detener")
            #btn.setStyleSheet("background-color: #ff4444; color: white; font-weight: bold;")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #0060cc;
                    color: white;
                    border: 1px solid #004099;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #1a80ff;
                }
            """)
            
            # Notify FFT and RF widgets about capture start
            if hasattr(self.main, 'fft_widget'):
                self.main.fft_widget.on_capture_started()
            if hasattr(self.main, 'rf_widget'):
                self.main.rf_widget.on_capture_started()
            
            # Update status bar
            sample_rate = params['sample_rate'] if params else 2e6
            fft_size = params.get('fft_size', 1024) if params else 1024
            self.main.statusbar.showMessage(
                f"Capturing — Throttling {self.main.iq_processor.throttle_factor}x | "
                f"Sample Rate: {sample_rate/1e6:.1f} MHz | FFT: {fft_size}"
            )
        else:
            btn.setText("Iniciar")
            #btn.setStyleSheet("")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #0080ff;
                    color: white;
                    border: 1px solid #0060cc;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #1a90ff;
                }
            """)
            
            if hasattr(self.main, 'fft_widget'):
                self.main.fft_widget.on_capture_stopped()
            if hasattr(self.main, 'rf_widget'):
                self.main.rf_widget.on_capture_stopped()
            
            self.main.statusbar.showMessage("Stopped")
    
    def _start_monitoring(self) -> None:
        """Start periodic monitoring of buffer overflows."""
        self.overflow_check_timer = QTimer()
        self.overflow_check_timer.timeout.connect(self._check_overflows)
        self.overflow_check_timer.start(2000)
    
    def _handle_start_error(self, error: Exception) -> None:
        """Handle errors during reception start."""
        self.logger.error(f"❌ Error in start_rx: {error}")
        traceback.print_exc()
        self.main.statusbar.showMessage(f"Error starting: {error}")
    
    # ------------------------------------------------------------------------
    # STOP RECEPTION
    # ------------------------------------------------------------------------
    
    def stop_rx(self) -> None:
        """
        Stop real-time signal reception and clean up resources.
        
        Order of operations:
            1. Stop audio demodulator
            2. Stop monitoring timer
            3. Stop FFT processor
            4. Stop IQ processor
            5. Notify IQ Manager
            6. Clear buffers
            7. Stop hardware stream
        """
        try:
            # Stop audio demodulator
            if hasattr(self.main, 'audio_ctrl') and self.main.audio_ctrl.is_active:
                self.logger.info("🔇 Stopping audio demodulator...")
                self.main.audio_ctrl.on_capture_stopped()
            
            # Stop monitoring timer
            if self.overflow_check_timer:
                self.overflow_check_timer.stop()
            
            # Stop FFT processor
            if self.main.fft_processor is not None:
                self.logger.info("⏹️ Stopping FFTProcessor...")
                self.main.fft_processor.stop()
                self.main.fft_processor = None
            
            # Stop IQ processor
            if self.main.iq_processor is not None:
                self.logger.info("⏹️ Stopping IQProcessor...")
                self.main.iq_processor.stop()
                self.main.iq_processor = None
            
            # Notify IQ Manager
            if hasattr(self.main, 'iq_manager'):
                self.main.iq_manager.on_capture_stopped()
            
            # Clear buffers
            self.main.ring_buffer = None
            self.main.recording_ring_buffer = None
            
            # Stop hardware stream (using SDRDevice interface)
            if self.main.bladerf and self.main.bladerf.streaming:
                self.main.bladerf.stop_stream()
            
            # Update state
            self.main.is_running = False
            self._update_ui_running_state(False)
            self.logger.info("✅ Capture stopped")

            # Deshabilitar botón de grabación
            if hasattr(self.main, 'set_record_button_enabled'):
                self.main.set_record_button_enabled(False)

            # Actualizar estado visual del botón (gris deshabilitado)
            if hasattr(self.main, 'update_record_button_state'):
                self.main.update_record_button_state(False)

            # Actualizar indicador de modo
            if hasattr(self.main, 'update_mode_indicator'):
                self.main.update_mode_indicator('idle')
                self.logger.info("📻 Indicador de modo: ---")
                    
        except Exception as exc:
            self.logger.error(f"❌ Error in stop_rx: {exc}")
            # Force cleanup
            self.main.iq_processor = None
            self.main.fft_processor = None
            self.main.ring_buffer = None
            self.main.recording_ring_buffer = None
            self.main.is_running = False
    
    # ------------------------------------------------------------------------
    # RF SETTINGS UPDATE
    # ------------------------------------------------------------------------
    
    def update_rf_settings(self, settings: dict) -> None:
        """
        Update RF parameters.
        
        Handles fast frequency changes without restarting the pipeline
        when only frequency changes.
        
        Args:
            settings: Dictionary with RF parameters
        """
        if not settings or not isinstance(settings, dict):
            self.logger.warning("⚠️ update_rf_settings: invalid settings")
            return
        
        if not self.main.bladerf:
            self.logger.warning("⚠️ SDR not available")
            return
        
        # Log changes
        changes = self._format_changes(settings)
        if changes:
            self.logger.info(f"📻 Updating RF: {changes}")
        
        # Fast path: frequency only while running
        if self._is_frequency_only_change(settings) and self.main.is_running:
            if self._try_fast_frequency_change(settings):
                return
        
        # Full reconfiguration: stop, apply, restart
        was_running = self.main.is_running
        if was_running:
            self.logger.info("⏸ Stopping capture to apply changes...")
            self.stop_rx()
        
        # Apply settings to hardware
        self._apply_rf_config(settings)
        
        # Handle sample rate change (affects downstream processors)
        if 'sample_rate' in settings and settings['sample_rate'] is not None:
            self._handle_sample_rate_change(settings['sample_rate'])
        
        # Restart capture if it was running
        if was_running:
            self.logger.info("▶ Restarting capture...")
            self.start_rx()
    
    def _format_changes(self, settings: dict) -> str:
        """Format settings dictionary for logging."""
        parts = []
        if settings.get('frequency') is not None:
            parts.append(f"freq={settings['frequency']/1e6:.1f} MHz")
        if settings.get('sample_rate') is not None:
            parts.append(f"sr={settings['sample_rate']/1e6:.1f} MSPS")
        if settings.get('bandwidth') is not None:
            parts.append(f"bw={settings['bandwidth']/1e6:.1f} MHz")
        if settings.get('gain') is not None:
            parts.append(f"gain={settings['gain']} dB")
        return ', '.join(parts)
    
    def _is_frequency_only_change(self, settings: dict) -> bool:
        """Check if settings only contain frequency."""
        return (
            len(settings) == 1
            and 'frequency' in settings
            and settings['frequency'] is not None
        )
    
    def _try_fast_frequency_change(self, settings: dict) -> bool:
        """
        Attempt fast frequency change without pipeline restart.
        
        Uses SDRDevice.set_frequency() which is optimized for this operation.
        """
        freq_hz = settings['frequency']
        self.logger.info(f"📡 Fast frequency change to {freq_hz/1e6:.3f} MHz")
        
        success = self.main.bladerf.set_frequency(freq_hz)
        if success:
            self.main.sync_frequency_widgets(freq_hz / 1e6)
            return True
        
        self.logger.error("❌ Fast frequency change failed")
        return False
    
    def _apply_rf_config(self, settings: dict) -> None:
        """Apply RF settings to hardware."""
        filtered = {k: v for k, v in settings.items() if v is not None}
        if filtered:
            self.main.bladerf.configure(filtered)
    
    def _handle_sample_rate_change(self, new_sr: float) -> None:
        """
        Handle sample rate change by updating downstream processors.
        
        The IQProcessor and FFTProcessor both need to know the new sample rate
        for correct throttling and frequency axis calculation.
        """
        self.logger.info(f"🔄 Sample rate changed to {new_sr/1e6:.1f} MSPS")
        
        # Update IQ Processor throttling
        if hasattr(self.main, 'iq_processor') and self.main.iq_processor:
            self.main.iq_processor.update_sample_rate(new_sr)
        
        # Update FFT Processor frequency axis
        if hasattr(self.main, 'fft_processor') and self.main.fft_processor:
            self.main.fft_processor.update_settings({'sample_rate': new_sr})
        
        # Update IQ Manager display
        if hasattr(self.main, 'iq_manager') and self.main.bladerf:
            freq_mhz = self.main.bladerf.frequency / 1e6
            self.main.iq_manager.set_rf_info(freq_mhz, new_sr)
            self.logger.debug(f"   IQ Manager updated: {freq_mhz:.1f} MHz, {new_sr/1e6:.1f} MSPS")
    
    # ------------------------------------------------------------------------
    # MONITORING AND STATISTICS
    # ------------------------------------------------------------------------
    
    def _on_iq_stats(self, stats: dict) -> None:
        """Handle IQ processor statistics updates."""
        if stats.get('overflow_skips', 0) > 0:
            self.logger.warning(f"⚠️ IQ overflows: {stats['overflow_skips']}")
            self.main.statusbar.showMessage(f"Overflows: {stats['overflow_skips']}", 2000)
    
    def _check_overflows(self) -> None:
        """Check ring buffer for overflows and warn."""
        if hasattr(self.main, 'ring_buffer') and self.main.ring_buffer:
            stats = self.main.ring_buffer.get_stats()
            if stats['overflow'] > 0:
                self.logger.warning(f"⚠️ Ring buffer overflows: {stats['overflow']}")
                self.main.statusbar.showMessage(f"Overflows: {stats['overflow']}", 2000)
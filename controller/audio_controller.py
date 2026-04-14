# -*- coding: utf-8 -*-

"""
Audio Controller - Demodulation Management
===========================================
Controls the audio demodulation worker and integrates with the main pipeline.

This controller manages:
    - Starting/stopping the demodulator worker
    - Connecting demodulator signals to the UI
    - Audio device selection
    - Mode and parameter updates
"""
import os
import logging
import pyaudio
from PyQt5.QtCore import QObject

from workers.demodulator_worker import DemodulatorWorker
from widgets.audio_widget_compact import AudioWidgetCompact


# ============================================================================
# AUDIO CONTROLLER
# ============================================================================

class AudioController(QObject):
    """
    Controls audio demodulation.
    
    The demodulator worker is only started when the user enables it
    via the widget's toggle button, even if capture is running.
    """
    
    def __init__(self, main_controller):
        super().__init__()
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.AudioController")
        
        self.widget = None
        self.worker = None
        self.is_active = False
        
        self.logger.info("✅ AudioController initialized")
    
    # ------------------------------------------------------------------------
    # WIDGET CREATION
    # ------------------------------------------------------------------------
    
    def create_widget(self) -> AudioWidgetCompact:
        """Create and configure the audio widget."""
        if self.widget is None:
            self.widget = AudioWidgetCompact(self.main)
            
            # Connect signals
            self.widget.mode_changed.connect(self.on_mode_changed)
            self.widget.volume_changed.connect(self.on_volume_changed)
            self.widget.squelch_changed.connect(self.on_squelch_changed)
            self.widget.bfo_changed.connect(self.on_bfo_changed)
            self.widget.filter_changed.connect(self.on_filter_changed)
            self.widget.mute_toggled.connect(self.on_mute_toggled)
            self.widget.test_tone_requested.connect(self.on_test_tone)
            self.widget.demodulator_toggled.connect(self.on_demodulator_toggled)
            self.widget.agc_toggled.connect(self.on_agc_toggled)
            self.widget.record_requested.connect(self.on_record_requested)
            self.widget.record_stop.connect(self.on_record_stop)
            
            # Audio device selection
            self.widget.comboBox_audio_device.currentIndexChanged.connect(
                self.on_audio_device_changed
            )
        
        return self.widget
    
    # ------------------------------------------------------------------------
    # CAPTURE STATE
    # ------------------------------------------------------------------------
    
    def on_capture_started(self) -> None:
        """
        Called when live capture starts.
        
        The demodulator is NOT started automatically. It waits for user
        to press the DEMODULATOR button.
        """
        self.logger.info("🔊 Capture started, demodulator ready for activation")
        self.widget.is_active = False
        self.widget.label_status_icon.setText("🔇")
        self.widget.label_status_icon.setStyleSheet("color: #888888;")
    
    def on_capture_stopped(self) -> None:
        """Called when live capture stops. Always stop demodulator."""
        self._stop_worker()
    
    # ------------------------------------------------------------------------
    # DEMODULATOR CONTROL
    # ------------------------------------------------------------------------
    
    def on_demodulator_toggled(self, enabled: bool) -> None:
        """Enable or disable the demodulator worker."""
        if enabled:
            self._start_worker()
        else:
            self._stop_worker()
    
    def _start_worker(self) -> None:
        """Start the demodulator worker."""
        if not self.main.ring_buffer:
            self.logger.warning("⚠️ No ring buffer available")
            return
        
        if self.worker is not None:
            self.logger.warning("⚠️ Worker already exists, stopping first")
            self._stop_worker()
        
        self.logger.info("🔊 Starting demodulator...")
        
        self.worker = DemodulatorWorker(
            self.main.ring_buffer,
            self.main.bladerf.sample_rate if self.main.bladerf else 2e6
        )
        
        # Connect signals
        self.worker.vu_level.connect(self.widget.update_vu)
        self.worker.squelch_changed.connect(self.widget.update_squelch_indicator)
        self.worker.snr_updated.connect(self.widget.update_snr)
        self.worker.recording_state.connect(self.widget.update_recording_state)
        self.worker.error_occurred.connect(self.on_error)
        
        self.worker.start()
        self.widget.set_active_state(True)
        self.is_active = True
        
        self.logger.info("✅ Demodulator active")
    
    def _stop_worker(self) -> None:
        """Stop the demodulator worker."""
        if self.worker:
            self.logger.info("🔇 Stopping demodulator...")
            self.worker.stop()
            self.worker = None
        
        self.widget.set_active_state(False)
        self.is_active = False
        self.logger.info("✅ Demodulator stopped")
    
    # ------------------------------------------------------------------------
    # DEMODULATOR PARAMETERS
    # ------------------------------------------------------------------------
    
    def on_mode_changed(self, mode: str) -> None:
        """Change demodulation mode."""
        if self.worker:
            self.worker.set_mode(mode)
            self.logger.info(f"📻 Mode: {mode}")
    
    def on_volume_changed(self, volume: float) -> None:
        """Change output volume."""
        if self.worker:
            self.worker.set_volume(volume)
    
    def on_squelch_changed(self, threshold: float, enabled: bool) -> None:
        """Change squelch settings."""
        if self.worker:
            self.worker.set_squelch(threshold, enabled)
    
    def on_bfo_changed(self, freq_hz: int, auto: bool) -> None:
        """Change BFO settings."""
        if self.worker:
            enabled = self.widget.groupBox_bfo.isChecked()
            self.worker.set_bfo(float(freq_hz), enabled, auto)
    
    def on_filter_changed(self, lowpass: str, highpass: str) -> None:
        """Change audio filters."""
        if self.worker:
            # Map display names to frequencies
            lpf_map = {'2.4k': 2400, '3.0k': 3000, '3.5k': 3500,
                       '5.0k': 5000, '8.0k': 8000, '10k': 10000}
            hpf_map = {'OFF': 0, '50': 50, '100': 100, '200': 200, '300': 300}
            
            lpf_hz = lpf_map.get(lowpass, 5000)
            hpf_hz = hpf_map.get(highpass, 0)
            
            self.worker.set_lowpass(lpf_hz)
            self.worker.set_highpass(hpf_hz)
    
    def on_mute_toggled(self, muted: bool) -> None:
        """Mute/unmute audio."""
        if self.worker:
            volume = 0.0 if muted else self.widget.horizontalSlider_volume.value() / 100.0
            self.worker.set_volume(volume)
    
    def on_agc_toggled(self, enabled: bool) -> None:
        """Enable/disable AGC."""
        if self.worker:
            self.worker.set_agc(enabled)
    
    def on_audio_device_changed(self, index: int) -> None:
        """Change audio output device."""
        if self.worker:
            device_idx = self.widget.comboBox_audio_device.currentData()
            self.logger.info(f"🎧 Changing audio device: {device_idx}")
            
            if device_idx == -1:
                self.worker.set_audio_device(None)
            else:
                self.worker.set_audio_device(device_idx)
    
    def on_record_requested(self) -> None:
        """Start recording to WAV."""
        if self.worker:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recordings/audio_{timestamp}.wav"
            os.makedirs("recordings", exist_ok=True)
            self.worker.start_recording(filename)
    
    def on_record_stop(self) -> None:
        """Stop recording."""
        if self.worker:
            self.worker.stop_recording()
    
    def on_test_tone(self) -> None:
        """Generate test tone."""
        self.logger.info("🔊 Test tone requested")
        # TODO: Implement test tone generation
    
    def on_error(self, msg: str) -> None:
        """Handle demodulator errors."""
        self.logger.error(f"❌ Demodulator error: {msg}")
        self.main.statusbar.showMessage(f"Audio error: {msg}", 3000)
# -*- coding: utf-8 -*-

"""
Compact Audio Widget - GQRX Style
==================================
Widget for audio demodulation controls with compact VU meter.

Features:
    - Mode selection (FM, NBFM, AM, USB, LSB, CW)
    - Volume control with mute
    - Squelch with visual indicator
    - BFO (Beat Frequency Oscillator) for SSB/CW
    - Audio device selection
    - AGC toggle
    - WAV recording controls
    - SNR display with progress bar
"""

from PyQt5.QtWidgets import QDockWidget, QLabel
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QPainter, QColor
from PyQt5.uic import loadUi
import logging
import pyaudio


# ============================================================================
# COMPACT VU METER
# ============================================================================

class VUMeterCompact(QLabel):
    """
    Compact VU meter (30px height) with peak hold and decay.
    
    Displays audio level in dB with color coding:
        Green:  -60 to -20 dB (normal)
        Yellow: -20 to -6 dB  (loud)
        Red:    -6 to 0 dB    (clipping)
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = -60      # Current level in dB
        self.peak = -60       # Peak hold level
        self.setMinimumHeight(26)
        self.setMaximumHeight(26)
        
        # Peak decay timer (0.5 dB per 50ms)
        self.peak_timer = QTimer()
        self.peak_timer.timeout.connect(self._decay_peak)
        self.peak_timer.start(50)
    
    def set_level(self, level_db: float) -> None:
        """
        Update VU meter level.
        
        Args:
            level_db: Audio level in dB (typically -60 to 0)
        """
        self.level = max(-60, min(0, level_db))
        if self.level > self.peak:
            self.peak = self.level
        self.update()
    
    def _decay_peak(self) -> None:
        """Gradually decay the peak hold."""
        if self.peak > -60:
            self.peak = max(-60, self.peak - 0.5)
            self.update()
    
    def paintEvent(self, event) -> None:
        """Draw the VU meter."""
        painter = QPainter(self)
        rect = self.rect()
        
        # Background
        painter.fillRect(rect, QColor(30, 30, 30))
        
        # Calculate level position (0 to width)
        level_pos = int((self.level + 60) / 60 * rect.width())
        level_pos = max(0, min(rect.width(), level_pos))
        
        # Color based on level
        if self.level < -20:
            color = QColor(0, 255, 0)      # Green
        elif self.level < -6:
            color = QColor(255, 255, 0)    # Yellow
        else:
            color = QColor(255, 0, 0)      # Red
        
        # Draw level bar
        painter.fillRect(0, 0, level_pos, rect.height(), color)
        
        # Draw peak marker
        peak_pos = int((self.peak + 60) / 60 * rect.width())
        peak_pos = max(0, min(rect.width(), peak_pos))
        painter.fillRect(peak_pos - 2, 0, 4, rect.height(), QColor(255, 255, 255))
        
        # Draw level text
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(rect, Qt.AlignCenter, f"{self.level:.1f} dB")


# ============================================================================
# AUDIO WIDGET
# ============================================================================

class AudioWidgetCompact(QDockWidget):
    """
    Compact demodulation widget with all audio controls.
    
    Signals:
        mode_changed: Emitted when demodulation mode changes
        volume_changed: Emitted with volume value (0.0-1.0)
        squelch_changed: Emitted with (threshold, enabled)
        bfo_changed: Emitted with (frequency_hz, auto_enabled)
        filter_changed: Emitted with (lowpass, highpass)
        mute_toggled: Emitted with mute state
        test_tone_requested: Emitted when test tone button clicked
        demodulator_toggled: Emitted when demodulator on/off toggled
        agc_toggled: Emitted when AGC enabled/disabled
        record_requested: Emitted when record button clicked
        record_stop: Emitted when stop recording clicked
    """
    
    # Signals
    mode_changed = pyqtSignal(str)
    volume_changed = pyqtSignal(float)
    squelch_changed = pyqtSignal(float, bool)
    bfo_changed = pyqtSignal(int, bool)
    filter_changed = pyqtSignal(str, str)
    mute_toggled = pyqtSignal(bool)
    test_tone_requested = pyqtSignal()
    demodulator_toggled = pyqtSignal(bool)
    agc_toggled = pyqtSignal(bool)
    record_requested = pyqtSignal()
    record_stop = pyqtSignal()
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # Load UI
        loadUi('ui/audio_widget_compact.ui', self)
        
        # Replace VU label with custom meter
        self.vu_meter = VUMeterCompact()
        self.frame_vu_meter.layout().replaceWidget(self.label_vu, self.vu_meter)
        self.label_vu.deleteLater()
        
        # State
        self.is_active = False
        self.current_mode = 'FM'
        self.demodulator_enabled = True
        
        # Setup UI
        self.setup_ui()
        self.setup_connections()
        
        # Load audio devices
        self.load_audio_devices()
        
        self.logger.info("✅ AudioWidgetCompact created")
    
    # ------------------------------------------------------------------------
    # UI SETUP
    # ------------------------------------------------------------------------
    
    def setup_ui(self) -> None:
        """Configure initial UI values."""
        # Volume slider (0-100%)
        self.horizontalSlider_volume.setValue(80)
        self.horizontalSlider_squelch.setValue(10)
        
        # BFO group (disabled initially)
        self.groupBox_bfo.setChecked(False)
        self.spinBox_bfo.setEnabled(False)
        self.checkBox_bfo_auto.setEnabled(False)
        
        # Squelch indicator
        self.update_squelch_indicator(False)
        
        # Mute button
        self.pushButton_mute.setChecked(False)
        
        # Demodulator enable button (toggle with visual feedback)
        self.pushButton_demodulator.setCheckable(True)
        self.pushButton_demodulator.setChecked(True)
        self.pushButton_demodulator.setText("🔊 DEMOD. ON")
        self.pushButton_demodulator.setStyleSheet("""
            QPushButton:checked {
                background-color: #00aa00;
                color: white;
                font-weight: bold;
            }
            QPushButton:!checked {
                background-color: #aa0000;
                color: white;
                font-weight: bold;
            }
        """)
    
    def setup_connections(self) -> None:
        """Connect all UI signals."""
        self.comboBox_mode.currentTextChanged.connect(self.on_mode_changed)
        self.horizontalSlider_volume.valueChanged.connect(self.on_volume_changed)
        self.horizontalSlider_squelch.valueChanged.connect(self.on_squelch_changed)
        self.checkBox_squelch_enable.toggled.connect(self.on_squelch_enabled)
        self.pushButton_mute.toggled.connect(self.on_mute_toggled)
        self.groupBox_bfo.toggled.connect(self.on_bfo_toggled)
        self.spinBox_bfo.valueChanged.connect(self.on_bfo_changed)
        self.checkBox_bfo_auto.toggled.connect(self.on_bfo_auto_toggled)
        self.comboBox_lowpass.currentTextChanged.connect(self.on_filter_changed)
        self.comboBox_highpass.currentTextChanged.connect(self.on_filter_changed)
        self.pushButton_test_tone.clicked.connect(self.test_tone_requested)
        self.pushButton_demodulator.toggled.connect(self.on_demodulator_toggled)
        self.checkBox_agc.toggled.connect(self.on_agc_toggled)
        self.pushButton_record.toggled.connect(self.on_record_toggled)
    
    # ------------------------------------------------------------------------
    # AUDIO DEVICES
    # ------------------------------------------------------------------------
    
    def load_audio_devices(self) -> None:
        """Load available audio output devices."""
        try:
            p = pyaudio.PyAudio()
            self.comboBox_audio_device.clear()
            
            # Add system default option
            self.comboBox_audio_device.addItem("🔊 System default", -1)
            
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxOutputChannels'] > 0:  # Only output devices
                    name = info['name']
                    # Clean up common names
                    if 'ALC897 Analog' in name:
                        name = "🎧 Analog"
                    self.comboBox_audio_device.addItem(name, i)
            
            p.terminate()
            self.logger.info(f"✅ Loaded {self.comboBox_audio_device.count()} audio devices")
            
        except Exception as e:
            self.logger.error(f"Error loading audio devices: {e}")
    
    def get_audio_device(self) -> int:
        """Get selected audio device index."""
        return self.comboBox_audio_device.currentData()
    
    # ------------------------------------------------------------------------
    # PUBLIC METHODS
    # ------------------------------------------------------------------------
    
    def update_vu(self, level_db: float) -> None:
        """Update VU meter level."""
        self.vu_meter.set_level(level_db)
    
    def update_squelch_indicator(self, is_open: bool) -> None:
        """
        Update squelch status indicator.
        
        Args:
            is_open: True if squelch is open (audio passing)
        """
        if is_open:
            self.label_squelch_indicator.setText("🟢")
            self.label_squelch_indicator.setToolTip("Squelch open - audio passing")
        else:
            self.label_squelch_indicator.setText("🔴")
            self.label_squelch_indicator.setToolTip("Squelch closed - muted")
    
    def set_active_state(self, active: bool) -> None:
        """
        Set demodulator active state.
        
        Args:
            active: True if demodulator is processing audio
        """
        self.is_active = active
        if active and self.demodulator_enabled:
            self.label_status_icon.setText("🔊")
            self.label_status_icon.setStyleSheet("color: #00ff00;")
        else:
            self.label_status_icon.setText("🔇")
            self.label_status_icon.setStyleSheet("color: #888888;")
    
    def update_snr(self, snr_db: float) -> None:
        """Update SNR display."""
        self.progressBar_snr.setValue(int(snr_db))
        self.label_snr_value.setText(f"{snr_db:.1f} dB")
    
    def update_recording_state(self, active: bool, filename: str) -> None:
        """Update recording status display."""
        if active:
            import os
            self.label_record_filename.setText(os.path.basename(filename))
        else:
            self.label_record_filename.setText("none")
            self.pushButton_record.setChecked(False)
            self.pushButton_record.setText("⏺ REC")
    
    # ------------------------------------------------------------------------
    # SLOTS
    # ------------------------------------------------------------------------
    
    def on_mode_changed(self, mode: str) -> None:
        """Handle demodulation mode change."""
        self.current_mode = mode
        self.mode_changed.emit(mode)
        
        # Enable BFO only for SSB/CW modes
        bfo_needed = mode in ['LSB', 'USB', 'CW']
        self.groupBox_bfo.setEnabled(bfo_needed)
        if not bfo_needed:
            self.groupBox_bfo.setChecked(False)
    
    def on_volume_changed(self, value: int) -> None:
        """Handle volume change."""
        volume = value / 100.0
        self.label_volume_value.setText(f"{value}%")
        self.volume_changed.emit(volume)
    
    def on_squelch_changed(self, value: int) -> None:
        """Handle squelch threshold change."""
        threshold = value / 100.0
        self.label_squelch_value.setText(f"{threshold:.2f}")
        self.squelch_changed.emit(threshold, self.checkBox_squelch_enable.isChecked())
    
    def on_squelch_enabled(self, enabled: bool) -> None:
        """Handle squelch enable/disable."""
        self.squelch_changed.emit(
            self.horizontalSlider_squelch.value() / 100.0,
            enabled
        )
    
    def on_mute_toggled(self, muted: bool) -> None:
        """Handle mute toggle."""
        self.pushButton_mute.setText("🔇" if muted else "🔊")
        self.mute_toggled.emit(muted)
    
    def on_bfo_toggled(self, enabled: bool) -> None:
        """Handle BFO enable/disable."""
        self.spinBox_bfo.setEnabled(enabled)
        self.checkBox_bfo_auto.setEnabled(enabled)
        if enabled:
            self.bfo_changed.emit(self.spinBox_bfo.value(), self.checkBox_bfo_auto.isChecked())
    
    def on_bfo_changed(self, freq_hz: int) -> None:
        """Handle BFO frequency change."""
        if self.groupBox_bfo.isChecked():
            self.bfo_changed.emit(freq_hz, self.checkBox_bfo_auto.isChecked())
    
    def on_bfo_auto_toggled(self, auto: bool) -> None:
        """Handle BFO auto mode toggle."""
        if self.groupBox_bfo.isChecked():
            self.bfo_changed.emit(self.spinBox_bfo.value(), auto)
    
    def on_filter_changed(self) -> None:
        """Handle audio filter change."""
        lowpass = self.comboBox_lowpass.currentText()
        highpass = self.comboBox_highpass.currentText()
        self.filter_changed.emit(lowpass, highpass)
    
    def on_demodulator_toggled(self, enabled: bool) -> None:
        """Handle demodulator enable/disable."""
        self.demodulator_enabled = enabled
        self.pushButton_demodulator.setText(
            "🔊 DEMOD. ON" if enabled else "🔇 DEMOD. OFF"
        )
        self.demodulator_toggled.emit(enabled)
    
    def on_agc_toggled(self, enabled: bool) -> None:
        """Handle AGC toggle."""
        self.agc_toggled.emit(enabled)
    
    def on_record_toggled(self, checked: bool) -> None:
        """Handle record button toggle."""
        if checked:
            self.pushButton_record.setText("⏹ STOP")
            self.record_requested.emit()
        else:
            self.pushButton_record.setText("⏺ REC")
            self.record_stop.emit()
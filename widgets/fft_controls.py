# widgets/fft_controls.py
# -*- coding: utf-8 -*-

"""
FFT Controls Widget
===================
Widget for controlling FFT parameters (size, window, averaging, overlap).

Features:
    - FFT size selection (256 to 16384)
    - Window type selection (Rectangular, Hann, Hamming, Blackman, Kaiser)
    - Averaging control (1 to 100)
    - Overlap control (0 to 95%)
    - Blocking of FFT size during capture (pending changes)
"""

from PyQt5.QtWidgets import QDockWidget
from PyQt5.QtCore import pyqtSignal
from PyQt5.uic import loadUi
import logging


class FFTControlsWidget(QDockWidget):
    """Widget for controlling FFT parameters with size locking during capture."""
    
    # ------------------------------------------------------------------------
    # SIGNALS
    # ------------------------------------------------------------------------
    settings_changed = pyqtSignal(dict)
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        # State
        self.is_running = False
        self.pending_fft_size = None
        
        # Load UI
        loadUi('ui/fft_controls_widget.ui', self)
        
        # Configure UI
        self.setup_ui()
        
        # Connect signals
        self.setup_connections()
        
        # Internal state for averaging tracking
        self._target_averaging = 1
        self._actual_averaging = 1
    
    # ------------------------------------------------------------------------
    # UI CONFIGURATION
    # ------------------------------------------------------------------------
    
    def setup_ui(self):
        """Configure UI elements."""
        # FFT SIZE - locked during capture
        self.comboBox_fft_size.addItems([
            "256", "512", "1024", "2048", 
            "4096", "8192", "16384"
        ])
        self.comboBox_fft_size.setCurrentIndex(2)  # 1024 default
        
        # WINDOW TYPE - always enabled
        self.comboBox_window_type.addItems([
            "Rectangular", "Hann", "Hamming", 
            "Blackman", "Kaiser"
        ])
        self.comboBox_window_type.setCurrentIndex(1)  # Hann default
        
        # AVERAGING - always enabled
        self.horizontalSlider_averaging.setRange(1, 100)
        self.horizontalSlider_averaging.setValue(1)
        self.horizontalSlider_averaging.valueChanged.connect(
            lambda v: self.label_averaging_value.setText(f"{v}")
        )
        
        # OVERLAP - always enabled
        self.horizontalSlider_overlap.setRange(0, 95)
        self.horizontalSlider_overlap.setValue(50)
        self.horizontalSlider_overlap.valueChanged.connect(
            lambda v: self.label_overlap_value.setText(f"{v}%")
        )
        
        # Averaging status label (for real vs target)
        if hasattr(self, 'label_averaging_status'):
            self.label_averaging_status.setText("")
        else:
            # Create label if not present in UI
            from PyQt5.QtWidgets import QLabel
            self.label_averaging_status = QLabel()
            self.label_averaging_status.setStyleSheet("color: #888888; font-size: 8pt;")
            # Try to add to layout (assumes there's a layout with averaging controls)
            parent = self.horizontalSlider_averaging.parent()
            if parent and parent.layout():
                parent.layout().addWidget(self.label_averaging_status)
    
    def setup_connections(self):
        """Connect signals."""
        self.comboBox_fft_size.currentIndexChanged.connect(self.on_size_changed)
        self.comboBox_window_type.currentIndexChanged.connect(self.on_setting_changed)
        self.horizontalSlider_averaging.valueChanged.connect(self.on_setting_changed)
        self.horizontalSlider_overlap.valueChanged.connect(self.on_setting_changed)
    
    # ------------------------------------------------------------------------
    # PUBLIC METHODS - STATE CONTROL
    # ------------------------------------------------------------------------
    
    def set_controls_enabled(self, enabled: bool):
        """Enable/disable FFT size control visually."""
        self.comboBox_fft_size.setEnabled(enabled)
    
    def on_capture_started(self):
        """Called when capture starts."""
        self.is_running = True
        self.set_controls_enabled(False)
        self.logger.info("🔒 FFT size locked")
    
    def on_capture_stopped(self):
        """Called when capture stops."""
        self.is_running = False
        self.set_controls_enabled(True)
        self.logger.info("🔓 FFT size unlocked")
        
        # Apply pending FFT size change automatically
        if self.pending_fft_size:
            self.logger.info(f"✅ Applying pending FFT size: {self.pending_fft_size}")
            settings = {'fft_size': int(self.pending_fft_size)}
            self.settings_changed.emit(settings)
            self.pending_fft_size = None
    
    # ------------------------------------------------------------------------
    # PUBLIC METHODS - AVERAGING STATUS
    # ------------------------------------------------------------------------
    
    def update_averaging_real(self, actual: int, target: int):
        """
        Update the UI with real averaging value from FFT processor.
        
        Args:
            actual: Actual number of segments averaged
            target: Target number of segments
        """
        self._target_averaging = target
        self._actual_averaging = actual
        
        if actual < target:
            # Not enough data for full averaging
            self.label_averaging_status.setText(f"⚠️ Promediando {actual}/{target} segmentos")
            self.label_averaging_status.setStyleSheet("color: #ffaa00; font-size: 8pt;")
        else:
            self.label_averaging_status.setText(f"✅ {actual} segmentos promediados")
            self.label_averaging_status.setStyleSheet("color: #88ff88; font-size: 8pt;")
    
    def reset_averaging_status(self):
        """Reset averaging status display."""
        self.label_averaging_status.setText("")
    
    # ------------------------------------------------------------------------
    # PUBLIC METHODS - GETTERS
    # ------------------------------------------------------------------------
    
    def get_settings(self) -> dict:
        """Get current FFT settings."""
        return {
            'fft_size': int(self.comboBox_fft_size.currentText()),
            'window': self.comboBox_window_type.currentText(),
            'averaging': self.horizontalSlider_averaging.value(),
            'overlap': self.horizontalSlider_overlap.value()
        }
    
    def get_pending_size(self):
        """Return pending FFT size if any."""
        return self.pending_fft_size
    
    # ------------------------------------------------------------------------
    # PUBLIC METHODS - SETTERS
    # ------------------------------------------------------------------------
    
    def set_fft_size(self, size: int):
        """Set FFT size programmatically."""
        idx = self.comboBox_fft_size.findText(str(size))
        if idx >= 0:
            self.comboBox_fft_size.setCurrentIndex(idx)
    
    def set_window(self, window: str):
        """Set window type programmatically."""
        idx = self.comboBox_window_type.findText(window)
        if idx >= 0:
            self.comboBox_window_type.setCurrentIndex(idx)
    
    def set_averaging(self, averaging: int):
        """Set averaging value programmatically."""
        self.horizontalSlider_averaging.setValue(averaging)
    
    def set_overlap(self, overlap: int):
        """Set overlap value programmatically."""
        self.horizontalSlider_overlap.setValue(overlap)
    
    # ------------------------------------------------------------------------
    # SLOTS
    # ------------------------------------------------------------------------
    
    def on_size_changed(self):
        """Handle FFT size change - pending if capturing."""
        new_size = self.comboBox_fft_size.currentText()
        
        if self.is_running:
            self.pending_fft_size = new_size
            self.logger.info(f"⏳ FFT size pending: {new_size}")
        else:
            self.pending_fft_size = None
            settings = {'fft_size': int(new_size)}
            self.settings_changed.emit(settings)
    
    def on_setting_changed(self):
        """Handle window, averaging, overlap changes - always immediate."""
        settings = self.get_settings()
        if self.pending_fft_size:
            settings.pop('fft_size', None)
        if settings:
            self.settings_changed.emit(settings)
    
    def apply_settings(self):
        """Apply current settings manually."""
        settings = self.get_settings()
        self.settings_changed.emit(settings)
    
    def reset_settings(self):
        """Reset to default values."""
        self.comboBox_fft_size.setCurrentIndex(2)      # 1024
        self.comboBox_window_type.setCurrentIndex(1)   # Hann
        self.horizontalSlider_averaging.setValue(1)
        self.horizontalSlider_overlap.setValue(50)
        self.pending_fft_size = None
        self.apply_settings()
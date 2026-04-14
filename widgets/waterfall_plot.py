# -*- coding: utf-8 -*-

"""
Waterfall Plot Widget
=====================
Real-time waterfall display with persistence effect.

Features:
    - Rolling buffer of spectrum data
    - Persistence effect (exponential decay)
    - Configurable color mapping
    - Zoom/pan support
    - Frequency axis in MHz

CORRECTIONS APPLIED:
    - Persistence now works correctly with alpha blending
    - Smooth rolling buffer update
    - Proper frequency axis transformation
"""

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QObject, QTimer, pyqtSignal
import logging


# ============================================================================
# WATERFALL PLOT
# ============================================================================

class WaterfallPlot(QObject):
    """
    Waterfall display for spectrum data.
    
    The waterfall shows spectrum over time, with the most recent
    spectrum at the bottom and older data scrolling upward.
    
    Signals:
        updated: Emitted when waterfall data is updated
    """
    
    updated = pyqtSignal()
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # Configuration
        self.waterfall_height = 128
        self.fft_size = 1024
        self.waterfall_data = None
        self.freq_min_mhz = 0
        self.freq_max_mhz = 0
        self.min_display_db = -120
        self.max_display_db = 0
        self.update_counter = 0
        
        # State
        self.pending_update = False
        self.last_spectrum = None
        self.last_freq_axis = None
        self.last_center_freq = None
        self.last_sample_rate = None
        self.last_alpha = 1.0
        
        # Setup plot
        self.plot_widget = pg.PlotWidget(labels={
            'left': 'Time',
            'bottom': 'Frequency [MHz]',
        })
        
        self.imageitem = pg.ImageItem()
        self.plot_widget.addItem(self.imageitem)
        
        self.plot_widget.setMouseEnabled(x=True, y=False)
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.hideButtons()
        
        # Timer for deferred updates (30 fps)
        self.update_timer = QTimer()
        self.update_timer.setInterval(33)
        self.update_timer.timeout.connect(self._delayed_update)
        self.update_timer.start()
        
        # Initialize buffer
        self.reset_buffer()
        
        self.logger.info("✅ WaterfallPlot initialized")
    
    # ------------------------------------------------------------------------
    # BUFFER MANAGEMENT
    # ------------------------------------------------------------------------
    
    def reset_buffer(self) -> None:
        """Reset the waterfall buffer."""
        self.waterfall_data = np.full(
            (self.waterfall_height, self.fft_size),
            self.min_display_db,
            dtype=np.float32,
        )
        if self.imageitem is not None:
            self._update_image()
    
    def resize_buffer(self, new_fft_size: int) -> None:
        """
        Resize the waterfall buffer for new FFT size.
        
        Args:
            new_fft_size: New FFT size in bins
        """
        if new_fft_size == self.fft_size:
            return
        
        self.logger.info(f"Resizing buffer: {self.fft_size} -> {new_fft_size}")
        self.fft_size = new_fft_size
        self.waterfall_data = np.full(
            (self.waterfall_height, self.fft_size),
            self.min_display_db,
            dtype=np.float32,
        )
        self._update_transform()
        self._update_image()
    
    def set_display_range(self, min_db: float, max_db: float) -> None:
        """
        Set the display range (color mapping).
        
        Args:
            min_db: Minimum value (noise floor)
            max_db: Maximum value (peak)
        """
        self.min_display_db = min_db
        self.max_display_db = max_db
        if self.imageitem is not None:
            self.imageitem.setLevels([min_db, max_db])
            self._update_image()
    
    def clear(self) -> None:
        """Clear the waterfall buffer."""
        if self.waterfall_data is not None:
            self.waterfall_data.fill(self.min_display_db)
            self._update_image()
            self.logger.debug("💧 Waterfall cleared")
    
    def get_plot_widget(self) -> pg.PlotWidget:
        """Return the plot widget for embedding."""
        return self.plot_widget
    
    def get_image_item(self) -> pg.ImageItem:
        """Return the image item for colorbar connection."""
        return self.imageitem
    
    # ------------------------------------------------------------------------
    # DATA UPDATE
    # ------------------------------------------------------------------------
    
    def update_spectrum(self, spectrum: np.ndarray, freq_axis_mhz: np.ndarray,
                        center_freq_mhz: float, sample_rate_mhz: float,
                        alpha: float = 1.0) -> None:
        """
        Update waterfall with new spectrum.
        
        Args:
            spectrum: Power spectrum array (dB)
            freq_axis_mhz: Frequency axis in MHz
            center_freq_mhz: Center frequency in MHz
            sample_rate_mhz: Sample rate in MHz
            alpha: Persistence factor (1.0 = no persistence, <1.0 = decay)
        """
        self.last_spectrum = spectrum
        self.last_freq_axis = freq_axis_mhz
        self.last_center_freq = center_freq_mhz
        self.last_sample_rate = sample_rate_mhz
        self.last_alpha = float(np.clip(alpha, 0.01, 1.0))
        self.pending_update = True
    
    def _delayed_update(self) -> None:
        """
        Deferred update with throttling.
        
        CORRECTION: Persistence now correctly blends new spectrum with
        the previous row when alpha < 1.0, creating a trailing effect.
        """
        if not self.pending_update or self.last_spectrum is None:
            return
        
        try:
            spectrum = self.last_spectrum
            center_freq = self.last_center_freq
            sample_rate = self.last_sample_rate
            alpha = self.last_alpha
            
            # Adapt buffer size if FFT size changed
            if len(spectrum) != self.fft_size:
                self.fft_size = len(spectrum)
                self.reset_buffer()
            
            # Update frequency range and transform
            self.freq_min_mhz = center_freq - sample_rate / 2
            self.freq_max_mhz = center_freq + sample_rate / 2
            self._update_transform()
            
            # Roll the buffer (move all rows up)
            self.waterfall_data = np.roll(self.waterfall_data, -1, axis=0)
            
            # Write new row with persistence
            if alpha >= 1.0:
                # No persistence: pure new data
                self.waterfall_data[-1, :] = spectrum
            else:
                # With persistence: blend new data with previous row
                # alpha = 0.5 → 50% new + 50% previous → moderate trail
                # alpha = 0.01 → 1% new + 99% previous → long trail
                self.waterfall_data[-1, :] = (
                    alpha * spectrum
                    + (1.0 - alpha) * self.waterfall_data[-2, :]
                )
            
            self._update_image()
            self.pending_update = False
            
        except Exception as e:
            self.logger.error(f"Error in deferred update: {e}")
            self.pending_update = False
    
    def _update_image(self) -> None:
        """Update the image display."""
        if self.waterfall_data is not None and self.imageitem is not None:
            # Transpose for correct orientation (time vertical, frequency horizontal)
            self.imageitem.setImage(self.waterfall_data.T, autoLevels=False)
            self.imageitem.setLevels([self.min_display_db, self.max_display_db])
            self.update_counter += 1
            self.updated.emit()
    
    def _update_transform(self) -> None:
        """Update the coordinate transform for frequency axis."""
        if self.fft_size > 1 and self.imageitem is not None:
            freq_width = self.freq_max_mhz - self.freq_min_mhz
            self.imageitem.setRect(
                self.freq_min_mhz, 0, freq_width, self.waterfall_height
            )
            self.plot_widget.setXRange(self.freq_min_mhz, self.freq_max_mhz)
            self.plot_widget.setYRange(0, self.waterfall_height)
    
    # ------------------------------------------------------------------------
    # COMPATIBILITY METHOD
    # ------------------------------------------------------------------------
    
    def set_colormap(self, colormap_name: str) -> None:
        """
        Set color map (compatibility method).
        
        Color map is now managed by VisualizationWidget.
        """
        pass
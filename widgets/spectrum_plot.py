# -*- coding: utf-8 -*-

"""
Spectrum Plot Widget with Interactive Marker
=============================================
Professional spectrum visualization with interactive frequency marker,
max/min hold curves, and band plan display.

Features:
    - Interactive frequency marker with drag-and-drop
    - Max hold and min hold curves
    - Dynamic background adaptation based on curve colors
    - Band plan display with colored regions and labels
    - Threshold and noise floor lines for detector
    - Real-time power readout at marker position

CORRECTIONS APPLIED:
    1. Fixed marker drag handling with ghost line for visual feedback
    2. Proper color adaptation for visibility on dark backgrounds
    3. Band plan regions drawn at bottom of plot (not overlapping spectrum)
    4. Smart label positioning to avoid collisions
"""

import pyqtgraph as pg
import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QGraphicsRectItem
from PyQt5.QtCore import QRectF


# ============================================================================
# FREQUENCY MARKER (INTERACTIVE)
# ============================================================================

class FrequencyMarker(QObject):
    """
    Interactive frequency marker for spectrum plot.
    
    Features:
        - Draggable vertical line
        - Hover effects
        - Ghost line during drag
        - Power readout label
    """
    
    frequencyChanged = pyqtSignal(float)
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, frequency: float, logger=None):
        super().__init__()
        self.frequency = frequency
        self.logger = logger
        
        # Graphics items
        self.line = None
        self.power_label = None
        self.marker_point = None
        self.ghost_line = None
        
        # Drag state
        self.dragging = False
        self.drag_start_pos = None
        
        # Colors
        self.normal_color = '#FF0000'
        self.hover_color = '#FFA500'
        self.drag_color = '#FFFF00'
    
    # ------------------------------------------------------------------------
    # GRAPHICS SETUP
    # ------------------------------------------------------------------------
    
    def add_to_plot(self, plot) -> None:
        """
        Add marker elements to the plot.
        
        Args:
            plot: pyqtgraph PlotWidget
        """
        # Main vertical line
        self.line = pg.InfiniteLine(
            pos=self.frequency,
            angle=90,
            movable=True,
            pen=pg.mkPen(self.normal_color, width=2),
            hoverPen=pg.mkPen(self.hover_color, width=3),
            bounds=None
        )
        
        # Ghost line (shown during drag)
        self.ghost_line = pg.InfiniteLine(
            pos=self.frequency,
            angle=90,
            movable=False,
            pen=pg.mkPen('#888888', width=1, style=Qt.DashLine),
            hoverPen=None
        )
        self.ghost_line.setVisible(False)
        
        # Interactive point at bottom
        self.marker_point = pg.ScatterPlotItem(
            pos=[(self.frequency, -5)],
            size=8,
            pen=pg.mkPen(self.normal_color, width=1),
            brush=pg.mkBrush(self.normal_color),
            hoverable=True,
            hoverPen=pg.mkPen(self.hover_color, width=2),
            hoverBrush=pg.mkBrush(self.hover_color),
            hoverSize=12
        )
        
        # Power readout label
        self.power_label = pg.TextItem(
            text="",
            color=(255, 255, 255),
            anchor=(0.5, 1),
            border=pg.mkPen(0, 0, 0, 200),
            fill=pg.mkBrush(0, 0, 0, 180)
        )
        
        # Add all items
        plot.addItem(self.line)
        plot.addItem(self.ghost_line)
        plot.addItem(self.marker_point)
        plot.addItem(self.power_label)
        
        self._update_label_position()
    
    def connect_signals(self, callback) -> None:
        """
        Connect drag signals to callback.
        
        Args:
            callback: Function called when marker is released
        """
        if self.line:
            self.line.sigDragged.connect(self._on_drag_move)
            self.line.sigPositionChangeFinished.connect(
                lambda: self._on_drag_finished(callback)
            )
    
    def connect_point_click(self, callback) -> None:
        """
        Connect double-click on marker point.
        
        Args:
            callback: Function called on double-click
        """
        if self.marker_point:
            self.marker_point.sigClicked.connect(callback)
    
    # ------------------------------------------------------------------------
    # PUBLIC METHODS
    # ------------------------------------------------------------------------
    
    def set_frequency(self, frequency: float) -> None:
        """
        Update marker position.
        
        Args:
            frequency: New frequency in MHz
        """
        self.frequency = frequency
        if self.line and not self.dragging:
            self.line.setValue(frequency)
            self._update_marker_position()
            self._update_label_position()
    
    def set_power(self, power_dbm: float) -> None:
        """
        Update power readout label.
        
        Args:
            power_dbm: Power in dBm (or dBFS)
        """
        if self.power_label and power_dbm is not None:
            # Color coding by power level
            if power_dbm > -50:
                color = "#00FF00"  # Green (strong)
            elif power_dbm > -80:
                color = "#FFFF00"  # Yellow (medium)
            else:
                color = "#FF0000"  # Red (weak)
            
            self.power_label.setHtml(
                f'<span style="color: {color}; font-weight: bold;">'
                f'{power_dbm:.1f} dB</span>'
            )
        elif self.power_label:
            self.power_label.setText("")
    
    # ------------------------------------------------------------------------
    # PRIVATE METHODS
    # ------------------------------------------------------------------------
    
    def _update_marker_position(self) -> None:
        """Update marker point position."""
        if self.marker_point:
            self.marker_point.setData(pos=[(self.frequency, -5)])
    
    def _update_label_position(self) -> None:
        """Update power label position."""
        if self.power_label and self.line:
            self.power_label.setPos(self.frequency, -15)
    
    def _on_drag_move(self, line) -> None:
        """Handle drag movement."""
        if not self.dragging:
            self.dragging = True
            self.drag_start_pos = line.value()
            
            if self.ghost_line:
                self.ghost_line.setValue(line.value())
                self.ghost_line.setVisible(True)
            
            if self.line:
                self.line.setPen(pg.mkPen(self.drag_color, width=2, style=Qt.DashLine))
        else:
            if self.ghost_line:
                self.ghost_line.setValue(line.value())
    
    def _on_drag_finished(self, callback) -> None:
        """Handle drag completion."""
        if not self.dragging:
            return
        
        self.dragging = False
        new_freq = self.line.value()
        
        if self.ghost_line:
            self.ghost_line.setVisible(False)
        
        if self.line:
            self.line.setPen(pg.mkPen(self.normal_color, width=2))
        
        self.frequency = new_freq
        self._update_marker_position()
        self._update_label_position()
        
        callback(new_freq)
        
        if self.logger:
            self.logger.info(f"🎯 Frequency changed to: {new_freq:.3f} MHz")
        
        self.drag_start_pos = None


# ============================================================================
# SPECTRUM PLOT WIDGET
# ============================================================================

class SpectrumPlot(QObject):
    """
    Professional spectrum plot with interactive features.
    
    Signals:
        frequencyChanged: Emitted when marker is moved
    """
    
    frequencyChanged = pyqtSignal(float)
    
    # ------------------------------------------------------------------------
    # CONSTANTS
    # ------------------------------------------------------------------------
    BACKGROUND_DARK = QColor(25, 25, 25)
    BACKGROUND_LIGHT = QColor(240, 240, 240)
    BACKGROUND_MEDIUM = QColor(53, 53, 53)
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, main_window, logger):
        """
        Initialize spectrum plot.
        
        Args:
            main_window: Parent window (for frequency access)
            logger: Logger instance
        """
        super().__init__()
        self.main_window = main_window
        self.logger = logger
        
        # Graphics elements
        self.plot_widget = None
        self.curve = None
        self.max_curve = None
        self.min_curve = None
        self.freq_marker = None
        self.info_text = None
        self.grid = None
        self.viewbox = None

        self.baseline_curve = None
        
        # Data
        self.current_spectrum = None
        self.current_frequencies = None
        
        # State
        self.updating_from_marker = False
        self.max_hold_enabled = False
        self.min_hold_enabled = False
        self.max_hold_data = None
        self.min_hold_data = None
        
        # Detector lines
        self.threshold_line = None
        self.noise_line = None
        self.threshold_visible = True
        self.noise_visible = True
        
        # Band plan
        from utils.band_plan import BandPlan
        self.band_plan = BandPlan()
        self.show_band_plan = False
        self.band_regions = []
        
        # Current background
        self.current_bg_color = self.BACKGROUND_DARK
        
        # Setup plot
        self.setup_plot()
        self.setup_detector_lines()
        
        self.logger.info(f"✅ SpectrumPlot initialized with {len(self.band_plan.get_all_bands())} bands")
    
    # ------------------------------------------------------------------------
    # PLOT SETUP
    # ------------------------------------------------------------------------
    
    def setup_plot(self) -> None:
        """Configure the plot widget."""
        self.plot_widget = pg.PlotWidget(labels={
            'left': 'PSD [dB]',
            'bottom': 'Frequency [MHz]'
        })
        
        # Disable mouse interactions (handled by marker)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.hideButtons()
        
        # Fixed Y range
        self.plot_widget.setYRange(-120, 20)
        
        # Grid
        self.grid = self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # ViewBox reference for background
        self.viewbox = self.plot_widget.getViewBox()
        
        # Main spectrum curve
        self.curve = self.plot_widget.plot(
            [],
            pen=pg.mkPen(color=(0, 255, 255), width=1)
        )
        
        # Max hold curve
        self.max_curve = self.plot_widget.plot(
            [],
            pen=pg.mkPen(color=(0, 255, 0), width=2, style=Qt.SolidLine),
            name="Max Hold"
        )
        self.max_curve.setVisible(False)
        
        # Min hold curve
        self.min_curve = self.plot_widget.plot(
            [],
            pen=pg.mkPen(color=(0, 0, 255), width=2, style=Qt.SolidLine),
            name="Min Hold"
        )
        self.min_curve.setVisible(False)
        
        # Info text
        self.info_text = pg.TextItem(
            text="",
            color=(255, 255, 255),
            anchor=(0, 0),
            border=pg.mkPen(0, 0, 0, 150),
            fill=pg.mkBrush(0, 0, 0, 180)
        )
        self.plot_widget.addItem(self.info_text)
        self.info_text.setPos(10, 10)
        
        # Frequency marker
        initial_freq = self._get_initial_frequency()
        self.freq_marker = FrequencyMarker(initial_freq, self.logger)
        self.freq_marker.add_to_plot(self.plot_widget)
        self.freq_marker.connect_signals(self._on_marker_released)
        self.freq_marker.connect_point_click(self._on_point_clicked)
        
        # Mouse click handler
        self.plot_widget.scene().sigMouseClicked.connect(self._on_spectrum_click)
        
        # Range change handler (for band plan)
        self.plot_widget.sigRangeChanged.connect(self._on_range_changed)
        
        # Set initial background
        self.set_background_color(self.BACKGROUND_DARK)

        # Curva para Baseline (TSCM)
        self.baseline_curve = self.plot_widget.plot(
            [], 
            pen=pg.mkPen(color=(128, 128, 128, 150), width=1.5, style=Qt.DashLine),
            name="Baseline"
        )
        self.baseline_curve.setVisible(False)
    
    def setup_detector_lines(self) -> None:
        """Create threshold and noise floor lines."""
        try:
            # Threshold line (red dashed)
            self.threshold_line = pg.InfiniteLine(
                angle=0,
                pen=pg.mkPen('#FF4444', width=1, style=Qt.DashLine),
                movable=False,
                label="Threshold",
                labelOpts={'color': '#FF4444', 'position': 0.05}
            )
            self.plot_widget.addItem(self.threshold_line)
            self.threshold_line.setVisible(True)
            self.threshold_line.setValue(-80)
            
            # Noise floor line (gray dotted)
            self.noise_line = pg.InfiniteLine(
                angle=0,
                pen=pg.mkPen('#888888', width=1, style=Qt.DotLine),
                movable=False,
                label="Noise Floor",
                labelOpts={'color': '#888888', 'position': 0.1}
            )
            self.plot_widget.addItem(self.noise_line)
            self.noise_line.setVisible(True)
            self.noise_line.setValue(-95)
            
            self.logger.info("📊 Detector lines created")
            
        except Exception as e:
            self.logger.error(f"Error creating detector lines: {e}")
    
    # ------------------------------------------------------------------------
    # BACKGROUND MANAGEMENT
    # ------------------------------------------------------------------------
    
    def set_background_color(self, color) -> None:
        """
        Set plot background color.
        
        Args:
            color: QColor or hex string
        """
        if isinstance(color, str):
            color = QColor(color)
        
        self.current_bg_color = color
        self.viewbox.setBackgroundColor(color)
        self._recreate_info_text(color)
        self._adjust_grid_color(color)
    
    def _recreate_info_text(self, bg_color: QColor) -> None:
        """Recreate info text with appropriate colors."""
        luminance = (0.299 * bg_color.red() + 
                     0.587 * bg_color.green() + 
                     0.114 * bg_color.blue()) / 255
        
        current_pos = self.info_text.pos() if self.info_text else (10, 10)
        current_text = self.info_text.toPlainText() if self.info_text else ""
        
        if self.info_text in self.plot_widget.items():
            self.plot_widget.removeItem(self.info_text)
        
        if luminance > 0.5:  # Light background
            self.info_text = pg.TextItem(
                text=current_text,
                color=(0, 0, 0),
                anchor=(0, 0),
                border=pg.mkPen(0, 0, 0, 150),
                fill=pg.mkBrush(255, 255, 255, 200)
            )
        else:  # Dark background
            self.info_text = pg.TextItem(
                text=current_text,
                color=(255, 255, 255),
                anchor=(0, 0),
                border=pg.mkPen(255, 255, 255, 150),
                fill=pg.mkBrush(0, 0, 0, 200)
            )
        
        self.plot_widget.addItem(self.info_text)
        self.info_text.setPos(current_pos)
    
    def _adjust_grid_color(self, bg_color: QColor) -> None:
        """Adjust grid color based on background."""
        luminance = (0.299 * bg_color.red() + 
                     0.587 * bg_color.green() + 
                     0.114 * bg_color.blue()) / 255
        
        alpha = 100 if luminance > 0.5 else 70
        self.plot_widget.showGrid(x=True, y=True, alpha=alpha / 255)
    
    # ------------------------------------------------------------------------
    # CURVE COLOR MANAGEMENT
    # ------------------------------------------------------------------------
    
    def set_curve_colors(self, active_color=None, max_color=None, min_color=None) -> None:
        """
        Set colors for spectrum curves.
        
        Colors are adjusted for visibility on dark background.
        """
        self.logger.info("=" * 70)
        self.logger.info("🎨 SET_CURVE_COLORS()")
        self.logger.info(f"   Original: active={active_color}, max={max_color}, min={min_color}")
        
        # Ensure visibility on dark background
        bg_color = QColor(25, 25, 25)
        
        if active_color:
            active_color = self._ensure_visibility(active_color, bg_color)
        if max_color:
            max_color = self._ensure_visibility(max_color, bg_color)
        if min_color:
            min_color = self._ensure_visibility(min_color, bg_color)
        
        # Defaults
        active_to_use = active_color if active_color else '#00FFFF'
        max_to_use = max_color if max_color else '#FFFF00'
        min_to_use = min_color if min_color else '#FF8000'
        
        # Apply
        if self.curve:
            self.curve.setPen(pg.mkPen(color=active_to_use, width=1))
            self.logger.info(f"   Active curve → {active_to_use}")
        
        if self.max_curve:
            self.max_curve.setPen(pg.mkPen(color=max_to_use, width=1))
            self.max_curve.setVisible(self.max_hold_enabled)
            self.logger.info(f"   Max curve → {max_to_use}")
        
        if self.min_curve:
            self.min_curve.setPen(pg.mkPen(color=min_to_use, width=1))
            self.min_curve.setVisible(self.min_hold_enabled)
            self.logger.info(f"   Min curve → {min_to_use}")
        
        # Fixed dark background
        self.viewbox.setBackgroundColor(bg_color)
        
        # Force update
        if self.plot_widget:
            self.plot_widget.repaint()
        
        self.logger.info("=" * 70)
    
    def _ensure_visibility(self, color_hex: str, bg_color: QColor) -> str:
        """
        Ensure color is visible on background.
        
        For very dark colors, brighten them.
        """
        if not color_hex or not color_hex.startswith('#'):
            return color_hex
        
        # Special case: pure black
        if color_hex.lower() == '#000000':
            return '#FFFFFF'
        
        # Check luminance
        r = int(color_hex[1:3], 16)
        g = int(color_hex[3:5], 16)
        b = int(color_hex[5:7], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        
        if luminance < 0.15:  # Too dark
            # Brighten by factor 2.5
            r = min(255, int(r * 2.5))
            g = min(255, int(g * 2.5))
            b = min(255, int(b * 2.5))
            adjusted = QColor(r, g, b)
            self.logger.debug(f"   Brightened {color_hex} → {adjusted.name()}")
            return adjusted.name()
        
        return color_hex
    
    # ------------------------------------------------------------------------
    # DATA UPDATE
    # ------------------------------------------------------------------------
    
    def update_plot(self, spectrum, frequencies, max_hold=None, min_hold=None) -> None:
        """
        Update plot with new spectrum data.
        
        Args:
            spectrum: Power spectrum array (dB)
            frequencies: Frequency axis (MHz)
            max_hold: Max hold data (optional)
            min_hold: Min hold data (optional)
        """
        try:
            if spectrum is not None and frequencies is not None:
                self.current_spectrum = spectrum
                self.current_frequencies = frequencies
                
                # Main curve
                self.curve.setData(frequencies, spectrum)
                
                # Hold curves
                if self.max_hold_enabled and max_hold is not None:
                    self.max_curve.setData(frequencies, max_hold)
                
                if self.min_hold_enabled and min_hold is not None:
                    self.min_curve.setData(frequencies, min_hold)
                
                # Update marker power
                if not self.freq_marker.dragging:
                    center_freq = self._get_initial_frequency()
                    self.freq_marker.set_frequency(center_freq)
                    power = self._get_power_at_frequency(center_freq)
                    self.freq_marker.set_power(power)
                    
        except Exception as e:
            self.logger.error(f"Error updating spectrum plot: {e}")
    
    def _get_power_at_frequency(self, freq_mhz: float) -> float:
        """Get power at specified frequency."""
        try:
            if self.current_spectrum is None or self.current_frequencies is None:
                return None
            
            idx = np.argmin(np.abs(self.current_frequencies - freq_mhz))
            if idx < len(self.current_spectrum):
                return self.current_spectrum[idx]
            return None
        except Exception:
            return None
    
    def _get_initial_frequency(self) -> float:
        """Get initial frequency from UI."""
        if hasattr(self.main_window, 'doubleSpinBox_freq'):
            return self.main_window.doubleSpinBox_freq.value()
        elif hasattr(self.main_window, 'frequency_spinner'):
            return self.main_window.frequency_spinner.frequency_mhz
        return 100.0
    
    def update_plot_with_baseline(self, spectrum, frequencies, max_hold=None, min_hold=None, baseline=None):
        """Actualiza el plot con soporte para baseline."""
        # Actualizar curva principal
        self.curve.setData(frequencies, spectrum)
        
        # Actualizar Max/Min
        if self.max_hold_enabled and max_hold is not None:
            self.max_curve.setData(frequencies, max_hold)
            self.max_curve.setVisible(True)
        else:
            self.max_curve.setVisible(False)
            
        if self.min_hold_enabled and min_hold is not None:
            self.min_curve.setData(frequencies, min_hold)
            self.min_curve.setVisible(True)
        else:
            self.min_curve.setVisible(False)
        
        # Actualizar Baseline
        if baseline is not None and len(baseline) == len(frequencies):
            if not hasattr(self, 'baseline_curve') or self.baseline_curve is None:
                self.baseline_curve = self.plot_widget.plot(
                    [], 
                    pen=pg.mkPen(color=(128, 128, 128, 180), width=1.5, style=Qt.DashLine),
                    name="Baseline"
                )
            self.baseline_curve.setData(frequencies, baseline)
            self.baseline_curve.setVisible(True)
        elif hasattr(self, 'baseline_curve') and self.baseline_curve is not None:
            self.baseline_curve.setVisible(False)
        
        # Actualizar marcador
        if not self.freq_marker.dragging:
            center_freq = self._get_initial_frequency()
            self.freq_marker.set_frequency(center_freq)
            power = self._get_power_at_frequency(center_freq)
            self.freq_marker.set_power(power)


    
    # ------------------------------------------------------------------------
    # HOLD CURVES
    # ------------------------------------------------------------------------
    
    def enable_max_hold(self, enabled: bool) -> None:
        """Enable/disable max hold curve."""
        self.max_hold_enabled = enabled
        self.max_curve.setVisible(enabled)
        if not enabled:
            self.max_hold_data = None
    
    def enable_min_hold(self, enabled: bool) -> None:
        """Enable/disable min hold curve."""
        self.min_hold_enabled = enabled
        self.min_curve.setVisible(enabled)
        if not enabled:
            self.min_hold_data = None
    
    def clear_hold(self) -> None:
        """Clear hold data."""
        self.max_hold_data = None
        self.min_hold_data = None
        self.max_curve.setData([], [])
        self.min_curve.setData([], [])
        self.logger.info("Hold cleared")
    
    # ------------------------------------------------------------------------
    # FREQUENCY CONTROL
    # ------------------------------------------------------------------------
    
    def set_frequency(self, freq_mhz: float) -> None:
        """Set frequency from external controls."""
        try:
            if not self.freq_marker.dragging and not self.updating_from_marker:
                self.freq_marker.set_frequency(freq_mhz)
                power = self._get_power_at_frequency(freq_mhz)
                self.freq_marker.set_power(power)
        except Exception as e:
            self.logger.error(f"Error setting frequency: {e}")
    
    def update_info_text(self, text: str) -> None:
        """Update info text."""
        try:
            if self.info_text:
                self.info_text.setText(text)
        except Exception as e:
            self.logger.error(f"Error updating info text: {e}")
    
    # ------------------------------------------------------------------------
    # DETECTOR LINES
    # ------------------------------------------------------------------------
    
    def set_threshold_visible(self, visible: bool) -> None:
        """Show/hide threshold line."""
        self.threshold_visible = visible
        if self.threshold_line:
            self.threshold_line.setVisible(visible)
    
    def set_noise_visible(self, visible: bool) -> None:
        """Show/hide noise floor line."""
        self.noise_visible = visible
        if self.noise_line:
            self.noise_line.setVisible(visible)
    
    def update_threshold(self, threshold_db: float) -> None:
        """Update threshold line value."""
        if self.threshold_line:
            self.threshold_line.setValue(threshold_db)
            self.threshold_line.label.setText(f"Threshold: {threshold_db:.1f} dB")
    
    def update_noise(self, noise_db: float) -> None:
        """Update noise floor line value."""
        if self.noise_line:
            self.noise_line.setValue(noise_db)
            self.noise_line.label.setText(f"Noise: {noise_db:.1f} dB")
    
    # ------------------------------------------------------------------------
    # BAND PLAN
    # ------------------------------------------------------------------------
    
    def set_band_plan_visible(self, visible: bool) -> None:
        """Show/hide band plan regions."""
        self.show_band_plan = visible
        
        if visible:
            self._draw_band_regions()
        else:
            self._clear_band_regions()
    
    def _draw_band_regions(self) -> None:
        """Draw band regions at bottom of plot."""
        self._clear_band_regions()
        
        if not self.plot_widget:
            return
        
        try:
            # Get visible X range
            x_range = self.plot_widget.getViewBox().viewRange()[0]
            start_mhz = x_range[0]
            end_mhz = x_range[1]
            
            # Get bands in range
            bands = self.band_plan.get_bands_in_range(start_mhz, end_mhz)
            
            if not bands:
                return
            
            # Get Y range for bar positioning
            y_range = self.plot_widget.getViewBox().viewRange()[1]
            y_min = y_range[0]
            y_max = y_range[1]
            
            # Bar height (3.5% of total height)
            bar_height = (y_max - y_min) * 0.035
            bar_y_top = y_min + 2
            bar_y_bottom = bar_y_top + bar_height
            
            # Draw bars and collect label positions
            used_positions = []
            
            # Sort by width (wider first for label priority)
            bands_sorted = sorted(bands, key=lambda b: (b['end_mhz'] - b['start_mhz']), reverse=True)
            
            for band in bands_sorted:
                band_start = max(band['start_mhz'], start_mhz)
                band_end = min(band['end_mhz'], end_mhz)
                band_width = band_end - band_start
                
                if band_start >= band_end:
                    continue
                
                # Draw bar
                color = self.band_plan.get_band_color(band, alpha=220)
                border_color = self.band_plan.get_band_color(band, alpha=255)
                
                bar_rect = QGraphicsRectItem()
                bar_rect.setRect(QRectF(band_start, bar_y_top, 
                                        band_end - band_start, bar_height))
                bar_rect.setBrush(color)
                bar_rect.setPen(pg.mkPen(color=border_color, width=1))
                bar_rect.setZValue(-5)
                
                self.plot_widget.addItem(bar_rect)
                self.band_regions.append(bar_rect)
                
                # Add label if band is wide enough
                if band_width >= 1.5:
                    display_name = band.get('display', band.get('name', ''))
                    
                    # Shorten if too long
                    max_chars = max(4, int(band_width / 2.5))
                    if len(display_name) > max_chars:
                        display_name = display_name[:max_chars-2] + ".."
                    
                    # Calculate label position
                    candidate_pos = (band_start + band_end) / 2
                    
                    # Check collision
                    collision = False
                    for used_pos, used_width in used_positions:
                        distance = abs(candidate_pos - used_pos)
                        min_distance = (band_width + used_width) / 2.5
                        if distance < min_distance:
                            collision = True
                            break
                    
                    if collision:
                        # Try left side
                        left_pos = band_start + band_width * 0.25
                        left_collision = False
                        for used_pos, used_width in used_positions:
                            if abs(left_pos - used_pos) < (band_width + used_width) / 3:
                                left_collision = True
                                break
                        
                        if not left_collision and left_pos > band_start + 0.5:
                            final_pos = left_pos
                        else:
                            # Try right side
                            right_pos = band_end - band_width * 0.25
                            right_collision = False
                            for used_pos, used_width in used_positions:
                                if abs(right_pos - used_pos) < (band_width + used_width) / 3:
                                    right_collision = True
                                    break
                            
                            if not right_collision and right_pos < band_end - 0.5:
                                final_pos = right_pos
                            else:
                                continue
                    else:
                        final_pos = candidate_pos
                    
                    # Register position
                    used_positions.append((final_pos, band_width))
                    
                    # Create label
                    label = pg.TextItem(
                        text=display_name,
                        color=(255, 255, 255, 255),
                        anchor=(0.5, 0.5)
                    )
                    label.setPos(final_pos, bar_y_top + bar_height / 2)
                    label.setZValue(-4)
                    
                    # Add tooltip
                    tooltip = f"<b>{band.get('display', band.get('name', ''))}</b><br>"
                    tooltip += f"{band['start_mhz']:.1f} - {band['end_mhz']:.1f} MHz<br>"
                    if band.get('description'):
                        tooltip += f"{band.get('description')}<br>"
                    if band.get('type'):
                        tooltip += f"Type: {band.get('type')}"
                    label.setToolTip(tooltip)
                    
                    self.plot_widget.addItem(label)
                    self.band_regions.append(label)
            
            # Add divider line
            if bands:
                divider_line = pg.InfiniteLine(
                    pos=bar_y_top + bar_height,
                    angle=0,
                    pen=pg.mkPen('#666666', width=1, style=Qt.DashLine),
                    movable=False
                )
                divider_line.setZValue(-3)
                self.plot_widget.addItem(divider_line)
                self.band_regions.append(divider_line)
            
            self.logger.debug(f"📡 {len(bands)} bands drawn")
            
        except Exception as e:
            self.logger.error(f"Error drawing band regions: {e}")
            import traceback
            traceback.print_exc()
    
    def _clear_band_regions(self) -> None:
        """Clear all band region items."""
        for item in self.band_regions:
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self.band_regions.clear()
    
    def update_band_regions(self) -> None:
        """Update band regions (called on zoom/pan)."""
        if self.show_band_plan:
            self._draw_band_regions()
    
    # ------------------------------------------------------------------------
    # EVENT HANDLERS
    # ------------------------------------------------------------------------
    
    def _on_marker_released(self, new_freq: float) -> None:
        """Handle marker release."""
        try:
            if self.updating_from_marker:
                return
            
            self.updating_from_marker = True
            self.logger.info(f"🎯 Marker moved to: {new_freq:.3f} MHz")
            
            self.frequencyChanged.emit(new_freq)
            
            power = self._get_power_at_frequency(new_freq)
            self.freq_marker.set_power(power)
            
            self.updating_from_marker = False
            
        except Exception as e:
            self.updating_from_marker = False
            self.logger.error(f"Error in marker handler: {e}")
    
    def _on_point_clicked(self, plot, points, event) -> None:
        """Handle double-click on marker point."""
        if event.double():
            point = points[0]
            new_freq = point.pos().x()
            self.logger.info(f"🎯 Centering on {new_freq:.3f} MHz")
            self.frequencyChanged.emit(new_freq)
            power = self._get_power_at_frequency(new_freq)
            self.freq_marker.set_power(power)
            event.accept()
    
    def _on_spectrum_click(self, event) -> None:
        """Handle double-click on spectrum."""
        if event.double():
            pos = self.plot_widget.plotItem.vb.mapSceneToView(event.scenePos())
            freq_mhz = pos.x()
            self.logger.info(f"🎯 Centering on {freq_mhz:.3f} MHz")
            self.frequencyChanged.emit(freq_mhz)
            power = self._get_power_at_frequency(freq_mhz)
            self.freq_marker.set_power(power)
    
    def _on_range_changed(self, viewbox, range) -> None:
        """Handle zoom/pan range change."""
        if self.show_band_plan:
            self.update_band_regions()
# -*- coding: utf-8 -*-

"""
Frequency Controller - Widget Synchronization
==============================================
Manages frequency changes with debounce and synchronizes all frequency widgets.

This controller ensures that:
    - Frequency changes from any widget (spinner, doubleSpinBox, plot marker)
      are propagated to all other widgets
    - Debounce prevents rapid hardware updates during spinner scrolling
    - Fast frequency change uses SDRDevice.set_frequency() when possible
"""

import logging
from PyQt5.QtCore import QTimer


# ============================================================================
# FREQUENCY CONTROLLER
# ============================================================================

class FrequencyController:
    """
    Controls frequency and synchronizes all frequency widgets.
    
    Uses debounce to prevent excessive hardware updates during fast spinner scrolling.
    """
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, main_controller):
        """
        Initialize frequency controller.
        
        Args:
            main_controller: Reference to main controller
        """
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.FrequencyController")
        
        # Debounce variables
        self.pending_frequency = None
        self.frequency_timer = None
        
        self._setup_timer()
    
    def _setup_timer(self) -> None:
        """Setup debounce timer."""
        self.frequency_timer = QTimer()
        self.frequency_timer.setSingleShot(True)
        self.frequency_timer.setInterval(300)  # 300ms debounce
        self.frequency_timer.timeout.connect(self._apply_frequency_change)
    
    # ------------------------------------------------------------------------
    # FREQUENCY CHANGE HANDLERS
    # ------------------------------------------------------------------------
    
    def on_frequency_spinner_changed(self, freq_mhz: float) -> None:
        """
        Handle frequency change from spinner (with debounce).
        
        Args:
            freq_mhz: New frequency in MHz
        """
        try:
            self.logger.info(f"🎯 Spinner changed to: {freq_mhz:.3f} MHz (debounce)")
            
            # Update UI immediately
            self._update_frequency_ui(freq_mhz)
            
            # Store pending and start debounce timer
            self.pending_frequency = freq_mhz
            self.frequency_timer.start()
            
        except Exception as e:
            self.logger.error(f"Error in on_frequency_spinner_changed: {e}")
    
    def on_frequency_changed_from_plot(self, freq_mhz: float) -> None:
        """
        Handle frequency change from plot marker.
        
        Args:
            freq_mhz: New frequency in MHz
        """
        try:
            self.logger.info(f"🎯 Plot marker moved to: {freq_mhz:.3f} MHz")
            
            # Sync all widgets
            self.sync_frequency_widgets(freq_mhz)
            
            # Update plot range
            self.main._update_plot_range(freq_mhz)
            
            # Apply to SDR if running
            if self.main.is_running and self.main.bladerf:
                self.pending_frequency = freq_mhz
                self.frequency_timer.start()
            
        except Exception as e:
            self.logger.error(f"Error in on_frequency_changed_from_plot: {e}")
    
    def on_double_spinbox_freq_changed(self) -> None:
        """
        Handle frequency change from doubleSpinBox.
        """
        try:
            freq_mhz = self.main.doubleSpinBox_freq.value()
            self.logger.info(f"📻 DoubleSpinBox changed to: {freq_mhz:.3f} MHz")
            
            # Sync widgets
            self.sync_frequency_widgets(freq_mhz)
            
            # Update plot range
            self.main._update_plot_range(freq_mhz)
            
            # Apply to SDR directly (no debounce for direct input)
            if self.main.is_running and self.main.bladerf:
                self._apply_to_sdr(freq_mhz)
            
        except Exception as e:
            self.logger.error(f"Error in on_double_spinbox_freq_changed: {e}")
    
    # ------------------------------------------------------------------------
    # WIDGET SYNCHRONIZATION
    # ------------------------------------------------------------------------
    
    def sync_frequency_widgets(self, freq_mhz: float) -> None:
        """
        Synchronize all frequency widgets to the same value.
        
        Args:
            freq_mhz: Frequency in MHz
        """
        # DoubleSpinBox in main window
        if hasattr(self.main, 'doubleSpinBox_freq'):
            self.main.doubleSpinBox_freq.blockSignals(True)
            self.main.doubleSpinBox_freq.setValue(freq_mhz)
            self.main.doubleSpinBox_freq.blockSignals(False)
        
        # RF widget frequency control
        if hasattr(self.main, 'rf_widget') and hasattr(self.main.rf_widget, 'doubleSpinBox_freq'):
            self.main.rf_widget.doubleSpinBox_freq.blockSignals(True)
            self.main.rf_widget.doubleSpinBox_freq.setValue(freq_mhz)
            self.main.rf_widget.doubleSpinBox_freq.blockSignals(False)
        
        # Frequency spinner
        if hasattr(self.main, 'frequency_spinner'):
            self.main.frequency_spinner.setFrequency(freq_mhz)
        
        # Plot marker
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.set_frequency(freq_mhz)
        
        self.logger.debug(f"🔄 Widgets synced to {freq_mhz:.3f} MHz")
    
    def _update_frequency_ui(self, freq_mhz: float) -> None:
        """
        Update UI without applying to hardware.
        
        Args:
            freq_mhz: Frequency in MHz
        """
        # DoubleSpinBox
        if hasattr(self.main, 'doubleSpinBox_freq'):
            self.main.doubleSpinBox_freq.blockSignals(True)
            self.main.doubleSpinBox_freq.setValue(freq_mhz)
            self.main.doubleSpinBox_freq.blockSignals(False)
        
        # RF widget
        if hasattr(self.main, 'rf_widget') and hasattr(self.main.rf_widget, 'doubleSpinBox_freq'):
            self.main.rf_widget.doubleSpinBox_freq.blockSignals(True)
            self.main.rf_widget.doubleSpinBox_freq.setValue(freq_mhz)
            self.main.rf_widget.doubleSpinBox_freq.blockSignals(False)
        
        # Plot marker
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.set_frequency(freq_mhz)
            power = self.main.spectrum_plot._get_power_at_frequency(freq_mhz)
            if hasattr(self.main.spectrum_plot, 'freq_marker'):
                self.main.spectrum_plot.freq_marker.set_power(power)
        
        # Update plot range
        self.main._update_plot_range(freq_mhz)
    
    # ------------------------------------------------------------------------
    # HARDWARE UPDATE
    # ------------------------------------------------------------------------
    
    def _apply_frequency_change(self) -> None:
        """Apply pending frequency change to hardware after debounce."""
        if self.pending_frequency is None:
            return
        
        freq_mhz = self.pending_frequency
        self.logger.info(f"📡 Applying frequency to SDR: {freq_mhz:.3f} MHz")
        
        self._apply_to_sdr(freq_mhz)
        self.pending_frequency = None
    
    def _apply_to_sdr(self, freq_mhz: float) -> bool:
        """
        Apply frequency to SDR hardware.
        
        Args:
            freq_mhz: Frequency in MHz
        
        Returns:
            True if successful
        """
        if not (self.main.is_running and self.main.bladerf):
            return False
        
        freq_hz = freq_mhz * 1e6
        
        # Use SDRDevice interface
        if hasattr(self.main.bladerf, 'set_frequency'):
            success = self.main.bladerf.set_frequency(freq_hz)
            if success:
                self.logger.info(f"✅ SDR frequency updated: {freq_mhz:.3f} MHz")
                return True
            else:
                self.logger.error(f"❌ Fast frequency change failed")
        else:
            # Fallback to configure
            settings = {'frequency': freq_hz}
            success = self.main.bladerf.configure(settings)
            if success:
                self.logger.info(f"✅ SDR frequency updated via configure")
                return True
        
        return False
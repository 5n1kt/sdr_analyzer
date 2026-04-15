# -*- coding: utf-8 -*-

"""
Configuration Manager - Persistent Settings
============================================
Manages persistent application settings using QSettings.

Features:
    - Saves/loads RF, FFT, visualization, and window settings
    - Export/import profiles as JSON
    - Multi-platform configuration storage
    - Singleton-like pattern via reference passing
"""

import json
import os
import logging
from datetime import datetime
from PyQt5.QtCore import QSettings, QByteArray, QPoint, QSize
from PyQt5.QtWidgets import QDockWidget, QApplication
from typing import Optional


# ============================================================================
# CONFIGURATION MANAGER
# ============================================================================

class ConfigManager:
    """
    Manages persistent configuration for the SDR application.
    
    Uses QSettings for platform-appropriate storage (INI on Linux, Registry on Windows).
    
    Usage:
        config = ConfigManager(theme_manager)
        config.load_all_settings(controller)
        config.save_all_settings(controller)
    
    Configuration Sections:
        rf: Frequency, sample rate, bandwidth, gain, gain mode, AGC
        fft: FFT size, window type, averaging, overlap
        visualization: Color map, persistence, max/min hold, thresholds
        window: Geometry, dock states, window state
        theme: Current theme
    """
    
    # ------------------------------------------------------------------------
    # CONSTANTS
    # ------------------------------------------------------------------------
    ORGANIZATION = "INIDETEC - DCD"
    APPLICATION = "SIMANEEM"
    CONFIG_VERSION = "1.0"
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, theme_manager=None):
        """
        Initialize the configuration manager.
        
        Args:
            theme_manager: Reference to the global ThemeManager instance
        """
        self.logger = logging.getLogger(__name__)
        self.theme_manager = theme_manager
        self.logger.info(f"✅ ConfigManager initialized")
        
        # Initialize QSettings
        QSettings.setDefaultFormat(QSettings.IniFormat)
        self.settings = QSettings(self.ORGANIZATION, self.APPLICATION)
        
        self.logger.info(f"   Settings file: {self.settings.fileName()}")
    
    # ------------------------------------------------------------------------
    # SAVE CONFIGURATION
    # ------------------------------------------------------------------------
    
    def save_all_settings(self, controller) -> None:
        """
        Saves all configuration from the controller.
        
        Args:
            controller: MainController instance
        """
        self.logger.info("💾 Saving configuration...")
        
        # Save version and timestamp
        self.settings.setValue("config_version", self.CONFIG_VERSION)
        self.settings.setValue("last_save", datetime.now().isoformat())
        
        # Save each section
        self._save_rf_settings(controller)
        self._save_fft_settings(controller)
        self._save_viz_settings(controller)
        self._save_window_settings(controller)
        self._save_theme_settings(controller)
        self._save_artemis_settings(controller)  
        
        self.settings.sync()
        self.logger.info("✅ Configuration saved")
    
    def _save_rf_settings(self, controller) -> None:
        """Saves RF settings."""
        if not hasattr(controller, 'rf_widget'):
            return
        
        self.settings.beginGroup("rf")
        
        # Frequency: prefer spinner if available
        if hasattr(controller, 'frequency_spinner'):
            freq_mhz = controller.frequency_spinner.frequency_mhz
        else:
            freq_mhz = controller.rf_widget.doubleSpinBox_freq.value()
        
        self.settings.setValue("frequency_mhz", freq_mhz)
        self.settings.setValue("sample_rate", 
                               controller.rf_widget.comboBox_sample_rate.currentData())
        self.settings.setValue("bandwidth", 
                               controller.rf_widget.comboBox_bandwidth.currentData())
        self.settings.setValue("gain", 
                               controller.rf_widget.horizontalSlider_gain.value())
        
        # Gain mode mapping
        gain_mode_index = controller.rf_widget.comboBox_gain_mode.currentIndex()
        gain_modes = [1, 0, 2, 3, 4]  # Manual, Default, Fast AGC, Slow AGC, Hybrid
        self.settings.setValue("gain_mode", gain_modes[gain_mode_index])
        
        self.settings.setValue("agc", controller.rf_widget.checkBox_agc.isChecked())
        self.settings.endGroup()
        
        self.logger.debug(f"   RF: {freq_mhz:.3f} MHz saved")
    
    def _save_fft_settings(self, controller) -> None:
        """Saves FFT settings."""
        if not hasattr(controller, 'fft_widget'):
            return
        
        widget = controller.fft_widget
        settings = widget.get_settings()
        
        self.settings.beginGroup("fft")
        self.settings.setValue("fft_size", settings['fft_size'])
        self.settings.setValue("window", settings['window'])
        self.settings.setValue("averaging", settings['averaging'])
        self.settings.setValue("overlap", settings['overlap'])
        self.settings.endGroup()
        
        self.logger.debug("   FFT settings saved")
    
    def _save_viz_settings(self, controller) -> None:
        """Saves visualization settings."""
        if not hasattr(controller, 'viz_widget'):
            return
        
        widget = controller.viz_widget
        settings = widget.get_settings()
        
        self.settings.beginGroup("visualization")
        self.settings.setValue("color_map", settings['color_map'])
        self.settings.setValue("persistence", settings['persistence'])
        self.settings.setValue("plot_max", settings['plot_max'])
        self.settings.setValue("plot_min", settings['plot_min'])
        self.settings.setValue("min_threshold", settings.get('min_threshold', -120))
        self.settings.setValue("max_threshold", settings.get('max_threshold', 0))
        self.settings.setValue("hold_mode", settings.get('hold_mode', 'manual'))
        self.settings.setValue("hold_seconds", settings.get('hold_seconds', 0))
        self.settings.endGroup()
        
        self.logger.debug("   Visualization settings saved")
    
    def _save_window_settings(self, controller) -> None:
        """Saves window geometry and dock states."""
        self.settings.beginGroup("window")
        
        # Window geometry
        self.settings.setValue("geometry", controller.saveGeometry())
        self.settings.setValue("windowState", controller.saveState())
        
        # Dock visibility states
        dock_states = {}
        for dock in controller.findChildren(QDockWidget):
            if dock.objectName():
                dock_states[dock.objectName()] = not dock.isHidden()
        self.settings.setValue("dock_states", json.dumps(dock_states))
        
        self.settings.endGroup()
        self.logger.debug("   Window settings saved")
    
    def _save_theme_settings(self, controller) -> None:
        """Saves theme settings."""
        if not hasattr(controller, 'theme_manager'):
            return
        
        self.settings.beginGroup("theme")
        self.settings.setValue("current_theme", controller.theme_manager.current_theme)
        self.settings.endGroup()


    def _save_artemis_settings(self, controller) -> None:
        """Guarda la configuración de Artemis"""
        if not hasattr(controller, 'artemis_widget'):
            return
        
        self.settings.beginGroup("artemis")
        
        # Guardar ruta de la base de datos
        if hasattr(controller.artemis_widget, 'base_path') and controller.artemis_widget.base_path:
            self.settings.setValue("database_path", controller.artemis_widget.base_path)
            self.logger.debug(f"   Artemis DB path saved: {controller.artemis_widget.base_path}")
        
        self.settings.endGroup()
    
    # ------------------------------------------------------------------------
    # LOAD CONFIGURATION
    # ------------------------------------------------------------------------
    
    def load_all_settings(self, controller) -> bool:
        """
        Loads all configuration and applies it to the controller.
        
        Args:
            controller: MainController instance
        
        Returns:
            True if load was successful
        """
        self.logger.info("📂 Loading configuration...")
        
        # Check version
        saved_version = self.settings.value("config_version", "0.0")
        if saved_version != self.CONFIG_VERSION:
            self.logger.warning(
                f"⚠️ Configuration version mismatch: "
                f"{saved_version} vs {self.CONFIG_VERSION}"
            )
        
        # Load each section
        self._load_rf_settings(controller)
        self._load_fft_settings(controller)
        self._load_viz_settings(controller)
        self._load_window_settings(controller)
        self._load_theme_settings(controller)
        self._load_artemis_settings(controller) 
        
        self.logger.info("✅ Configuration loaded")
        return True
    
    def _load_rf_settings(self, controller) -> None:
        """Loads RF settings."""
        if not hasattr(controller, 'rf_widget'):
            return
        
        self.settings.beginGroup("rf")
        
        freq_mhz = self.settings.value("frequency_mhz", 100.0, type=float)
        sample_rate = self.settings.value("sample_rate", 2e6, type=float)
        bandwidth = self.settings.value("bandwidth", 1e6, type=float)
        gain = self.settings.value("gain", 50, type=int)
        gain_mode = self.settings.value("gain_mode", 1, type=int)
        agc = self.settings.value("agc", False, type=bool)
        
        self.settings.endGroup()
        
        # Apply RF settings (block signals to avoid unwanted updates)
        controller.rf_widget.blockSignals(True)
        
        # Sample rate
        idx = controller.rf_widget.comboBox_sample_rate.findData(sample_rate)
        if idx >= 0:
            controller.rf_widget.comboBox_sample_rate.setCurrentIndex(idx)
        
        # Bandwidth
        idx = controller.rf_widget.comboBox_bandwidth.findData(bandwidth)
        if idx >= 0:
            controller.rf_widget.comboBox_bandwidth.setCurrentIndex(idx)
        
        # Gain
        controller.rf_widget.horizontalSlider_gain.setValue(gain)
        
        # Gain mode
        gain_modes = [1, 0, 2, 3, 4]
        if gain_mode in gain_modes:
            idx = gain_modes.index(gain_mode)
            controller.rf_widget.comboBox_gain_mode.setCurrentIndex(idx)
        
        # AGC
        controller.rf_widget.checkBox_agc.setChecked(agc)
        
        controller.rf_widget.blockSignals(False)
        
        # Sync all frequency widgets
        if hasattr(controller, 'sync_frequency_widgets'):
            controller.sync_frequency_widgets(freq_mhz)
        else:
            if hasattr(controller, 'doubleSpinBox_freq'):
                controller.doubleSpinBox_freq.setValue(freq_mhz)
            if hasattr(controller, 'frequency_spinner'):
                controller.frequency_spinner.setFrequency(freq_mhz)
        
        self.logger.debug(
            f"   RF loaded: {freq_mhz:.3f} MHz, {sample_rate/1e6:.1f} MSPS"
        )
    
    def _load_fft_settings(self, controller) -> None:
        """Loads FFT settings."""
        if not hasattr(controller, 'fft_widget'):
            return
        
        self.settings.beginGroup("fft")
        fft_size = self.settings.value("fft_size", 1024, type=int)
        window = self.settings.value("window", "Hann", type=str)
        averaging = self.settings.value("averaging", 1, type=int)
        overlap = self.settings.value("overlap", 50, type=int)
        self.settings.endGroup()
        
        controller.fft_widget.blockSignals(True)
        
        # FFT size
        idx = controller.fft_widget.comboBox_fft_size.findText(str(fft_size))
        if idx >= 0:
            controller.fft_widget.comboBox_fft_size.setCurrentIndex(idx)
        
        # Window
        idx = controller.fft_widget.comboBox_window_type.findText(window)
        if idx >= 0:
            controller.fft_widget.comboBox_window_type.setCurrentIndex(idx)
        
        # Averaging
        controller.fft_widget.horizontalSlider_averaging.setValue(averaging)
        
        # Overlap
        controller.fft_widget.horizontalSlider_overlap.setValue(overlap)
        
        controller.fft_widget.blockSignals(False)
        
        self.logger.debug(
            f"   FFT loaded: {fft_size}, {window}, avg={averaging}, overlap={overlap}%"
        )
    
    def _load_viz_settings(self, controller) -> None:
        """Loads visualization settings."""
        if not hasattr(controller, 'viz_widget'):
            return
        
        self.settings.beginGroup("visualization")
        color_map = self.settings.value("color_map", "Viridis", type=str)
        persistence = self.settings.value("persistence", 50, type=int)
        plot_max = self.settings.value("plot_max", False, type=bool)
        plot_min = self.settings.value("plot_min", False, type=bool)
        min_threshold = self.settings.value("min_threshold", -120, type=int)
        max_threshold = self.settings.value("max_threshold", 0, type=int)
        hold_mode = self.settings.value("hold_mode", "manual", type=str)
        hold_seconds = self.settings.value("hold_seconds", 0, type=int)
        self.settings.endGroup()
        
        controller.viz_widget.blockSignals(True)
        
        # Color map (by data, not display text)
        idx = controller.viz_widget.comboBox_color_map.findData(color_map.lower())
        if idx < 0:
            idx = controller.viz_widget.comboBox_color_map.findData('viridis')
        if idx >= 0:
            controller.viz_widget.comboBox_color_map.setCurrentIndex(idx)
        
        # Persistence
        controller.viz_widget.horizontalSlider_persistence.setValue(persistence)
        controller.viz_widget.label_persistence_value.setText(f"{persistence}%")
        
        # Checkboxes
        controller.viz_widget.checkBox_plot_max.setChecked(plot_max)
        controller.viz_widget.checkBox_plot_min.setChecked(plot_min)
        
        # Thresholds
        if hasattr(controller.viz_widget, 'min_spin'):
            controller.viz_widget.min_spin.setValue(min_threshold)
        if hasattr(controller.viz_widget, 'max_spin'):
            controller.viz_widget.max_spin.setValue(max_threshold)
        
        # Hold mode
        if hasattr(controller.viz_widget, 'comboBox_hold_time'):
            seconds_to_index = {0: 0, 1: 1, 2: 2, 5: 3, 10: 4, 30: 5, 60: 6}
            idx = seconds_to_index.get(hold_seconds, 0)
            controller.viz_widget.comboBox_hold_time.setCurrentIndex(idx)
            controller.viz_widget.hold_mode = hold_mode
            controller.viz_widget.hold_seconds = hold_seconds
            
            if hold_mode == 'timed' and hold_seconds > 0:
                controller.viz_widget.hold_timer.start(hold_seconds * 1000)
            else:
                controller.viz_widget.hold_timer.stop()
        
        controller.viz_widget.blockSignals(False)
        
        self.logger.debug(
            f"   Viz loaded: {color_map}, persist={persistence}%, "
            f"range={min_threshold}/{max_threshold} dB, hold={hold_mode}/{hold_seconds}s"
        )
    
    def _load_window_settings(self, controller) -> None:
        """Loads window geometry and dock states."""
        self.settings.beginGroup("window")
        
        # Geometry
        geometry = self.settings.value("geometry")
        if geometry:
            controller.restoreGeometry(geometry)
        
        # Window state
        window_state = self.settings.value("windowState")
        if window_state:
            controller.restoreState(window_state)
        
        # Dock visibility states (apply after restoring state)
        dock_states_json = self.settings.value("dock_states", "{}", type=str)
        try:
            dock_states = json.loads(dock_states_json)
            for dock in controller.findChildren(QDockWidget):
                if dock.objectName() in dock_states:
                    dock.setVisible(dock_states[dock.objectName()])
        except Exception:
            pass
        
        self.settings.endGroup()
        self.logger.debug("   Window settings loaded")
    
    def _load_theme_settings(self, controller) -> None:
        """Loads theme settings."""
        if not self.theme_manager:
            self.logger.warning("⚠️ No theme_manager available")
            return
        
        self.settings.beginGroup("theme")
        theme_key = self.settings.value("current_theme", "dark", type=str)
        self.settings.endGroup()
        
        # Apply theme using the existing theme_manager
        app = QApplication.instance()
        if app:
            self.theme_manager.apply_theme_to_app(app, theme_key)
        
        # Update menu checks
        if hasattr(controller, 'ui_ctrl'):
            controller.ui_ctrl._update_theme_menu_checks(theme_key)
        
        # Update spectrum plot colors
        if hasattr(controller, 'spectrum_plot'):
            theme = self.theme_manager.get_theme_colors(theme_key)
            controller.spectrum_plot.set_curve_colors(
                active_color=theme['spectrum_default'].name(),
                max_color=theme['max_hold_default'].name(),
                min_color=theme['min_hold_default'].name()
            )
        
        self.logger.debug(f"   Theme loaded: {theme_key}")

    def _load_artemis_settings(self, controller) -> None:
        """Carga la configuración de Artemis"""
        if not hasattr(controller, 'artemis_widget'):
            return
        
        self.settings.beginGroup("artemis")
        
        # Cargar ruta de la base de datos (NO cargar automáticamente)
        db_path = self.settings.value("database_path", "", type=str)
        if db_path and os.path.exists(db_path) and os.path.exists(os.path.join(db_path, "static")):
            controller.artemis_widget.base_path = db_path
            self.logger.info(f"📂 Ruta de Artemis DB cargada: {db_path}")
            # NOTA: NO llamamos a load_database() aquí
        else:
            self.logger.debug("   No se encontró ruta válida de Artemis DB")
        
        self.settings.endGroup()
    
    # ------------------------------------------------------------------------
    # UTILITY METHODS
    # ------------------------------------------------------------------------
    
    def clear_all_settings(self) -> None:
        """Clears all saved settings."""
        self.settings.clear()
        self.logger.warning("🗑️ All settings cleared")
    
    def export_settings(self, filename: str) -> bool:
        """
        Exports settings to a JSON file.
        
        Args:
            filename: Path to export file
        
        Returns:
            True if export was successful
        """
        export_data = {}
        
        # Collect all groups
        for group in ["rf", "fft", "visualization", "window"]:
            self.settings.beginGroup(group)
            export_data[group] = {}
            for key in self.settings.allKeys():
                export_data[group][key] = self.settings.value(key)
            self.settings.endGroup()
        
        # Add metadata
        export_data['_metadata'] = {
            'export_date': datetime.now().isoformat(),
            'config_version': self.CONFIG_VERSION,
            'application': self.APPLICATION
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, default=str)
            self.logger.info(f"📤 Settings exported to {filename}")
            return True
        except Exception as e:
            self.logger.error(f"Error exporting settings: {e}")
            return False
    
    def import_settings(self, filename: str, controller=None) -> bool:
        """
        Imports settings from a JSON file.
        
        Args:
            filename: Path to import file
            controller: MainController instance to apply settings (optional)
        
        Returns:
            True if import was successful
        """
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            # Check metadata
            metadata = import_data.get('_metadata', {})
            self.logger.info(
                f"📥 Importing settings from {metadata.get('export_date', 'unknown date')}"
            )
            
            # Import each group
            for group, values in import_data.items():
                if group == '_metadata':
                    continue
                
                self.settings.beginGroup(group)
                for key, value in values.items():
                    self.settings.setValue(key, value)
                self.settings.endGroup()
            
            self.settings.sync()
            
            # Apply settings if controller provided
            if controller:
                self.load_all_settings(controller)
            
            self.logger.info(f"✅ Settings imported from {filename}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error importing settings: {e}")
            return False
    
    def get_settings_file_path(self) -> str:
        """Returns the path to the settings file."""
        return self.settings.fileName()
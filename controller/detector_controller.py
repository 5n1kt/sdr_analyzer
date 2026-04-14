# -*- coding: utf-8 -*-

"""
Detector Controller - Signal Detection Management
==================================================
Controls the signal detector adapter and integrates with the main pipeline.

Features:
    - Band scanning with configurable frequencies
    - Automatic frequency stepping
    - CFAR detection via GRInspectorAdapter
    - Progress reporting for scan status
"""

import logging
from PyQt5.QtCore import QTimer

from workers.gr_inspector_adapter import GRInspectorAdapter
from widgets.signal_detector_widget import SignalDetectorWidget


# ============================================================================
# DETECTOR CONTROLLER
# ============================================================================

class DetectorController:
    """
    Controls signal detection and band scanning.
    
    Manages the GRInspectorAdapter (CFAR detector) and coordinates
    frequency scanning across configured bands.
    """
    
    SCAN_INTERVAL_MS = 600          # Time per frequency (ms)
    MIN_SCAN_INTERVAL_MS = 500      # Minimum recommended interval
    
    def __init__(self, main_controller):
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.DetectorController")
        
        self.widget = None
        self.adapter = None
        self.current_freq_index = 0
        self.scan_timer = None
        self.scan_config = {}
        
        self.logger.info("✅ DetectorController initialized")
    
    # ------------------------------------------------------------------------
    # WIDGET CREATION
    # ------------------------------------------------------------------------
    
    def create_widget(self) -> SignalDetectorWidget:
        """Create and configure the signal detector widget."""
        if self.widget is None:
            self.widget = SignalDetectorWidget(self.main)
            self.widget.main_controller = self.main
            
            # Connect signals
            self.widget.scan_started.connect(self.on_scan_started)
            self.widget.scan_stopped.connect(self.on_scan_stopped)
            self.widget.scan_paused.connect(self.on_scan_paused)
            self.widget.scan_resumed.connect(self.on_scan_resumed)
            self.widget.frequency_selected.connect(self.on_frequency_selected)
            self.widget.scan_config_updated.connect(self.on_config_updated)
        
        return self.widget
    
    # ------------------------------------------------------------------------
    # SCAN CONTROL
    # ------------------------------------------------------------------------
    
    def on_scan_started(self, config: dict) -> None:
        """Start band scanning."""
        self.logger.info("▶ Starting detector")
        self.scan_config = config
        
        self.stop_adapter()
        
        # Check if capture is active
        if not self.main.is_running or not self.main.ring_buffer:
            self.widget.update_inspector_status(False)
            self.widget.update_scan_state(False)
            self.logger.error("❌ Start capture first")
            return
        
        # Create adapter
        sample_rate = self.main.bladerf.sample_rate if self.main.bladerf else 2e6
        
        self.adapter = GRInspectorAdapter(
            ring_buffer=self.main.ring_buffer,
            sample_rate=sample_rate,
        )
        self.adapter.configure(config)
        
        # Connect signals
        self.adapter.inspector_ready.connect(self.widget.update_inspector_status)
        self.adapter.detection_result.connect(self.widget.add_detection)
        self.adapter.stats_updated.connect(self._on_stats_updated)
        self.adapter.scan_progress.connect(self._on_scan_progress)
        self.adapter.values_updated.connect(self.widget.update_detector_values)
        self.adapter.values_updated.connect(self._update_spectrum_lines)
        
        self.adapter.start_processing()
        
        # Check scan interval
        interval = self.SCAN_INTERVAL_MS
        if interval < self.MIN_SCAN_INTERVAL_MS:
            self.logger.warning(
                f"⚠️ Scan interval {interval}ms < minimum {self.MIN_SCAN_INTERVAL_MS}ms"
            )
        
        # Start frequency stepping timer
        self.current_freq_index = 0
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self._scan_next_frequency)
        self.scan_timer.start(interval)
        
        self.widget.update_scan_state(True, False)
        
        # Log scan info
        band_name = config.get('band_name', '?')
        freq_count = len(config.get('band_frequencies', []))
        est_time_s = freq_count * interval / 1000
        self.logger.info(
            f"📡 Scanning '{band_name}' — "
            f"{freq_count} frequencies × {interval}ms ≈ {est_time_s:.0f}s/pass"
        )
    
    def on_scan_stopped(self) -> None:
        """Stop scanning."""
        self.logger.info("⏹ Stopping detector")
        self.stop_adapter()
        self.widget.update_scan_state(False)
    
    def on_scan_paused(self) -> None:
        """Pause scanning."""
        self.logger.info("⏸ Pausing detector")
        if self.adapter:
            self.adapter.pause_processing()
        if self.scan_timer:
            self.scan_timer.stop()
        self.widget.update_scan_state(True, True)
    
    def on_scan_resumed(self) -> None:
        """Resume scanning."""
        self.logger.info("▶ Resuming detector")
        if self.adapter:
            self.adapter.resume_processing()
        if self.scan_timer and not self.scan_timer.isActive():
            self.scan_timer.start(self.SCAN_INTERVAL_MS)
        self.widget.update_scan_state(True, False)
    
    def on_frequency_selected(self, freq_mhz: float) -> None:
        """Tune to selected frequency."""
        self.logger.info(f"🎯 Tuning to {freq_mhz:.3f} MHz")
        
        if not self.main.bladerf:
            self.logger.warning("⚠️ SDR not available")
            return
        
        # Use SDRDevice interface
        success = self.main.bladerf.set_frequency(freq_mhz * 1e6)
        if success:
            self.main.sync_frequency_widgets(freq_mhz)
            if self.adapter:
                self.adapter.set_current_frequency(freq_mhz)
            self.main.statusbar.showMessage(f"📡 Tuned to {freq_mhz:.3f} MHz", 3000)
        else:
            self.logger.error(f"❌ Error tuning to {freq_mhz:.3f} MHz")
    
    def on_config_updated(self, config: dict) -> None:
        """Handle configuration updates from widget."""
        self.logger.info(f"⚙️ Config updated: {list(config.keys())}")
        
        if config.get('sync_detector_values'):
            self.logger.info("🔄 Syncing detector values")
            self._force_sync_values()
        elif config.get('request_values'):
            self._update_values_from_adapter()
        
        if 'show_threshold' in config:
            self._update_threshold_visibility(
                config['show_threshold'],
                config.get('threshold_value')
            )
        
        if 'show_noise' in config:
            self._update_noise_visibility(
                config['show_noise'],
                config.get('noise_value')
            )
    
    # ------------------------------------------------------------------------
    # INTERNAL METHODS
    # ------------------------------------------------------------------------
    
    def stop_adapter(self) -> None:
        """Stop and clean up adapter."""
        if self.scan_timer:
            self.scan_timer.stop()
            self.scan_timer = None
        
        if self.adapter and self.adapter.isRunning():
            self.adapter.stop_processing()
            self.adapter.wait(2000)
            self.adapter = None
    
    def _scan_next_frequency(self) -> None:
        """Advance to next frequency in the scan list."""
        if not self.main.is_running or not self.main.bladerf:
            return
        
        frequencies = self.widget.get_band_frequencies()
        if not frequencies:
            return
        
        total = len(frequencies)
        if self.current_freq_index >= total:
            self.current_freq_index = 0
        
        freq_mhz = frequencies[self.current_freq_index]
        
        # Use SDRDevice interface
        self.main.bladerf.set_frequency(freq_mhz * 1e6)
        
        if self.adapter:
            self.adapter.set_current_frequency(freq_mhz)
            self.adapter.set_scan_progress(self.current_freq_index, total)
        
        self.current_freq_index += 1
    
    def _on_stats_updated(self, samples: int, detections: int) -> None:
        """Update progress display."""
        self.widget.update_progress(samples, detections)
    
    def _on_scan_progress(self, index: int, total: int) -> None:
        """Update scan progress bar."""
        if total > 0:
            self.widget.progressBar.setValue(int((index / total) * 100))
    
    def _force_sync_values(self) -> None:
        """Force sync of threshold and noise values."""
        self.logger.info("🔄 Forcing value sync")
        
        if self.adapter and hasattr(self.adapter, 'cfar') and self.adapter.cfar:
            cfar = self.adapter.cfar
            self.widget.update_detector_values(cfar.threshold_db, cfar.noise_floor_db)
            
            if not self.widget.checkBox_auto_threshold.isChecked():
                self.widget.doubleSpinBox_threshold.blockSignals(True)
                self.widget.doubleSpinBox_threshold.setValue(cfar.threshold_db)
                self.widget.doubleSpinBox_threshold.blockSignals(False)
    
    def _update_values_from_adapter(self) -> None:
        """Update values from adapter."""
        if self.adapter and hasattr(self.adapter, 'cfar') and self.adapter.cfar:
            cfar = self.adapter.cfar
            self.widget.update_detector_values(cfar.threshold_db, cfar.noise_floor_db)
    
    def _update_threshold_visibility(self, visible: bool, value: float = None) -> None:
        """Update threshold line visibility."""
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.set_threshold_visible(visible)
            if value is not None:
                self.main.spectrum_plot.update_threshold(value)
    
    def _update_noise_visibility(self, visible: bool, value: float = None) -> None:
        """Update noise floor line visibility."""
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.set_noise_visible(visible)
            if value is not None:
                self.main.spectrum_plot.update_noise(value)
    
    def _update_spectrum_lines(self, threshold_db: float, noise_db: float) -> None:
        """Update detector lines on spectrum plot."""
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.update_threshold(threshold_db)
            self.main.spectrum_plot.update_noise(noise_db)
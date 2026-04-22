# controller/fft_controller.py
# -*- coding: utf-8 -*-

"""
FFT Controller - Spectral Processing Management
================================================
Manages FFT processing and spectrum visualization.

This controller connects FFT processors to the visualization pipeline
and handles FFT parameter updates.

Corrections Applied:
    1. Proper frame consumption notification to prevent dropped frames
    2. Periodic logging of frequency axis (every 300 frames)
    3. Safe handling of averaging status update (check for method existence)
"""

import logging
import numpy as np
import traceback
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer


class FFTController:
    """
    Manages FFT processing and spectrum visualization.
    
    This is the single point where fft_data_ready from any FFTProcessorZeroCopy
    connects to the rendering pipeline.
    """
    
    def __init__(self, main_controller):
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.FFTController")

        # Referencia al controlador TSCM
        self._tscm_controller = None
        
        # Buffer for spectrum persistence
        self._prev_spectrum = None
        
        # Periodic logging counter (every 300 frames ≈ 10s at 30fps)
        self._log_frame_counter = 0
        self._LOG_EVERY_N = 300    

    # ------------------------------------------------------------------------
    # CONNECTION METHODS
    # ------------------------------------------------------------------------
    
    def set_tscm_controller(self, tscm_controller):
        """
        Establece la referencia al TSCMController.
        
        Args:
            tscm_controller: Instancia de TSCMController
        """
        self._tscm_controller = tscm_controller
        self.logger.info("✅ TSCMController vinculado a FFTController")

    def connect_fft_processor(self, processor) -> None:
        """
        Connect a live capture FFT processor.
        
        Args:
            processor: FFTProcessorZeroCopy instance
        """
        processor.fft_data_ready.connect(self._on_fft_data_live)
        processor.stats_updated.connect(self._on_fft_stats)
        self.logger.info("✅ Live FFTProcessor connected")
    
    def connect_playback_fft_processor(self, processor) -> None:
        """
        Connect a playback FFT processor.
        
        Args:
            processor: FFTProcessorZeroCopy instance
        """
        processor.fft_data_ready.connect(self._on_fft_data_playback)
        self.logger.info("✅ Playback FFTProcessor connected")
    
    # ------------------------------------------------------------------------
    # FFT DATA RECEIVERS
    # ------------------------------------------------------------------------
    
    def _on_fft_data_live(self, fft_data: np.ndarray) -> None:
        """Handle live capture FFT data."""
        self.update_spectrum(fft_data)
        
        # Notify processor that frame was consumed
        if (self.main.fft_processor is not None
                and hasattr(self.main.fft_processor, 'on_frame_consumed')):
            self.main.fft_processor.on_frame_consumed()
    
    def _on_fft_data_playback(self, fft_data: np.ndarray) -> None:
        """Handle playback FFT data."""
        self.update_spectrum(fft_data)
        
        if (self.main.playback_fft_processor is not None
                and hasattr(self.main.playback_fft_processor, 'on_frame_consumed')):
            self.main.playback_fft_processor.on_frame_consumed()
    
    # ------------------------------------------------------------------------
    # FFT SETTINGS UPDATE
    # ------------------------------------------------------------------------
    
    def update_fft_settings(self, settings: dict) -> None:
        """
        Update FFT parameters with intelligent restart logic.
        
        Args:
            settings: Dictionary with fft_size, window, averaging, overlap
        """
        if not self.main.fft_processor:
            return
        
        self._log_changes(settings)
        
        restart_needed, fft_size_changed = self._check_restart_needed(settings)
        processor_restart = self.main.fft_processor.update_settings(settings)
        restart_needed = restart_needed or processor_restart
        
        if restart_needed and self.main.is_running:
            self._handle_restart(settings, fft_size_changed)
    
    def _log_changes(self, settings: dict) -> None:
        """Log FFT setting changes."""
        changes = [
            f"{k}: {settings[k]}"
            for k in ('window', 'averaging', 'overlap', 'fft_size')
            if k in settings
        ]
        if changes:
            self.logger.info(f"🔄 FFT changes: {', '.join(changes)}")
    
    def _check_restart_needed(self, settings: dict) -> tuple:
        """Check if restart is needed for FFT changes."""
        restart_needed = False
        fft_size_changed = False
        
        if 'fft_size' in settings:
            old_size = getattr(self.main.fft_processor, 'fft_size', 0)
            new_size = settings['fft_size']
            if new_size != old_size:
                restart_needed = True
                fft_size_changed = True
                self.logger.info(f"📏 FFT size change: {old_size} → {new_size}")
        
        return restart_needed, fft_size_changed
    
    def _handle_restart(self, settings: dict, fft_size_changed: bool) -> None:
        """Handle FFT processor restart."""
        self.main.statusbar.showMessage("Reconfiguring FFT...", 1000)
        
        if self.main.fft_processor.isRunning():
            self.main.fft_processor.stop(immediate=True)
            QTimer.singleShot(
                50,
                lambda: self._continue_reconfig(settings, fft_size_changed)
            )
        else:
            self._continue_reconfig(settings, fft_size_changed)
    
    def _continue_reconfig(self, settings: dict, fft_size_changed: bool) -> None:
        """Continue reconfiguration after processor stop."""
        try:
            self.main.statusbar.showMessage("⚙️ Reconfiguring FFT... please wait", 0)
            QApplication.processEvents()
            
            # Resize waterfall buffer if FFT size changed
            if fft_size_changed and hasattr(self.main, 'waterfall'):
                self.main.waterfall.resize_buffer(settings['fft_size'])
                QApplication.processEvents()
            
            # Reinitialize hold buffers
            if fft_size_changed:
                new_size = settings['fft_size']
                self.main.max_hold = np.full(new_size, self.main.FLOOR_DB)
                self.main.min_hold = np.full(new_size, self.main.CEILING_DB)
                self._prev_spectrum = None
            
            # Clear ring buffer
            self._clear_ring_buffer()
            
            # Restart processor
            self.main.statusbar.showMessage("🚀 Starting new FFT...", 500)
            QApplication.processEvents()
            self.main.fft_processor.start()
            
            self.main.statusbar.showMessage("✅ FFT reconfigured", 2000)
            self.logger.info("✅ FFT reconfigured successfully")
            
        except Exception as exc:
            self.logger.error(f"❌ Error in FFT reconfiguration: {exc}")
            self.main.statusbar.showMessage(f"Error: {exc}", 3000)
            traceback.print_exc()
    
    def _clear_ring_buffer(self) -> None:
        """Drain ring buffer to ensure clean start."""
        if not hasattr(self.main, 'ring_buffer') or not self.main.ring_buffer:
            return
        
        drained = 0
        for _ in range(self.main.ring_buffer.num_buffers):
            result = self.main.ring_buffer.get_read_buffer(timeout_ms=10)
            if result:
                _, idx = result
                self.main.ring_buffer.release_read(idx)
                drained += 1
        
        if drained > 0:
            self.logger.info(f"🧹 Drained {drained} buffers from ring")
    
    # ------------------------------------------------------------------------
    # SPECTRUM UPDATE
    # ------------------------------------------------------------------------
    # controller/fft_controller.py

    def update_spectrum(self, fft_data: np.ndarray) -> None:
        """Update all visualizations with new FFT frame."""
        try:
            sample_rate, center_freq_hz = self._get_current_parameters()
            
            fft_size = len(fft_data)
            center_freq_mhz = center_freq_hz / 1e6
            sample_rate_mhz = sample_rate / 1e6
            
            freq_axis_mhz = np.linspace(
                center_freq_mhz - sample_rate_mhz / 2,
                center_freq_mhz + sample_rate_mhz / 2,
                fft_size,
            )
            
            # Aplicar persistencia normal
            p = float(getattr(self.main, 'persistence_factor', 0.0))
            alpha = 1.0 - float(np.clip(p, 0.0, 0.99))
            
            fft_f32 = fft_data.astype(np.float32)
            
            if self._prev_spectrum is None or len(self._prev_spectrum) != fft_size:
                displayed = fft_f32.copy()
            else:
                displayed = (
                    alpha * fft_f32 + (1.0 - alpha) * self._prev_spectrum
                ).astype(np.float32)
            
            self._prev_spectrum = displayed.copy()
            
            # Actualizar max/min hold
            if getattr(self.main, 'reset_max_min_flag', False):
                self.main.reset_max_min_flag = False
                self.main.max_hold = fft_data.copy()
                self.main.min_hold = fft_data.copy()
            else:
                self._update_hold_buffers(fft_data, fft_size)
            
            # --- INTEGRACIÓN TSCM ---
            baseline_to_plot = None
            if self._tscm_controller and self._tscm_controller.is_diff_mode_active():
                plot_spectrum, baseline_to_plot = self._tscm_controller.process_spectrum(
                    displayed, freq_axis_mhz
                )
                plot_max = None
                plot_min = None
            else:
                plot_spectrum = displayed
                plot_max = self.main.max_hold if self.main.plot_max else None
                plot_min = self.main.min_hold if self.main.plot_min else None
            # -------------------------
            
            # Actualizar waterfall
            self._update_waterfall(
                plot_spectrum, freq_axis_mhz, center_freq_mhz, sample_rate_mhz,
                alpha=alpha,
            )
            
            # Actualizar spectrum plot
            if hasattr(self.main, 'spectrum_plot'):
                if baseline_to_plot is not None:
                    self.main.spectrum_plot.update_plot_with_baseline(
                        plot_spectrum, freq_axis_mhz,
                        max_hold=plot_max, min_hold=plot_min,
                        baseline=baseline_to_plot
                    )
                else:
                    self.main.spectrum_plot.update_plot(
                        plot_spectrum, freq_axis_mhz,
                        max_hold=plot_max, min_hold=plot_min
                    )
            
            self._update_plot_range(center_freq_mhz, sample_rate_mhz)
            
            # Log periódico
            self._log_frame_counter += 1
            if self._log_frame_counter >= self._LOG_EVERY_N:
                self._log_frame_counter = 0
                self.logger.info(
                    f"📊 X-axis: {freq_axis_mhz[0]:.1f} – {freq_axis_mhz[-1]:.1f} MHz "
                    f"(SR={sample_rate_mhz:.1f} MHz)"
                )
            
        except Exception as exc:
            self.logger.error(f"Error updating graphics: {exc}")
            import traceback
            traceback.print_exc()

    
    def _get_current_parameters(self) -> tuple:
        """Get current sample rate and center frequency."""
        if self.main.is_playing_back and self.main.player:
            return self.main.player.sample_rate, self.main.player.freq_mhz * 1e6
        sr = self.main.bladerf.sample_rate if self.main.bladerf else 2e6
        freq = self.main.bladerf.frequency if self.main.bladerf else 100e6
        return sr, freq
    
    def _update_waterfall(self, fft_data, freq_axis, center_freq, sample_rate, alpha=1.0):
        """Update waterfall plot."""
        if hasattr(self.main, 'waterfall'):
            self.main.waterfall.update_spectrum(
                fft_data, freq_axis, center_freq, sample_rate, alpha=alpha
            )
    
    def _update_hold_buffers(self, fft_data: np.ndarray, fft_size: int) -> None:
        """Update max/min hold buffers."""
        if self.main.max_hold is None or len(self.main.max_hold) != fft_size:
            self.main.max_hold = fft_data.copy()
        else:
            np.maximum(self.main.max_hold, fft_data, out=self.main.max_hold)
        
        if self.main.min_hold is None or len(self.main.min_hold) != fft_size:
            self.main.min_hold = fft_data.copy()
        else:
            np.minimum(self.main.min_hold, fft_data, out=self.main.min_hold)
    
    def _update_spectrum_plot(self, fft_data: np.ndarray, freq_axis) -> None:
        """Update spectrum plot."""
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.update_plot(
                fft_data,
                freq_axis,
                max_hold=self.main.max_hold if self.main.plot_max else None,
                min_hold=self.main.min_hold if self.main.plot_min else None,
            )
    
    def _update_plot_range(self, center_freq: float, sample_rate: float) -> None:
        """Update plot X range."""
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.plot_widget.setXRange(
                center_freq - sample_rate / 2,
                center_freq + sample_rate / 2,
            )
        
        # Update band plan if visible
        if (hasattr(self.main, 'spectrum_plot') 
                and hasattr(self.main.spectrum_plot, 'show_band_plan')
                and self.main.spectrum_plot.show_band_plan):
            self.main.spectrum_plot.update_band_regions()
    
    # ------------------------------------------------------------------------
    # STATISTICS HANDLER
    # ------------------------------------------------------------------------
    
    def _on_fft_stats(self, stats: dict) -> None:
        """
        Handle FFT processor statistics.
        
        CORRECTION: Safe check for update_averaging_real method existence.
        """
        # Update UI with real averaging value (if widget supports it)
        if hasattr(self.main, 'fft_widget'):
            # Check if method exists before calling
            if hasattr(self.main.fft_widget, 'update_averaging_real'):
                self.main.fft_widget.update_averaging_real(
                    actual=stats.get('actual_averaging', 1),
                    target=stats.get('target_averaging', 1)
                )
            else:
                # Log only occasionally to avoid spam
                if not hasattr(self, '_logged_averaging_warning'):
                    self.logger.warning(
                        "FFTControlsWidget missing update_averaging_real method. "
                        "Averaging status display disabled."
                    )
                    self._logged_averaging_warning = True
            
            # Log informational message (every 50 frames)
            if stats.get('fft_frames', 0) % 50 == 0:
                actual = stats.get('actual_averaging', 1)
                target = stats.get('target_averaging', 1)
                if actual < target:
                    self.logger.info(
                        f"📊 FFT averaging: target={target}, "
                        f"actual={actual} (limited by data availability)"
                    )

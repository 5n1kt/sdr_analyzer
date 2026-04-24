# -*- coding: utf-8 -*-

"""
Playback Controller - IQ File Playback
=======================================
Manages playback of IQ recordings with async file loading.

Features:
    - Asynchronous file loading (non-blocking UI)
    - Seamless transition between live capture and playback
    - Automatic restoration of RF configuration after playback
    - Speed control and loop mode
    - Progress reporting with accurate time calculation

CORRECTIONS APPLIED:
    1. Async file loading with FileLoaderThread
    2. Proper state restoration between live and playback modes
    3. Accurate time calculation (4 bytes per complex sample)
    4. Smooth progress slider updates
"""

import os
import time
import logging
import traceback
import numpy as np  
from PyQt5.QtWidgets import QMessageBox, QApplication
from PyQt5.QtCore import QThread, pyqtSignal

from workers.iq_player import IQPlayer
from workers.shared_buffer import IQRingBuffer
from workers.fft_processor_zerocopy import FFTProcessorZeroCopy


# ============================================================================
# ASYNC FILE LOADER THREAD
# ============================================================================

class FileLoaderThread(QThread):
    """
    Loads IQ file in a separate thread to prevent UI blocking.
    """
    load_finished = pyqtSignal(bool, object)  # (success, player_instance)
    
    def __init__(self, filename: str):
        super().__init__()
        self.filename = filename
        self.player = None
        self.success = False
    
    def run(self) -> None:
        """Load file in background."""
        try:
            self.player = IQPlayer()
            self.success = self.player.load_file(self.filename)
            self.load_finished.emit(self.success, self.player)
        except Exception as e:
            logging.getLogger(__name__).error(f"Error in FileLoaderThread: {e}")
            self.load_finished.emit(False, None)


# ============================================================================
# PLAYBACK CONTROLLER
# ============================================================================

class PlaybackController:
    """
    Controls IQ file playback.
    
    Manages the transition between live capture and playback modes,
    including saving and restoring RF configuration.
    """
    
    def __init__(self, main_controller):
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.PlaybackController")
        
        # State
        self._saved_rf_config = None
        self._is_loading = False
        self._metadata_callback = None
        
        # Pending configuration
        self._pending_speed = 1.0
        self._pending_loop = False
        self._pending_filename = None
        self._pending_fft_size = 1024
        self._pending_samples_per_block = 8192
        
        # File loader
        self._file_loader = None
    
    # ------------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------------
    
    def on_playback_requested(self, filename: str, play: bool) -> None:
        """
        Handle playback request from IQ Manager.
        
        Args:
            filename: Path to IQ file
            play: True to start, False to stop
        """
        if play:
            self.logger.info(f"▶ Playback requested: {filename}")
            self.start_playback(filename)
        else:
            self.logger.info("⏹ Stop requested")
            self.stop_playback()
    
    def start_playback(self, filename: str) -> None:
        """
        Start playback of IQ file.
        
        Args:
            filename: Path to IQ file (.sigmf-data or .bin)
        """
        # Prevent multiple loads
        if self._is_loading:
            self.logger.warning("⚠️ Already loading, ignoring...")
            return
        
        try:
            self.logger.info("=" * 60)
            self.logger.info(f"🎬 Starting playback: {filename}")
            
            # Clear previous metadata in UI
            if hasattr(self.main, 'iq_manager') and self.main.iq_manager:
                self.logger.info("🗑️ Clearing previous metadata...")
                self.main.iq_manager.clear_metadata_display()
                QApplication.processEvents()
            
            # ===== STEP 1: Stop live capture if active =====
            if self.main.is_running:
                self.logger.info("📻 Live capture active - stopping before playback")
                self._saved_rf_config = {
                    'frequency': self.main.bladerf.frequency if self.main.bladerf else 100e6,
                    'sample_rate': self.main.bladerf.sample_rate if self.main.bladerf else 2e6,
                    'bandwidth': self.main.bladerf.bandwidth if self.main.bladerf else 1e6,
                    'gain': self.main.bladerf.gain if self.main.bladerf else 50,
                    'gain_mode': self.main.bladerf.gain_mode if self.main.bladerf else 'Manual'
                }
                self.logger.info(f"💾 RF config saved: {self._saved_rf_config['frequency']/1e6:.1f} MHz")
                self.main.rf_ctrl.stop_rx()
                QApplication.processEvents()
                time.sleep(0.1)
            
            # ===== STEP 2: Stop any existing playback =====
            if self.main.is_playing_back:
                self.logger.info("⏹ Stopping previous playback")
                self.stop_playback()
                QApplication.processEvents()
                time.sleep(0.1)
            
            # ===== STEP 3: Verify file exists =====
            if not os.path.exists(filename):
                self.logger.error(f"❌ File not found: {filename}")
                QMessageBox.critical(self.main, "Error", f"File not found:\n{filename}")
                if hasattr(self.main, 'iq_manager') and self.main.iq_manager:
                    self.main.iq_manager.label_play_metadata.setText("File not found")
                return
            
            # ===== STEP 4: Get playback configuration =====
            speed = 1.0
            loop = False
            if hasattr(self.main, 'iq_manager'):
                speed = float(self.main.iq_manager.spinBox_play_speed.value())
                loop = self.main.iq_manager.pushButton_play_loop.isChecked()
                self.logger.info(f"⚙️ Config: speed={speed}x, loop={loop}")
            
            # ===== STEP 5: Save pending configuration =====
            self._pending_speed = speed
            self._pending_loop = loop
            self._pending_filename = filename
            self._pending_fft_size = self._get_fft_size()
            self._pending_samples_per_block = self._get_samples_per_block()
            
            # ===== STEP 6: Start async file loading =====
            self._is_loading = True
            self.main.statusbar.showMessage("📂 Loading IQ file... please wait")
            QApplication.processEvents()
            
            self._file_loader = FileLoaderThread(filename)
            self._file_loader.load_finished.connect(self._on_file_loaded)
            self._file_loader.start()

            # Actualizar indicador de modo
            if hasattr(self.main, 'update_mode_indicator'):
                self.main.update_mode_indicator('play')
                
            self.logger.info("=" * 60)
            
        except Exception as e:
            self._is_loading = False
            self._handle_error(e)
    
    def stop_playback(self, restore_rx: bool = True) -> None:
        """
        Stop playback and optionally restore live capture.
        
        Args:
            restore_rx: If True, restore RF configuration and start live capture
        """
        self.logger.info("=" * 50)
        self.logger.info("🛑 Stopping playback")
        
        try:
            # Stop player
            if self.main.player:
                self.logger.info("   ⏹ Stopping player...")
                self.main.player.stop_playback()
                if not self.main.player.wait(2000):
                    self.logger.warning("      ⚠️ Player timeout")
                self.main.player.close()
                self.main.player = None
                self.logger.info("   ✅ Player stopped")
            
            # Stop FFT processor
            if self.main.playback_fft_processor:
                self.logger.info("   ⏹ Stopping FFT processor...")
                self.main.playback_fft_processor.stop()
                self.main.playback_fft_processor = None
                self.logger.info("   ✅ FFT processor stopped")
            
            # Clear buffer
            self.main.playback_ring_buffer = None
            self.logger.info("   ✅ Buffer cleared")
            
            # Update state
            self.main.is_playing_back = False
            
            # Restore live capture if requested
            if restore_rx and self._saved_rf_config:
                self.logger.info("   🔄 Restoring RF configuration...")
                self._restore_rx_config()
            
            # Update UI
            self._update_ui_playback_state(False)
            
            if hasattr(self.main, 'iq_manager'):
                self.main.iq_manager.set_playback_playing(False)
                self.main.iq_manager.set_playback_state(True)
                self.main.iq_manager.pushButton_play_pause.setText("⏸ PAUSE")
            
            # Clear waterfall
            if hasattr(self.main, 'waterfall'):
                self.main.waterfall.clear()

            # Restaurar indicador de modo
            if hasattr(self.main, 'update_mode_indicator'):
                self.main.update_mode_indicator('live')
            
            self.main.statusbar.showMessage("⏹ Playback stopped", 3000)
            self.logger.info("✅ Playback stopped successfully")
            
        except Exception as e:
            self.logger.error(f"❌ Error stopping playback: {e}")
            traceback.print_exc()
        
        self.logger.info("=" * 50)
    
    def pause_playback(self) -> None:
        """Pause current playback."""
        if self.main.player and self.main.is_playing_back:
            self.logger.info("⏸ Pausing playback")
            self.main.player.pause_playback()
    
    def resume_playback(self) -> None:
        """Resume paused playback."""
        if self.main.player and self.main.is_playing_back:
            self.logger.info("▶ Resuming playback")
            self.main.player.resume_playback()
    
    def set_loop_mode(self, enabled: bool) -> None:
        """Enable/disable loop mode."""
        if self.main.player:
            self.main.player.loop = enabled
            self.logger.info(f"🔄 Loop mode: {'on' if enabled else 'off'}")
    
    def set_metadata_callback(self, callback) -> None:
        """Register callback for metadata updates."""
        self._metadata_callback = callback
        self.logger.info("✅ Metadata callback registered")
    
    # ------------------------------------------------------------------------
    # PRIVATE METHODS - FILE LOADING
    # ------------------------------------------------------------------------
    
    def _on_file_loaded(self, success: bool, player) -> None:
        """
        Called when file loading completes.
        
        Args:
            success: True if file loaded successfully
            player: IQPlayer instance (or None)
        """
        self._is_loading = False
        
        try:
            if not success or player is None:
                raise RuntimeError("Could not load file")
            
            self.logger.info("=" * 60)
            self.logger.info("📂 File loaded successfully")
            
            # Assign player
            self.main.player = player

            # IMPORTANTE: Guardar la frecuencia del archivo ANTES de restaurar
            playback_freq = player.freq_mhz
            playback_sr = player.sample_rate
            
            self.logger.info(f"📡 Playback file frequency: {playback_freq:.1f} MHz")
            self.logger.info(f"📡 Playback file sample rate: {playback_sr/1e6:.1f} MHz")
            
            # Actualizar widgets de frecuencia con la frecuencia del archivo
            self.main.sync_frequency_widgets(playback_freq)
            
            # Actualizar plot range con la frecuencia del archivo
            self.main._update_plot_range_with_sr(playback_freq, playback_sr)
            
            # NO actualizar la frecuencia del SDR durante reproducción
            # El SDR está detenido, no es necesario
            
            # Connect signals
            self._connect_player_signals()
            
            # Emit metadata
            if hasattr(self.main.player, 'metadata') and self.main.player.metadata:
                self.logger.info("📡 Updating UI with metadata...")
                self._on_playback_metadata(self.main.player.metadata)
            else:
                self.logger.warning("⚠️ No metadata available")
            
            # Configure player
            self.main.player.configure(
                samples_per_buffer=self._pending_samples_per_block,
                speed=self._pending_speed,
                loop=self._pending_loop
            )
            
            # Update plot range
            self._update_ui_with_playback_info()
            
            # Create playback pipeline
            self._create_playback_pipeline(
                self._pending_samples_per_block,
                self._pending_fft_size
            )
            
            # Start FFT processor
            self.logger.info("🚀 Starting FFT processor...")
            self.main.playback_fft_processor.start()
            
            # Start playback
            self.logger.info("▶ Starting playback...")
            self.main.is_playing_back = True
            self.main.player.start_playback()
            
            # Update UI
            self._update_ui_playback_state(True, self._pending_filename)
            
            self.logger.info("✅ Playback started successfully")
            self.logger.info("=" * 60)
            
        except Exception as e:
            self._handle_error(e)
    
    def _connect_player_signals(self) -> None:
        """Connect all player signals."""
        if self.main.player is None:
            return
        
        p = self.main.player
        
        self.logger.info("🔌 Connecting player signals...")
        
        p.metadata_loaded.connect(self._on_playback_metadata)
        p.buffer_ready.connect(self._on_playback_buffer_ready)
        p.playback_finished.connect(self._on_playback_finished)
        p.playback_stopped.connect(self._on_playback_stopped)
        p.error_occurred.connect(self._on_playback_error)
        p.progress_updated.connect(self._on_playback_progress)
        p.playback_started.connect(self._on_playback_started)
        p.playback_paused.connect(self._on_playback_paused)
        
        self.logger.info("✅ All player signals connected")
    
    def _on_playback_metadata(self, metadata: dict) -> None:
        """
        Handle metadata from player.
        
        Args:
            metadata: Dictionary with file metadata
        """
        self.logger.info("=" * 60)
        self.logger.info("📋 Playback metadata received")
        self.logger.info(f"   Freq: {metadata.get('frequency', 100):.3f} MHz")
        self.logger.info(f"   SR: {metadata.get('sample_rate', 2e6)/1e6:.2f} MHz")
        self.logger.info(f"   Duration: {metadata.get('duration', 0):.1f} s")
        self.logger.info(f"   Mode: {metadata.get('mode', 'CONT')}")
        
        # Update UI
        if hasattr(self.main, 'iq_manager') and self.main.iq_manager:
            self.main.iq_manager.update_metadata_display(metadata)
        
        # Callback for external listeners
        if self._metadata_callback:
            self._metadata_callback(metadata)
    
    # ------------------------------------------------------------------------
    # PRIVATE METHODS - PIPELINE SETUP
    # ------------------------------------------------------------------------
    
    def _get_fft_size(self) -> int:
        """Get current or pending FFT size."""
        if hasattr(self.main, 'fft_widget'):
            return self.main.fft_widget.get_settings().get('fft_size', 1024)
        return 1024
    
    def _get_samples_per_block(self) -> int:
        """Get samples per block from hardware."""
        if self.main.bladerf:
            return getattr(self.main.bladerf, 'samples_per_block', 8192)
        return 8192
    
    def _create_playback_pipeline(self, samples_per_block: int, fft_size: int) -> None:
        """
        Create playback pipeline (ring buffer + FFT processor).
        
        Args:
            samples_per_block: Samples per buffer
            fft_size: FFT size in bins
        """
        self.logger.info("🔄 Creating playback pipeline...")


        # Aumentar significativamente el buffer de reproducción
        # 512 slots es insuficiente para 6835 bloques/segundo
        # Calculamos para 2 segundos de buffer
        blocks_per_second = self.main.player.sample_rate / samples_per_block
        buffer_seconds = 2  # 2 segundos de buffer
        num_buffers = max(1024, int(blocks_per_second * buffer_seconds))
        
        self.logger.info(f"   Playback buffer: {num_buffers} slots × {samples_per_block} samples")
        
        self.main.playback_ring_buffer = IQRingBuffer(
            num_buffers=num_buffers,  # Aumentado de 512 a valor calculado
            samples_per_buffer=samples_per_block,
            use_shared_memory=False
        )
        
        # Ring buffer
        '''self.main.playback_ring_buffer = IQRingBuffer(
            num_buffers=512,
            samples_per_buffer=samples_per_block,
            use_shared_memory=False
        )'''
        
        # FFT processor
        self.main.playback_fft_processor = FFTProcessorZeroCopy(
            self.main.playback_ring_buffer,
            sample_rate=self.main.player.sample_rate
        )
        
        # Configure FFT
        self.main.playback_fft_processor.update_settings({
            'fft_size': fft_size,
            'window': 'Hann',
            'averaging': 1,
            'overlap': 50,
            'sample_rate': self.main.player.sample_rate
        })
        
        # Connect to main FFT controller
        self.main.fft_ctrl.connect_playback_fft_processor(
            self.main.playback_fft_processor
        )
        
        self.logger.info("✅ Playback pipeline created")
    
    def _update_ui_with_playback_info(self) -> None:
        """Update UI with file metadata."""
        if self.main.player is None:
            return
        
        p = self.main.player
        playback_freq = p.freq_mhz
        playback_sr = p.sample_rate
        
        self.logger.info(f"📡 Playback freq: {playback_freq:.1f} MHz")
        self.logger.info(f"📡 Playback SR: {playback_sr/1e6:.1f} MHz")
        
        # Update frequency widgets
        self.main.sync_frequency_widgets(playback_freq)
        
        # Update plot range
        self.main._update_plot_range_with_sr(playback_freq, playback_sr)
    
    def _update_ui_playback_state(self, playing: bool, filename: str = None) -> None:
        """
        Update UI based on playback state.
        
        Args:
            playing: True if playing
            filename: Current file (for status bar)
        """
        if playing and filename and self.main.player is not None:
            try:
                file_size_mb = os.path.getsize(filename) / 1e6
                duration = 0
                if hasattr(self.main.player, 'metadata') and self.main.player.metadata:
                    duration = self.main.player.metadata.get('duration', 0)
                
                self.main.statusbar.showMessage(
                    f"▶ Playing: {os.path.basename(filename)} | "
                    f"{file_size_mb:.1f} MB | {duration:.1f} s"
                )
                
                if hasattr(self.main, 'iq_manager'):
                    self.main.iq_manager.update_mode_indicator("play")
            except Exception as e:
                self.logger.warning(f"Error updating UI: {e}")
        else:
            self.main.statusbar.showMessage("Playback stopped")
            if hasattr(self.main, 'iq_manager'):
                self.main.iq_manager.update_mode_indicator("live")
    
    '''def _restore_rx_config(self) -> None:
        """Restore saved RF configuration and start live capture."""
        if not self._saved_rf_config:
            self.logger.info("ℹ️ No saved RF config to restore")
            return
        
        self.logger.info("🔄 Restoring RF configuration...")
        
        if hasattr(self.main, 'rf_ctrl'):
            self.main.rf_ctrl.update_rf_settings(self._saved_rf_config)
            self.logger.info(f"✅ RF config restored: {self._saved_rf_config['frequency']/1e6:.1f} MHz")
            self._saved_rf_config = None'''

    # controller/playback_controller.py - En _restore_rx_config

    def _restore_rx_config(self) -> None:
        """Restore saved RF configuration and start live capture."""
        if not self._saved_rf_config:
            self.logger.info("ℹ️ No saved RF config to restore")
            return
        
        self.logger.info("🔄 Restoring RF configuration...")
        
        # Extraer frecuencia guardada
        saved_freq = self._saved_rf_config.get('frequency', 100e6)
        self.logger.info(f"   Saved frequency: {saved_freq/1e6:.1f} MHz")
        
        # Obtener frecuencia actual del archivo (si existe)
        playback_freq = None
        if self.main.player:
            playback_freq = self.main.player.freq_mhz * 1e6
            self.logger.info(f"   Playback frequency: {playback_freq/1e6:.1f} MHz")
        
        # Restaurar configuración
        if hasattr(self.main, 'rf_ctrl'):
            self.main.rf_ctrl.update_rf_settings(self._saved_rf_config)
            
            # Verificar que la frecuencia se restauró correctamente
            if self.main.bladerf:
                current_freq = self.main.bladerf.frequency
                self.logger.info(f"   Current frequency after restore: {current_freq/1e6:.1f} MHz")
                
                # Si la frecuencia no coincide con la guardada, forzar actualización
                if abs(current_freq - saved_freq) > 1000:  # 1 kHz de tolerancia
                    self.logger.warning(f"   Frequency mismatch, forcing to {saved_freq/1e6:.1f} MHz")
                    self.main.bladerf.set_frequency(saved_freq)
            
            self._saved_rf_config = None
    
    # ------------------------------------------------------------------------
    # PLAYER SIGNAL HANDLERS
    # ------------------------------------------------------------------------
    
    def _on_playback_buffer_ready(self, iq_data: np.ndarray) -> None:
        """
        Handle buffer ready from player.
        
        Args:
            iq_data: IQ samples (complex64)
        """
        try:
            if not self.main.playback_ring_buffer:
                return
            
            write_buffer = self.main.playback_ring_buffer.get_write_buffer()
            
            if write_buffer is None:
                self.logger.warning("⚠️ Ring buffer full in playback")
                return
            
            min_samples = min(len(write_buffer), len(iq_data))
            write_buffer[:min_samples] = iq_data[:min_samples]
            self.main.playback_ring_buffer.commit_write()
            
        except Exception as e:
            self.logger.error(f"Error in playback buffer ready: {e}")
    
    def _on_playback_finished(self) -> None:
        """Handle natural end of file."""
        self.logger.info("🏁 Playback finished naturally")
        
        if hasattr(self.main, 'iq_manager'):
            mgr = self.main.iq_manager
            mgr.set_playback_playing(False)
            mgr.set_playback_state(True)
            mgr.label_play_status_text.setText("FINISHED")
        
        self.main.is_playing_back = False
        self.stop_playback(restore_rx=True)
    
    def _on_playback_stopped(self) -> None:
        """Handle player stopped signal."""
        self.logger.info("🔊 Playback stopped signal received")
        
        if self.main.is_playing_back:
            self.logger.info("   → Calling stop_playback()")
            self.stop_playback()
    
    def _on_playback_error(self, error_msg: str) -> None:
        """Handle playback error."""
        self.logger.error(f"❌ Playback error: {error_msg}")
        self.main.statusbar.showMessage(f"Error: {error_msg}")
        self.stop_playback()
    
    def _on_playback_progress(self, position_bytes: float, total_bytes: float) -> None:
        """
        Handle progress update from player.
        
        Args:
            position_bytes: Current position in bytes
            total_bytes: Total file size in bytes
        """
        if total_bytes <= 0:
            return
        
        if not hasattr(self.main, 'iq_manager') or self.main.iq_manager is None:
            return
        
        mgr = self.main.iq_manager
        
        # Update slider (0-1000 range)
        ratio = position_bytes / total_bytes
        slider_value = int(ratio * 1000)
        
        mgr.horizontalSlider_play.blockSignals(True)
        mgr.horizontalSlider_play.setValue(slider_value)
        mgr.horizontalSlider_play.blockSignals(False)
        
        # Update time labels
        try:
            if self.main.player is None:
                return
            
            sr = self.main.player.sample_rate
            if sr <= 0:
                sr = 2e6
            
            speed = getattr(self.main.player, 'speed', 1.0)
            
            # 4 bytes per complex sample (int16 I + int16 Q)
            total_seconds = total_bytes / (sr * 4)
            current_seconds = position_bytes / (sr * 4)
            
            current_effective = current_seconds / speed if speed > 0 else current_seconds
            total_effective = total_seconds / speed if speed > 0 else total_seconds
            
            mgr.label_play_status_text.setText(
                f"PLAYING  {current_effective:.1f}s / {total_effective:.1f}s ({speed:.0f}x)"
            )
            
            if hasattr(mgr, 'label_play_duration'):
                mgr.label_play_duration.setText(f"{total_effective:.1f} s")
                
        except Exception as e:
            self.logger.debug(f"Error updating time labels: {e}")
    
    def _on_playback_started(self) -> None:
        """Handle playback started signal."""
        self.logger.info("🔊 Playback started signal received")
        if hasattr(self.main, 'iq_manager'):
            mgr = self.main.iq_manager
            mgr.set_playback_playing(True)
            mgr.pushButton_play_pause.setText("⏸ PAUSE")
            mgr.label_play_status_text.setText("PLAYING")
    
    def _on_playback_paused(self) -> None:
        """Handle playback paused signal."""
        self.logger.info("🔊 Playback paused signal received")
        if hasattr(self.main, 'iq_manager'):
            self.main.iq_manager.label_play_status_icon.setText("⏸")
            self.main.iq_manager.label_play_status_text.setText("PAUSED")
            self.main.iq_manager.pushButton_play_pause.setText("▶ RESUME")
            self.main.iq_manager.pushButton_play_play.setEnabled(False)
            self.main.iq_manager.pushButton_play_stop.setEnabled(True)
    
    # ------------------------------------------------------------------------
    # ERROR HANDLING
    # ------------------------------------------------------------------------
    
    def _handle_error(self, error: Exception) -> None:
        """
        Handle playback errors.
        
        Args:
            error: Exception that occurred
        """
        self.logger.error(f"❌ Playback error: {error}")
        traceback.print_exc()
        
        self.stop_playback()
        
        QMessageBox.critical(
            self.main,
            "Playback Error",
            f"Could not start playback:\n{str(error)}"
        )
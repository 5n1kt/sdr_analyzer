# -*- coding: utf-8 -*-

"""
IQ Manager Widget - Unified Recording & Playback
=================================================
Widget for managing IQ recordings and playback.

Features:
    - SigMF format recording (.sigmf-data + .sigmf-meta)
    - Time-limited and size-limited recording modes
    - IQ file playback with speed control and loop
    - Metadata display from SigMF and .meta files
    - Progress slider with seek
    - Mode indicator (LIVE/PLAY)
"""

import os
import re
import json
import time
import logging
import subprocess
import platform
from datetime import datetime
from PyQt5.QtWidgets import (QDockWidget, QFileDialog, QMessageBox,
                              QLabel, QApplication)
from PyQt5.QtCore import pyqtSignal, QTimer
from PyQt5.uic import loadUi

from workers.iq_recorder_simple import IQRecorderSimple


# ============================================================================
# IQ MANAGER WIDGET
# ============================================================================

class IQManagerWidget(QDockWidget):
    """
    Unified widget for IQ recording and playback.
    
    Signals:
        playback_requested: Emitted when playback starts (filename, play)
    """
    
    playback_requested = pyqtSignal(str, bool)
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        loadUi('ui/iq_manager_widget.ui', self)
        
        # References
        self.main_controller = None
        self.recording_buffer = None
        self.recorder = None
        
        # State
        self.is_capturing = False
        self.current_freq = 100.0
        self.current_sample_rate = 2e6
        self.current_playback_file = None
        
        # Timers
        self.ui_update_timer = QTimer()
        self.ui_update_timer.setInterval(100)
        self.ui_update_timer.timeout.connect(self._update_ui_from_recorder)
        
        self.playback_progress_timer = QTimer()
        self.playback_progress_timer.setInterval(100)
        self.playback_progress_timer.timeout.connect(self._update_playback_slider)
        
        # Seek state
        self._is_seeking = False
        self._was_playing_before_seek = False
        
        # Setup
        self.setup_ui()
        self.setup_connections()
        self._ensure_labels_exist()
        self._verify_labels()
        
        self.logger.info("✅ IQManagerWidget created")
    
    # ------------------------------------------------------------------------
    # UI SETUP
    # ------------------------------------------------------------------------
    
    def setup_ui(self) -> None:
        """Configure UI elements."""
        # Recording limits
        self.spinBox_record_duration.setRange(1, 3600)
        self.spinBox_record_duration.setValue(10)
        self.spinBox_record_size.setRange(10, 102400)
        self.spinBox_record_size.setValue(100)
        self.spinBox_record_size.setSuffix(" MB")
        
        # Recording mode radio buttons
        self.radio_record_continuous.toggled.connect(self._on_record_mode_changed)
        self.radio_record_time.toggled.connect(self._on_record_mode_changed)
        self.radio_record_size.toggled.connect(self._on_record_mode_changed)
        self._on_record_mode_changed()
        
        # Playback controls
        self.spinBox_play_speed.setRange(1, 100)
        self.spinBox_play_speed.setValue(1)
        self.spinBox_play_speed.valueChanged.connect(self._on_speed_changed)
        self._set_playback_ui_state(False)
        
        # Mode indicator (LIVE/PLAY)
        self.label_mode_indicator = QLabel("📻 MODO: LIVE")
        self.label_mode_indicator.setStyleSheet("""
            QLabel {
                color: #00ff00;
                font-weight: bold;
                background-color: #1a1a1a;
                padding: 4px 8px;
                border: 1px solid #00ff00;
                border-radius: 4px;
            }
        """)
        if hasattr(self, 'horizontalLayout_mode'):
            self.horizontalLayout_mode.insertWidget(0, self.label_mode_indicator)
    
    def setup_connections(self) -> None:
        """Connect UI signals."""
        # Recording
        self.pushButton_record_start.clicked.connect(self._on_record_start_clicked)
        self.pushButton_record_stop.clicked.connect(self._on_record_stop_clicked)
        self.pushButton_open_folder.clicked.connect(self._open_recordings_folder)
        
        # Playback
        self.pushButton_play_open.clicked.connect(self._on_play_open_clicked)
        self.pushButton_play_play.clicked.connect(self._on_play_play_clicked)
        self.pushButton_play_pause.clicked.connect(self._on_play_pause_clicked)
        self.pushButton_play_stop.clicked.connect(self._on_play_stop_clicked)
        self.pushButton_play_loop.toggled.connect(self._on_play_loop_toggled)
        
        # Seek slider
        self.horizontalSlider_play.sliderPressed.connect(self._on_seek_start)
        self.horizontalSlider_play.sliderReleased.connect(self._on_seek_end)
        self.horizontalSlider_play.valueChanged.connect(self._on_seek_value_changed)
    
    def _ensure_labels_exist(self) -> None:
        """Create missing labels."""
        required = {
            'label_play_filename': '-',
            'label_play_freq': '-',
            'label_play_sr': '-',
            'label_play_duration': '-',
            'label_play_mode': '-',
            'label_play_metadata': 'No file loaded'
        }
        for name, default in required.items():
            if not hasattr(self, name):
                label = QLabel(default)
                setattr(self, name, label)
    
    def _verify_labels(self) -> None:
        """Log label status for debugging."""
        required = ['label_play_filename', 'label_play_freq', 'label_play_sr',
                    'label_play_duration', 'label_play_mode', 'label_play_metadata']
        for name in required:
            if hasattr(self, name):
                label = getattr(self, name)
                self.logger.info(f"   ✅ {name}: {label.text() if label else 'None'}")
            else:
                self.logger.warning(f"   ❌ {name} NOT FOUND")
    
    # ------------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------------
    
    def set_controller(self, controller) -> None:
        """Set reference to main controller."""
        self.main_controller = controller
        self.logger.info("🔗 IQManagerWidget connected to MainController")
        
        # Connect playback signal
        if hasattr(controller, 'on_playback_requested'):
            self.playback_requested.connect(controller.on_playback_requested)
        
        # Register metadata callback
        if hasattr(controller, 'playback_ctrl'):
            controller.playback_ctrl.set_metadata_callback(self.update_metadata_display)
    
    def set_rf_info(self, freq_mhz: float, sample_rate: float) -> None:
        """Update RF information for recording."""
        self.current_freq = freq_mhz
        self.current_sample_rate = sample_rate
        if hasattr(self, 'label_record_freq'):
            self.label_record_freq.setText(f"{freq_mhz:.3f} MHz")
    
    def on_capture_started(self, recording_buffer) -> None:
        """Called when live capture starts."""
        self.is_capturing = True
        self.recording_buffer = recording_buffer
        
        if self.main_controller and hasattr(self.main_controller, 'bladerf'):
            bf = self.main_controller.bladerf
            if bf:
                self.set_rf_info(bf.frequency / 1e6, bf.sample_rate)
        
        self.logger.info(f"🎤 Capture started — buffer: {recording_buffer.num_buffers} slots")
    
    def on_capture_stopped(self) -> None:
        """Called when live capture stops."""
        self.is_capturing = False
        self.recording_buffer = None
        if self.recorder and self.recorder.is_recording:
            self.recorder.stop_recording()
    
    def set_playback_playing(self, playing: bool) -> None:
        """Update UI for playback state."""
        if playing:
            self.label_play_status_icon.setText("▶")
            self.label_play_status_text.setText("PLAYING")
            self.label_play_status_icon.setStyleSheet("color: #00ff00;")
            self.label_play_status_text.setStyleSheet("color: #00ff00; font-weight: bold;")
            self.pushButton_play_pause.setText("⏸ PAUSE")
        else:
            self.label_play_status_icon.setText("⏹")
            self.label_play_status_text.setText("STOPPED")
            self.label_play_status_icon.setStyleSheet("color: #888888;")
            self.label_play_status_text.setStyleSheet("color: #888888;")
            self.pushButton_play_pause.setText("⏸ PAUSE")
    
    def set_playback_state(self, file_loaded: bool) -> None:
        """Update UI based on file loaded state."""
        self._set_playback_ui_state(file_loaded)
    
    def update_mode_indicator(self, mode: str) -> None:
        """Update mode indicator (LIVE or PLAY)."""
        if mode == "live":
            self.label_mode_indicator.setText("📻 MODO: LIVE")
            self.label_mode_indicator.setStyleSheet("""
                QLabel { color: #00ff00; font-weight: bold; background-color: #1a1a1a;
                         padding: 4px 8px; border: 1px solid #00ff00; border-radius: 4px; }
            """)
        else:
            self.label_mode_indicator.setText("🎬 MODO: PLAY")
            self.label_mode_indicator.setStyleSheet("""
                QLabel { color: #ffaa00; font-weight: bold; background-color: #1a1a1a;
                         padding: 4px 8px; border: 1px solid #ffaa00; border-radius: 4px; }
            """)
    
    def update_metadata_display(self, metadata: dict) -> None:
        """Update UI with file metadata."""
        self.logger.info(f"📋 Updating metadata: freq={metadata.get('frequency')} MHz")
        
        try:
            freq = metadata.get('frequency', 100.0)
            sr = metadata.get('sample_rate', 2e6)
            duration = metadata.get('duration', 0)
            mode = metadata.get('mode', 'CONT')
            file_size = metadata.get('file_size_mb', 0)
            filename = metadata.get('filename', '')
            timestamp = metadata.get('timestamp', '')
            samples = metadata.get('samples', 0)
            
            if hasattr(self, 'label_play_filename'):
                self.label_play_filename.setText(filename if filename else "-")
            if hasattr(self, 'label_play_freq'):
                self.label_play_freq.setText(f"{freq:.3f} MHz")
            if hasattr(self, 'label_play_sr'):
                self.label_play_sr.setText(f"{sr/1e6:.2f} MHz")
            if hasattr(self, 'label_play_duration'):
                self.label_play_duration.setText(f"{duration:.1f} s")
            if hasattr(self, 'label_play_mode'):
                self.label_play_mode.setText(mode)
            
            metadata_text = (
                f"📡 Frequency: {freq:.3f} MHz\n"
                f"📊 Sample Rate: {sr/1e6:.2f} MHz\n"
                f"⏱️ Duration: {duration:.1f} s\n"
                f"📁 Mode: {mode}\n"
                f"💾 Size: {file_size:.1f} MB\n"
                f"📅 Timestamp: {timestamp[:19] if timestamp else 'N/A'}\n"
                f"🔢 Samples: {samples/1e6:.1f}M"
            )
            
            if hasattr(self, 'label_play_metadata'):
                self.label_play_metadata.setText(metadata_text)
            
        except Exception as e:
            self.logger.error(f"Error updating UI: {e}")
    
    def clear_metadata_display(self) -> None:
        """Clear all metadata labels."""
        if hasattr(self, 'label_play_filename'):
            self.label_play_filename.setText("")
        if hasattr(self, 'label_play_freq'):
            self.label_play_freq.setText("-")
        if hasattr(self, 'label_play_sr'):
            self.label_play_sr.setText("-")
        if hasattr(self, 'label_play_duration'):
            self.label_play_duration.setText("-")
        if hasattr(self, 'label_play_mode'):
            self.label_play_mode.setText("-")
        if hasattr(self, 'label_play_metadata'):
            self.label_play_metadata.setText("Loading file...")
        
        self.horizontalSlider_play.blockSignals(True)
        self.horizontalSlider_play.setValue(0)
        self.horizontalSlider_play.blockSignals(False)
        
        self.label_play_status_text.setText("STOPPED")
    
    # ------------------------------------------------------------------------
    # RECORDING METHODS
    # ------------------------------------------------------------------------
    
    def _on_record_mode_changed(self) -> None:
        """Handle recording mode change."""
        is_time = self.radio_record_time.isChecked()
        is_size = self.radio_record_size.isChecked()
        self.spinBox_record_duration.setEnabled(is_time)
        self.spinBox_record_size.setEnabled(is_size)
    
    def _get_current_mode_string(self) -> str:
        """Get mode string for filename."""
        if self.radio_record_time.isChecked():
            return f"TIME{self.spinBox_record_duration.value()}s"
        elif self.radio_record_size.isChecked():
            return f"SIZE{self.spinBox_record_size.value()}MB"
        return "CONT"
    
    def _on_record_start_clicked(self) -> None:
        """Start recording."""
        # Check capture is active
        if not self.is_capturing or self.recording_buffer is None:
            QMessageBox.warning(
                self, "No Capture",
                "Start live capture before recording.\n\n"
                "1. Configure RF parameters\n"
                "2. Press START\n"
                "3. Then start recording"
            )
            return
        
        # Check for existing recording
        if self.recorder and self.recorder.is_recording:
            self.logger.warning("⚠️ Recording already in progress")
            return
        
        # Get real SDR values
        real_sample_rate = self.current_sample_rate
        real_freq = self.current_freq
        
        if self.main_controller and hasattr(self.main_controller, 'bladerf'):
            bladerf = self.main_controller.bladerf
            if bladerf:
                real_sample_rate = bladerf.sample_rate
                real_freq = bladerf.frequency / 1e6
        
        # Configure recording limits
        mode = 'continuous'
        time_limit = 0
        size_limit_mb = 0
        
        if self.radio_record_time.isChecked():
            mode = 'time'
            time_limit = self.spinBox_record_duration.value()
        elif self.radio_record_size.isChecked():
            mode = 'size'
            size_limit_mb = self.spinBox_record_size.value()
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if mode == 'time':
            mode_str = f"TIME{time_limit}s"
        elif mode == 'size':
            mode_str = f"SIZE{size_limit_mb}MB"
        else:
            mode_str = "CONT"
        
        sr_msps = real_sample_rate / 1e6
        sr_str = f"{sr_msps:.0f}MSPS" if sr_msps >= 10 else f"{sr_msps:.1f}MSPS".replace('.', '')
        
        os.makedirs("recordings", exist_ok=True)
        base_filename = f"recordings/IQ_{real_freq:.0f}MHz_{sr_str}_{mode_str}_{timestamp}"
        
        try:
            # Create recorder
            self.recorder = IQRecorderSimple(
                self.recording_buffer,
                real_sample_rate,
                real_freq * 1e6
            )
            
            self.recorder.configure_recording(base_filename, mode, time_limit, size_limit_mb)
            
            # Attach IQ processor for buffer control
            if self.main_controller is not None:
                iq_proc = getattr(self.main_controller, 'iq_processor', None)
                if iq_proc is not None:
                    self.recorder.set_processor(iq_proc)
            
            # Connect signals
            self.recorder.recording_started.connect(self._on_recorder_started)
            self.recorder.recording_stopped.connect(self._on_recorder_stopped)
            self.recorder.stats_updated.connect(self._update_recording_ui)
            
            # Start recording
            self.recorder.start_recording()
            
            # Update UI
            self.pushButton_record_start.setEnabled(False)
            self.pushButton_record_stop.setEnabled(True)
            self.ui_update_timer.start()
            
            display_name = f"{base_filename}.bin"
            self.label_record_filename.setText(os.path.basename(display_name))
            
        except Exception as e:
            self.logger.error(f"Error starting recording: {e}")
            self.recorder = None
            self.pushButton_record_start.setEnabled(True)
            self.pushButton_record_stop.setEnabled(False)
            QMessageBox.critical(self, "Recording Error", str(e))
    
    def _on_record_stop_clicked(self) -> None:
        """Stop recording."""
        if self.recorder and self.recorder.is_recording:
            self.recorder.stop_recording()
    
    def _on_recorder_started(self, filename: str) -> None:
        """Handle recorder started signal."""
        self.label_record_filename.setText(os.path.basename(filename))
        self._set_record_status(True)
    
    def _on_recorder_stopped(self) -> None:
        """Handle recorder stopped signal."""
        self.pushButton_record_start.setEnabled(True)
        self.pushButton_record_stop.setEnabled(False)
        self.ui_update_timer.stop()
        self._set_record_status(False)
    
    def _update_recording_ui(self, stats: dict) -> None:
        """Update recording UI with stats."""
        self.label_record_size.setText(f"{stats['file_size_mb']:.1f} MB")
        self.label_record_time.setText(f"{stats['elapsed_time']:.0f} s")
    
    def _update_ui_from_recorder(self) -> None:
        """Timer callback to update UI from recorder."""
        if not (self.recorder and self.recorder.is_recording):
            return
        elapsed = time.time() - self.recorder.start_time if self.recorder.start_time else 0
        mb = self.recorder.bytes_written / 1e6
        self.label_record_size.setText(f"{mb:.1f} MB")
        self.label_record_time.setText(f"{elapsed:.0f} s")
    
    def _set_record_status(self, recording: bool) -> None:
        """Update recording status display."""
        if recording:
            self.label_record_status_icon.setText("⏺")
            self.label_record_status_text.setText("RECORDING")
            self.label_record_status_icon.setStyleSheet("color: #ff4444;")
            self.label_record_status_text.setStyleSheet("color: #ff4444; font-weight: bold;")
        else:
            self.label_record_status_icon.setText("⏹")
            self.label_record_status_text.setText("STOPPED")
            self.label_record_status_icon.setStyleSheet("color: #888888;")
            self.label_record_status_text.setStyleSheet("color: #888888;")
            self.label_record_filename.setText("-")
            self.label_record_size.setText("0 MB")
            self.label_record_time.setText("0 s")
    
    # ------------------------------------------------------------------------
    # PLAYBACK METHODS
    # ------------------------------------------------------------------------
    
    def _on_play_open_clicked(self) -> None:
        """Open file for playback."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open IQ Recording", "recordings/",
            "IQ Files (*.bin *.sigmf-data);;All Files (*)"
        )
        
        if filename:
            self.clear_metadata_display()
            self.logger.info(f"📂 Loading: {filename}")
            
            # Handle .meta selection
            if filename.endswith('.meta'):
                filename = filename.replace('.meta', '.bin')
                if not os.path.exists(filename):
                    filename = filename.replace('.bin', '.sigmf-data')
            
            if os.path.exists(filename):
                self._load_playback_file(filename)
            else:
                QMessageBox.warning(self, "Error", f"File not found:\n{filename}")
                self.label_play_metadata.setText("File not found")
    
    def _load_playback_file(self, filename: str) -> None:
        """Load file and prepare for playback."""
        self.label_play_filename.setText(os.path.basename(filename))
        self.current_playback_file = filename
        self.horizontalSlider_play.setValue(0)
        self.label_play_metadata.setText("Loading file...")
        self.label_play_freq.setText("...")
        self.label_play_sr.setText("...")
        self.label_play_duration.setText("...")
        self.label_play_mode.setText("...")
        
        QApplication.processEvents()
        
        # Find metadata file
        meta_file = filename.replace('.bin', '.meta')
        if not os.path.exists(meta_file):
            meta_file = filename.replace('.sigmf-data', '.sigmf-meta')
        
        if os.path.exists(meta_file):
            self._load_metadata_file(meta_file)
        else:
            self._set_default_metadata(filename)
        
        self._set_playback_ui_state(True)
        self._update_playback_duration_estimate()
    
    def _load_metadata_file(self, meta_file: str) -> None:
        """Load metadata from .meta or .sigmf-meta file."""
        try:
            # Try multiple encodings
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            content = None
            
            for enc in encodings:
                try:
                    with open(meta_file, 'r', encoding=enc) as f:
                        content = f.read()
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            
            if content is None:
                with open(meta_file, 'rb') as f:
                    content = f.read().decode('utf-8', errors='replace')
            
            # Parse lines
            for line in content.splitlines():
                if 'Frequency:' in line:
                    self.label_play_freq.setText(line.split(':', 1)[1].strip())
                elif 'Sample Rate:' in line:
                    val = line.split(':', 1)[1].strip()
                    self.label_play_sr.setText(val)
                    try:
                        sr_val = float(val.split()[0])
                        self.current_sample_rate = sr_val * 1e6
                    except:
                        pass
                elif 'Duration:' in line:
                    self.label_play_duration.setText(line.split(':', 1)[1].strip())
                elif 'Mode:' in line:
                    self.label_play_mode.setText(line.split(':', 1)[1].strip())
                    
        except Exception as e:
            self.logger.error(f"Error loading metadata: {e}")
            self.label_play_metadata.setText("Error reading metadata")
    
    def _set_default_metadata(self, filename: str) -> None:
        """Set default metadata when no .meta file exists."""
        try:
            file_bytes = os.path.getsize(filename)
            sr = self.current_sample_rate
            
            # Try to infer sample rate from filename
            if sr <= 0 or sr < 1e6:
                match = re.search(r'(\d+)MSPS', filename, re.IGNORECASE)
                if match:
                    sr = float(match.group(1)) * 1e6
                else:
                    sr = 2e6
            
            self.current_sample_rate = sr
            duration_s = file_bytes / (sr * 4) if sr > 0 else 0
            
            self.label_play_metadata.setText("No metadata (calculated)")
            self.label_play_freq.setText(f"{self.current_freq:.3f} MHz")
            self.label_play_sr.setText(f"{sr/1e6:.2f} MHz")
            self.label_play_duration.setText(f"{duration_s:.1f} s")
            self.label_play_mode.setText(f"{file_bytes/1e6:.1f} MB")
            
        except Exception as e:
            self.logger.error(f"Error setting default metadata: {e}")
    
    def _update_playback_duration_estimate(self) -> None:
        """Update estimated playback duration based on speed."""
        if not self.current_playback_file:
            return
        
        try:
            file_size = os.path.getsize(self.current_playback_file)
            sr = self.current_sample_rate if self.current_sample_rate > 0 else 2e6
            duration_sec = file_size / (sr * 4)
            speed = self.spinBox_play_speed.value()
            estimated_sec = duration_sec / speed if speed > 0 else duration_sec
            self.label_play_duration.setText(f"{duration_sec:.1f}s ({speed}x = {estimated_sec:.1f}s)")
        except Exception as e:
            self.logger.error(f"Error calculating duration: {e}")
    
    def _on_play_play_clicked(self) -> None:
        """Start playback."""
        if not self.current_playback_file:
            QMessageBox.warning(self, "Error", "Open a file first")
            return
        
        self.playback_requested.emit(self.current_playback_file, True)
        self._set_playback_ui_playing(True)
    
    def _on_play_pause_clicked(self) -> None:
        """Pause or resume playback."""
        controller = self._get_main_controller()
        if not controller:
            return
        
        if controller.is_playing_back:
            player = getattr(controller, 'player', None)
            if player and getattr(player, 'is_paused', False):
                controller.resume_playback()
                self.pushButton_play_pause.setText("⏸ PAUSE")
            else:
                controller.pause_playback()
                self.pushButton_play_pause.setText("▶ RESUME")
    
    def _on_play_stop_clicked(self) -> None:
        """Stop playback."""
        controller = self._get_main_controller()
        if not controller:
            return
        
        controller.stop_playback()
        self._set_playback_ui_state(True)
        self._set_playback_ui_playing(False)
        
        self.horizontalSlider_play.blockSignals(True)
        self.horizontalSlider_play.setValue(0)
        self.horizontalSlider_play.blockSignals(False)
        
        self.playback_progress_timer.stop()
        self.pushButton_play_pause.setText("⏸ PAUSE")
        self._is_seeking = False
    
    def _on_play_loop_toggled(self, checked: bool) -> None:
        """Toggle loop mode."""
        controller = self._get_main_controller()
        if controller and hasattr(controller, 'set_loop_mode'):
            controller.set_loop_mode(checked)
            self.logger.info(f"🔄 Loop mode: {'on' if checked else 'off'}")
    
    def _on_speed_changed(self, value: int) -> None:
        """Handle speed change."""
        controller = self._get_main_controller()
        if not controller:
            return
        
        speed = float(value)
        self.logger.info(f"⏩ Speed selected: {speed}x")
        self._update_playback_duration_estimate()
        
        if controller.is_playing_back and hasattr(controller, 'player') and controller.player:
            controller.player.speed = speed
            if hasattr(controller.player, 'configure'):
                controller.player.configure(
                    samples_per_buffer=controller.player.samples_per_buffer,
                    speed=speed,
                    loop=controller.player.loop
                )
    
    # ------------------------------------------------------------------------
    # SEEK METHODS
    # ------------------------------------------------------------------------
    
    def _on_seek_start(self) -> None:
        """Start seek (user pressed slider)."""
        self.logger.info("🎚️ Seek started - pausing playback")
        controller = self._get_main_controller()
        
        if controller and controller.is_playing_back:
            self._was_playing_before_seek = True
            controller.pause_playback()
        else:
            self._was_playing_before_seek = False
        
        self._is_seeking = True
    
    def _on_seek_value_changed(self, value: int) -> None:
        """Handle slider value change during seek."""
        if not self._is_seeking:
            return
        self._update_time_from_slider_value(value)
    
    def _on_seek_end(self) -> None:
        """End seek (user released slider)."""
        self.logger.info("🎚️ Seek finished - applying position")
        controller = self._get_main_controller()
        
        if not controller or not controller.player:
            self._is_seeking = False
            return
        
        final_value = self.horizontalSlider_play.value()
        player = controller.player
        
        if player.total_bytes > 0:
            target_position = int(player.total_bytes * final_value / 1000)
            aligned = (target_position // player.bytes_per_buffer) * player.bytes_per_buffer
            aligned = max(0, min(aligned, player.total_bytes - player.bytes_per_buffer))
            player.seek(aligned)
            
            if self._was_playing_before_seek:
                self.logger.info("▶ Resuming playback after seek")
                controller.resume_playback()
        
        self._is_seeking = False
    
    def _update_time_from_slider_value(self, slider_value: int) -> None:
        """Update time display during seek."""
        controller = self._get_main_controller()
        if not controller or not controller.player:
            return
        
        player = controller.player
        if player.total_bytes > 0:
            ratio = slider_value / 1000
            position_bytes = int(player.total_bytes * ratio)
            sr = player.sample_rate
            speed = getattr(player, 'speed', 1.0)
            
            if sr > 0:
                total_seconds = player.total_bytes / (sr * 4)
                current_seconds = position_bytes / (sr * 4)
                current_effective = current_seconds / speed if speed > 0 else current_seconds
                total_effective = total_seconds / speed if speed > 0 else total_seconds
                
                self.label_play_status_text.setText(
                    f"SEEK  {current_effective:.1f}s / {total_effective:.1f}s"
                )
    
    def _update_playback_slider(self) -> None:
        """Update progress slider during playback."""
        if self._is_seeking:
            return
        
        player = getattr(self.main_controller, 'player', None)
        if player is None or player.total_bytes == 0:
            return
        
        ratio = player.position / player.total_bytes if player.position > 0 else 0
        
        self.horizontalSlider_play.blockSignals(True)
        self.horizontalSlider_play.setValue(int(ratio * 1000))
        self.horizontalSlider_play.blockSignals(False)
        
        # Update time labels
        try:
            sr = getattr(player, 'sample_rate', 2e6)
            speed = getattr(player, 'speed', 1.0)
            total_bytes = player.total_bytes
            position = getattr(player, 'position', 0)
            
            if total_bytes > 0 and sr > 0:
                total_seconds = total_bytes / (sr * 4)
                current_seconds = position / (sr * 4)
                current_effective = current_seconds / speed if speed > 0 else current_seconds
                total_effective = total_seconds / speed if speed > 0 else total_seconds
                
                if not self._is_seeking:
                    self.label_play_status_text.setText(
                        f"PLAYING  {current_effective:.1f}s / {total_effective:.1f}s ({speed:.0f}x)"
                    )
                    self.label_play_duration.setText(f"{total_effective:.1f} s")
        except Exception as e:
            self.logger.debug(f"Time update error: {e}")
    
    # ------------------------------------------------------------------------
    # UI STATE HELPERS
    # ------------------------------------------------------------------------
    
    def _set_playback_ui_state(self, file_loaded: bool) -> None:
        """Update UI based on file loaded state."""
        self.pushButton_play_play.setEnabled(file_loaded)
        self.pushButton_play_pause.setEnabled(False)
        self.pushButton_play_stop.setEnabled(False)
        self.horizontalSlider_play.setEnabled(file_loaded)
        self.spinBox_play_speed.setEnabled(file_loaded)
        self.pushButton_play_loop.setEnabled(file_loaded)
        
        if not file_loaded:
            self.label_play_status_icon.setText("⏹")
            self.label_play_status_text.setText("STOPPED")
    
    def _set_playback_ui_playing(self, playing: bool) -> None:
        """Update UI based on playback state."""
        self.pushButton_play_play.setEnabled(not playing)
        self.pushButton_play_pause.setEnabled(playing)
        self.pushButton_play_stop.setEnabled(playing)
        
        if playing:
            self.label_play_status_icon.setText("▶")
            self.label_play_status_text.setText("PLAYING")
            self.pushButton_play_pause.setText("⏸ PAUSE")
        else:
            self.label_play_status_icon.setText("⏹")
            self.label_play_status_text.setText("STOPPED")
            self.pushButton_play_pause.setText("⏸ PAUSE")
    
    # ------------------------------------------------------------------------
    # UTILITY METHODS
    # ------------------------------------------------------------------------
    
    def _open_recordings_folder(self) -> None:
        """Open recordings folder in file explorer."""
        folder = os.path.abspath("recordings")
        os.makedirs(folder, exist_ok=True)
        
        if platform.system() == "Windows":
            os.startfile(folder)
        elif platform.system() == "Darwin":
            subprocess.run(["open", folder])
        else:
            subprocess.run(["xdg-open", folder])
    
    def _get_main_controller(self):
        """Get main controller reference."""
        if self.main_controller is not None:
            return self.main_controller
        
        # Search in parent hierarchy
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'is_running') and hasattr(parent, 'playback_ctrl'):
                self.main_controller = parent
                return self.main_controller
            parent = parent.parent()
        
        return None
    
    # ------------------------------------------------------------------------
    # CLOSE EVENT
    # ------------------------------------------------------------------------
    
    def closeEvent(self, event) -> None:
        """Ensure recording stops on close."""
        if self.recorder and self.recorder.is_recording:
            self.recorder.stop_recording()
            if not self.recorder.wait(3000):
                self.recorder.stop_event.set()
        event.accept()
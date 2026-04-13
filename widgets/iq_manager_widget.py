# widgets/iq_manager_widget.py
# -*- coding: utf-8 -*-


import os
from datetime import datetime
from PyQt5.QtWidgets import (QDockWidget, QFileDialog, QMessageBox,
                              QCheckBox, QProgressBar, QLabel)
from PyQt5.QtCore import pyqtSignal, QTimer
from PyQt5.uic import loadUi
import logging

from workers.iq_recorder_simple import IQRecorderSimple as IQRecorder


class IQManagerWidget(QDockWidget):
    """Widget unificado para grabación y reproducción de datos IQ."""

    playback_requested = pyqtSignal(str, bool)   # (filename, play)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)

        loadUi('ui/iq_manager_widget.ui', self)

        self.main_controller      = None
        self.recording_buffer     = None
        self.recorder             = None

        self.is_capturing         = False
        self.current_freq         = 100.0
        self.current_sample_rate  = 2e6
        self.current_playback_file = None   # None hasta que el usuario abra un archivo

        self.pending_speed         = 1

        # Timer de actualización de UI de grabación (~10 Hz)
        self.ui_update_timer = QTimer()
        self.ui_update_timer.setInterval(100)
        self.ui_update_timer.timeout.connect(self._update_ui_from_recorder)  # FIX BUG 9

        # Timer de progreso de reproducción (~2 Hz)
        self.playback_progress_timer = QTimer()
        self.playback_progress_timer.setInterval(500)
        self.playback_progress_timer.timeout.connect(self._update_playback_slider)

        self.setup_ui()
        self.setup_connections()
        self.logger.info("✅ IQManagerWidget creado")

    # ──────────────────────────────────────────────────────────────────────
    # CONFIGURACIÓN DE UI
    # ──────────────────────────────────────────────────────────────────────

    def setup_ui(self):
        self.spinBox_record_duration.setRange(1, 3600)
        self.spinBox_record_duration.setValue(10)
        self.spinBox_record_size.setRange(10, 102400)
        self.spinBox_record_size.setValue(100)
        self.spinBox_record_size.setSuffix(" MB")

        self.radio_record_continuous.toggled.connect(self._on_record_mode_changed)
        self.radio_record_time.toggled.connect(self._on_record_mode_changed)
        self.radio_record_size.toggled.connect(self._on_record_mode_changed)
        self._on_record_mode_changed()

        self._add_ram_cache_controls()

        self.spinBox_play_speed.setRange(1, 100)
        self.spinBox_play_speed.setValue(1)
        self._set_playback_ui_state(False)

        # ===== NUEVO: Añadir indicador de modo =====
        self.label_mode_indicator = QLabel("📻 MODO: LIVE")
        self.label_mode_indicator.setStyleSheet("""
            QLabel {
                color: #00ff00;
                font-weight: bold;
                font-size: 10pt;
                background-color: #1a1a1a;
                padding: 4px 8px;
                border: 1px solid #00ff00;
                border-radius: 4px;
            }
        """)

    def _add_ram_cache_controls(self):
        if hasattr(self, 'groupBox_mode_record'):
            layout = self.groupBox_mode_record.layout()
            self.checkBox_ram_cache = QCheckBox("USAR CACHE EN RAM (2GB)")
            self.checkBox_ram_cache.setChecked(False)
            self.checkBox_ram_cache.setVisible(False)
            layout.addWidget(self.checkBox_ram_cache)

    def setup_connections(self):
        self.pushButton_record_start.clicked.connect(self._on_record_start_clicked)
        self.pushButton_record_stop.clicked.connect(self._on_record_stop_clicked)
        self.pushButton_open_folder.clicked.connect(self._open_recordings_folder)

        self.pushButton_play_open.clicked.connect(self._on_play_open_clicked)
        self.pushButton_play_play.clicked.connect(self._on_play_play_clicked)
        self.pushButton_play_pause.clicked.connect(self._on_play_pause_clicked)
        self.pushButton_play_stop.clicked.connect(self._on_play_stop_clicked)
        self.pushButton_play_loop.toggled.connect(self._on_play_loop_toggled)
        self.horizontalSlider_play.sliderMoved.connect(self._on_seek)

    # ──────────────────────────────────────────────────────────────────────
    # API PÚBLICA
    # ──────────────────────────────────────────────────────────────────────

    def set_controller(self, controller):
        """
        FIX BUG 2: conecta playback_requested al controller en el mismo acto
        que se guarda la referencia.
        """
        self.main_controller = controller

        if hasattr(controller, 'on_playback_requested'):
            # Desconectar conexiones previas para evitar duplicados
            try:
                self.playback_requested.disconnect()
            except TypeError:
                pass  # No estaba conectada
            self.playback_requested.connect(controller.on_playback_requested)
            self.logger.info("✅ playback_requested → controller.on_playback_requested")
        else:
            self.logger.error("❌ controller no tiene on_playback_requested")

    def set_rf_info(self, freq_mhz: float, sample_rate: float):
        """
        FIX BUG 10: único punto de actualización de freq y SR.
        Llamar desde rf_controller al cambiar frecuencia o sample rate.
        """
        self.current_freq        = freq_mhz
        self.current_sample_rate = sample_rate
        if hasattr(self, 'label_record_freq'):
            self.label_record_freq.setText(f"{freq_mhz:.3f} MHz")

    def on_capture_started(self, recording_buffer):
        """
        Llamado por rf_controller._create_buffers() con el recording_ring_buffer.
        Habilita el botón GRABAR.
        """
        self.is_capturing     = True
        self.recording_buffer = recording_buffer

        # Sincronizar info RF
        if self.main_controller and hasattr(self.main_controller, 'bladerf'):
            bf = self.main_controller.bladerf
            if bf:
                self.set_rf_info(bf.frequency / 1e6, bf.sample_rate)

        slots = recording_buffer.num_buffers
        spb   = recording_buffer.samples_per_buffer
        self.logger.info(
            f"🎤 Captura iniciada — recording buffer: "
            f"{slots} slots × {spb} muestras"
        )

    def on_capture_stopped(self):
        """Llamado cuando la captura en vivo termina."""
        self.is_capturing     = False
        self.recording_buffer = None
        if self.recorder and self.recorder.is_recording:
            self.recorder.stop_recording()
        self.logger.info("⏹ Captura detenida")

    def set_playback_playing(self, playing: bool):
        self._set_playback_ui_playing(playing)
        if playing:
            self.playback_progress_timer.start()
        else:
            self.playback_progress_timer.stop()

    def set_playback_state(self, file_loaded: bool):
        self._set_playback_ui_state(file_loaded)

    # ──────────────────────────────────────────────────────────────────────
    # GRABACIÓN
    # ──────────────────────────────────────────────────────────────────────

    def _on_record_mode_changed(self):
        is_time = self.radio_record_time.isChecked()
        is_size = self.radio_record_size.isChecked()
        self.spinBox_record_duration.setEnabled(is_time)
        self.spinBox_record_size.setEnabled(is_size)

    def _get_current_mode_string(self):
        if self.radio_record_time.isChecked():
            return f"TIME{self.spinBox_record_duration.value()}s"
        elif self.radio_record_size.isChecked():
            return f"SIZE{self.spinBox_record_size.value()}MB"
        return "CONT"

    def _on_record_start_clicked(self):
        if not self.is_capturing or self.recording_buffer is None:
            QMessageBox.warning(
                self, "Sin captura activa",
                "Debe iniciar la captura en vivo antes de grabar.\n\n"
                "1. Configure los parámetros RF\n"
                "2. Presione INICIAR\n"
                "3. Luego inicie la grabación"
            )
            return

        if self.recorder and self.recorder.is_recording:
            return

        timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode_str     = self._get_current_mode_string()
        sr_str       = f"{self.current_sample_rate/1e6:.0f}MSPS"
        os.makedirs("recordings", exist_ok=True)
        filename     = (
            f"recordings/IQ_{self.current_freq:.0f}MHz_"
            f"{sr_str}_{mode_str}_{timestamp}.bin"
        )

        mode          = 'continuous'
        time_limit    = 0
        size_limit_mb = 0
        if self.radio_record_time.isChecked():
            mode       = 'time'
            time_limit = self.spinBox_record_duration.value()
        elif self.radio_record_size.isChecked():
            mode          = 'size'
            size_limit_mb = self.spinBox_record_size.value()

        self.recorder = IQRecorder(
            self.recording_buffer,
            self.current_sample_rate,
            self.current_freq
        )
        self.recorder.configure_recording(filename, mode, time_limit, size_limit_mb)
        self.recorder.recording_started.connect(self._on_recorder_started)
        self.recorder.recording_stopped.connect(self._on_recorder_stopped)
        self.recorder.stats_updated.connect(self._update_recording_ui)

        self.recorder.start_recording()

        self.pushButton_record_start.setEnabled(False)
        self.pushButton_record_stop.setEnabled(True)
        self.ui_update_timer.start()
        self.logger.info(f"⏺ Grabación: {filename}")

    def _on_record_stop_clicked(self):
        if self.recorder and self.recorder.is_recording:
            self.recorder.stop_recording()

    def _on_recorder_started(self, filename: str):
        self.label_record_filename.setText(os.path.basename(filename))
        self._set_record_status(True)

    def _on_recorder_stopped(self):
        self.pushButton_record_start.setEnabled(True)
        self.pushButton_record_stop.setEnabled(False)
        self.ui_update_timer.stop()
        self._set_record_status(False)
        self.logger.info("⏹ Grabación completada")

    def _update_recording_ui(self, stats: dict):
        """Slot de stats_updated del recorder."""
        self.label_record_size.setText(f"{stats['file_size_mb']:.1f} MB")
        self.label_record_time.setText(f"{stats['elapsed_time']:.0f} s")
        self._set_record_status(True)

    def _update_ui_from_recorder(self):
        """
        FIX BUG 9: timer de respaldo — obtiene stats del recorder directamente
        en caso de que stats_updated no haya llegado.
        """
        if not (self.recorder and self.recorder.is_recording):
            return
        with self.recorder.stats_lock:
            elapsed  = self.recorder.start_time
        import time as _time
        elapsed_s = _time.time() - elapsed if elapsed else 0
        mb = self.recorder.bytes_written / 1e6
        self.label_record_size.setText(f"{mb:.1f} MB")
        self.label_record_time.setText(f"{elapsed_s:.0f} s")
        self._set_record_status(True)

    def _set_record_status(self, recording: bool):
        if recording:
            self.label_record_status_icon.setText("⏺")
            self.label_record_status_text.setText("GRABANDO")
            self.label_record_status_icon.setStyleSheet("color: #ff4444;")
            self.label_record_status_text.setStyleSheet(
                "color: #ff4444; font-weight: bold;"
            )
        else:
            self.label_record_status_icon.setText("⏹")
            self.label_record_status_text.setText("DETENIDO")
            self.label_record_status_icon.setStyleSheet("color: #888888;")
            self.label_record_status_text.setStyleSheet("color: #888888;")
            self.label_record_filename.setText("-")
            self.label_record_size.setText("0 MB")
            self.label_record_time.setText("0 s")

    # ──────────────────────────────────────────────────────────────────────
    # REPRODUCCIÓN
    # ──────────────────────────────────────────────────────────────────────

    def _on_play_open_clicked(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Abrir grabación IQ", "recordings/",
            "IQ Files (*.bin);;All Files (*)"
        )
        if filename:
            self._load_playback_file(filename)

    '''def _on_play_play_clicked(self):
        """FIX BUG 3: comprueba None, no hasattr."""
        if not self.current_playback_file:
            QMessageBox.warning(self, "Error", "Primero debe abrir un archivo")
            return
        self.playback_requested.emit(self.current_playback_file, True)
        self._set_playback_ui_playing(True)'''


    def _on_play_play_clicked(self):
        """FIX BUG 3: comprueba None, no hasattr."""
        if not self.current_playback_file:
            QMessageBox.warning(self, "Error", "Primero debe abrir un archivo")
            return
        
        # ===== NUEVO: Aplicar velocidad pendiente =====
        # Obtener velocidad actual del spinBox
        current_speed = self.spinBox_play_speed.value()
        self.pending_speed = current_speed
        # =============================================
        
        self.playback_requested.emit(self.current_playback_file, True)
        self._set_playback_ui_playing(True)
    
    def _on_play_pause_clicked(self):
        """Delegar la acción de pausa/reanudación al PlaybackController."""
        controller = self._get_main_controller()
        if not controller:
            return

        if controller.is_playing_back:
            player = getattr(controller, 'player', None)
            if player and getattr(player, 'is_paused', False):
                controller.resume_playback()
            else:
                controller.pause_playback()
        else:
            self.logger.warning("No hay reproducción activa para pausar")

 

    def _on_play_stop_clicked(self):
        """Detiene la reproducción de forma robusta."""
        controller = self._get_main_controller()
        if not controller:
            self.logger.error("No se pudo obtener MainController para detener")
            return

        self.logger.info("⏹ Botón STOP presionado, llamando a controller.stop_playback()")
        controller.stop_playback()
        
        # La UI se actualizará a través de las señales del PlaybackController
        # Pero por si acaso, forzamos un estado visual inmediato
        self._set_playback_ui_state(True)  # Archivo sigue cargado
        self._set_playback_ui_playing(False)
        self.horizontalSlider_play.setValue(0)
        self.playback_progress_timer.stop()

    
    
    '''def _on_play_loop_toggled(self, checked: bool):
        """Delegar el cambio de modo loop al PlaybackController."""
        controller = self._get_main_controller()
        if controller:
            controller.set_loop_mode(checked)'''
    

    def _on_play_loop_toggled(self, checked: bool):
        """Cambia el modo loop."""
        controller = self._get_main_controller()
        if not controller:
            return
        
        self.logger.info(f"🔄 Modo loop: {'activado' if checked else 'desactivado'}")
        
        # Si está reproduciendo, aplicar inmediatamente
        if controller.is_playing_back and hasattr(controller, 'player') and controller.player:
            controller.player.loop = checked
            self.logger.info(f"✅ Loop aplicado en tiempo real")
        else:
            self.logger.info(f"⏳ Loop guardado para próxima reproducción")

    def _on_seek(self, value: int):
        """Seek al mover el slider (rango 0-1000)."""
        player = getattr(self.main_controller, 'player', None)
        if player and player.total_bytes > 0:
            target = int(player.total_bytes * value / 1000)
            player.seek(target)

    def _update_playback_slider(self):
        """
        FIX BUG 8: progress_updated emite (ratio, 1.0), no (pos, total).
        Leemos position y total_bytes directamente del player para el slider.
        """
        player = getattr(self.main_controller, 'player', None)
        if player is None or player.total_bytes == 0:
            return

        ratio = player.position / player.total_bytes
        self.horizontalSlider_play.blockSignals(True)
        self.horizontalSlider_play.setValue(int(ratio * 1000))
        self.horizontalSlider_play.blockSignals(False)

        sr       = getattr(player, 'sample_rate', 2e6)
        elapsed  = player.position / (sr * 4) if sr else 0
        total    = player.total_bytes / (sr * 4) if sr else 0
        self.label_play_status_text.setText(
            f"REPRODUCIENDO  {elapsed:.1f}s / {total:.1f}s"
        )

    def _load_playback_file(self, filename: str):
        self.label_play_filename.setText(os.path.basename(filename))
        self.current_playback_file = filename
        self.horizontalSlider_play.setValue(0)

        meta_file = filename.replace('.bin', '.meta')
        if os.path.exists(meta_file):
            self._load_metadata_file(meta_file)
        else:
            self._set_default_metadata(filename)

        self._set_playback_ui_state(True)
        
        self._update_playback_duration_estimate()


    def _load_metadata_file(self, meta_file: str):
        try:
            with open(meta_file, 'r') as f:
                content = f.read()
            lines = content.splitlines()
            self.label_play_metadata.setText('\n'.join(lines[:3]))
            for line in lines:
                if 'Frequency:'   in line:
                    self.label_play_freq.setText(line.split(':', 1)[1].strip())
                elif 'Sample Rate:' in line:
                    self.label_play_sr.setText(line.split(':', 1)[1].strip())
                elif 'Duration:'    in line:
                    self.label_play_duration.setText(line.split(':', 1)[1].strip())
                elif 'Mode:'        in line:
                    self.label_play_mode.setText(line.split(':', 1)[1].strip())
        except Exception as exc:
            self.logger.error(f"Error leyendo metadata: {exc}")
            self.label_play_metadata.setText("Error leyendo metadata")

    def _set_default_metadata(self, filename: str):
        """FIX BUG 11: duración correcta = bytes / (SR × 4)."""
        self.label_play_metadata.setText("Sin metadata")
        file_bytes  = os.path.getsize(filename)
        sr          = self.current_sample_rate
        duration_s  = file_bytes / (sr * 4) if sr > 0 else 0
        self.label_play_freq.setText(f"{self.current_freq:.3f} MHz")
        self.label_play_sr.setText(f"{sr/1e6:.2f} MHz")
        self.label_play_duration.setText(f"{duration_s:.1f} s")
        self.label_play_mode.setText(f"{file_bytes/1e6:.1f} MB")

    def _set_playback_ui_state(self, file_loaded: bool):
        self.pushButton_play_play.setEnabled(file_loaded)
        self.pushButton_play_pause.setEnabled(False)
        self.pushButton_play_stop.setEnabled(False)
        self.horizontalSlider_play.setEnabled(file_loaded)
        self.spinBox_play_speed.setEnabled(file_loaded)
        self.pushButton_play_loop.setEnabled(file_loaded)
        if not file_loaded:
            self.label_play_status_icon.setText("⏹")
            self.label_play_status_text.setText("DETENIDO")
            self.label_play_status_icon.setStyleSheet("color: #888888;")
            self.label_play_status_text.setStyleSheet("color: #888888;")

    def _set_playback_ui_playing(self, playing: bool):
        self.pushButton_play_play.setEnabled(not playing)
        self.pushButton_play_pause.setEnabled(playing)
        self.pushButton_play_stop.setEnabled(playing)
        if playing:
            self.label_play_status_icon.setText("▶")
            self.label_play_status_text.setText("REPRODUCIENDO")
            self.label_play_status_icon.setStyleSheet("color: #00ff00;")
            self.label_play_status_text.setStyleSheet(
                "color: #00ff00; font-weight: bold;"
            )
            self.pushButton_play_pause.setText("⏸ PAUSE")
        else:
            self.label_play_status_icon.setText("⏹")
            self.label_play_status_text.setText("DETENIDO")
            self.label_play_status_icon.setStyleSheet("color: #888888;")
            self.label_play_status_text.setStyleSheet("color: #888888;")

    # ──────────────────────────────────────────────────────────────────────
    # UTILIDADES
    # ──────────────────────────────────────────────────────────────────────

    def _open_recordings_folder(self):
        import subprocess, platform
        folder = os.path.abspath("recordings")
        os.makedirs(folder, exist_ok=True)
        if platform.system() == "Windows":
            os.startfile(folder)
        elif platform.system() == "Darwin":
            subprocess.run(["open", folder])
        else:
            subprocess.run(["xdg-open", folder])

    # ──────────────────────────────────────────────────────────────────────
    # CIERRE
    # ──────────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self.recorder and self.recorder.is_recording:
            self.recorder.stop_recording()
            if not self.recorder.wait(3000):
                self.recorder.stop_event.set()
        event.accept()


    def _get_main_controller(self):
        """Obtiene el MainController de forma robusta."""
        if self.main_controller is not None:
            return self.main_controller

        # Si la referencia directa falló, buscar en la jerarquía de padres
        self.logger.warning("Referencia directa a main_controller perdida. Buscando en padres...")
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'is_running') and hasattr(parent, 'playback_ctrl'):
                self.main_controller = parent
                self.logger.info("✅ MainController recuperado de la jerarquía de padres.")
                return self.main_controller
            parent = parent.parent()

        self.logger.error("❌ No se pudo encontrar el MainController.")
        return None
    

    '''def _on_speed_changed(self, value: int):
        """Cambia la velocidad de reproducción."""
        controller = self._get_main_controller()
        if not controller:
            return
        
        
        if not controller.is_playing_back:
            self.logger.info(f"⏩ Velocidad guardada para próxima reproducción: {value}x")
            # Guardar para cuando se inicie reproducción
            self.pending_speed = value
            return
        
        if hasattr(controller, 'player') and controller.player:
            # Convertir a float (el spinBox es int)
            speed = float(value)
            controller.player.speed = speed
            
            # Recalcular throttling en el player
            if hasattr(controller.player, 'configure'):
                controller.player.configure(
                    samples_per_buffer=controller.player.samples_per_buffer,
                    speed=speed,
                    loop=controller.player.loop
                )
            
            self.logger.info(f"⏩ Velocidad cambiada a: {speed}x")
            
            # Actualizar label de duración estimada
            self._update_playback_duration_estimate()'''
    
    # widgets/iq_manager_widget.py

    def _on_speed_changed(self, value: int):
        """Cambia la velocidad de reproducción."""
        controller = self._get_main_controller()
        if not controller:
            return
        
        speed = float(value)
        self.logger.info(f"⏩ Velocidad seleccionada: {speed}x")
        
        # Actualizar estimación de duración
        self._update_playback_duration_estimate()
        
        # Si está reproduciendo, aplicar inmediatamente
        if controller.is_playing_back and hasattr(controller, 'player') and controller.player:
            controller.player.speed = speed
            
            # Reconfigurar throttling
            if hasattr(controller.player, 'configure'):
                controller.player.configure(
                    samples_per_buffer=controller.player.samples_per_buffer,
                    speed=speed,
                    loop=controller.player.loop
                )
            self.logger.info(f"✅ Velocidad aplicada en tiempo real: {speed}x")
        else:
            self.logger.info(f"⏳ Velocidad {speed}x guardada para próxima reproducción")

    def _update_playback_duration_estimate(self):
        """Actualiza la etiqueta de duración con la velocidad actual."""
        if not self.current_playback_file:
            return
        
        try:
            import os
            file_size = os.path.getsize(self.current_playback_file)
            
            # Obtener sample rate (del metadata o del widget)
            sr = self.current_sample_rate
            if sr <= 0:
                sr = 2e6  # Fallback
            
            duration_sec = file_size / (sr * 4)
            speed = self.spinBox_play_speed.value()
            estimated_sec = duration_sec / speed
            
            self.label_play_duration.setText(
                f"{duration_sec:.1f} s ({speed}x = {estimated_sec:.1f} s)"
            )
        except Exception as e:
            self.logger.error(f"Error calculando duración: {e}")

    # widgets/iq_manager_widget.py

    def update_mode_indicator(self, mode: str):
        """Actualiza el indicador de modo (LIVE/PLAY)."""
        if mode == "live":
            self.label_mode_indicator.setText("📻 MODO: LIVE")
            self.label_mode_indicator.setStyleSheet("""
                QLabel {
                    color: #00ff00;
                    font-weight: bold;
                    font-size: 10pt;
                    background-color: #1a1a1a;
                    padding: 4px 8px;
                    border: 1px solid #00ff00;
                    border-radius: 4px;
                }
            """)
        else:  # play
            self.label_mode_indicator.setText("🎬 MODO: PLAY")
            self.label_mode_indicator.setStyleSheet("""
                QLabel {
                    color: #ffaa00;
                    font-weight: bold;
                    font-size: 10pt;
                    background-color: #1a1a1a;
                    padding: 4px 8px;
                    border: 1px solid #ffaa00;
                    border-radius: 4px;
                }
            """)
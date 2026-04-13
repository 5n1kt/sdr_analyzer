# widgets/iq_manager_widget.py
# -*- coding: utf-8 -*-



import os
import re
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
        self.ui_update_timer.timeout.connect(self._update_ui_from_recorder)

        # Timer de progreso de reproducción (~30 Hz para slider suave)
        self.playback_progress_timer = QTimer()
        self.playback_progress_timer.setInterval(100)
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
        self.spinBox_play_speed.valueChanged.connect(self._on_speed_changed)
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
        
        # Añadir al layout si existe
        if hasattr(self, 'horizontalLayout_mode'):
            self.horizontalLayout_mode.insertWidget(0, self.label_mode_indicator)

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
        """Establece la referencia al controlador principal y conecta señales."""
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
        """Actualiza información RF para grabación."""
        self.current_freq = freq_mhz
        self.current_sample_rate = sample_rate
        if hasattr(self, 'label_record_freq'):
            self.label_record_freq.setText(f"{freq_mhz:.3f} MHz")

    def on_capture_started(self, recording_buffer):
        """Llamado cuando la captura en vivo comienza."""
        self.is_capturing = True
        self.recording_buffer = recording_buffer

        # Sincronizar info RF
        if self.main_controller and hasattr(self.main_controller, 'bladerf'):
            bf = self.main_controller.bladerf
            if bf:
                self.set_rf_info(bf.frequency / 1e6, bf.sample_rate)

        slots = recording_buffer.num_buffers
        spb = recording_buffer.samples_per_buffer
        self.logger.info(
            f"🎤 Captura iniciada — recording buffer: "
            f"{slots} slots × {spb} muestras"
        )

    def on_capture_stopped(self):
        """Llamado cuando la captura en vivo termina."""
        self.is_capturing = False
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

    '''def _on_record_start_clicked(self):
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

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode_str = self._get_current_mode_string()
        sr_str = f"{self.current_sample_rate/1e6:.0f}MSPS"
        os.makedirs("recordings", exist_ok=True)
        filename = (
            f"recordings/IQ_{self.current_freq:.0f}MHz_"
            f"{sr_str}_{mode_str}_{timestamp}.bin"
        )

        mode = 'continuous'
        time_limit = 0
        size_limit_mb = 0
        if self.radio_record_time.isChecked():
            mode = 'time'
            time_limit = self.spinBox_record_duration.value()
        elif self.radio_record_size.isChecked():
            mode = 'size'
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
        self.logger.info(f"⏺ Grabación: {filename}")'''
    
    def _on_record_start_clicked(self):
        """Inicia la grabación con formato SigMF y compatibilidad con .bin"""
        
        # ===== VERIFICAR QUE HAY CAPTURA ACTIVA =====
        if not self.is_capturing or self.recording_buffer is None:
            QMessageBox.warning(
                self, "Sin captura activa",
                "Debe iniciar la captura en vivo antes de grabar.\n\n"
                "1. Configure los parámetros RF\n"
                "2. Presione INICIAR\n"
                "3. Luego inicie la grabación"
            )
            return

        # ===== EVITAR GRABACIONES MÚLTIPLES =====
        if self.recorder and self.recorder.is_recording:
            self.logger.warning("⚠️ Ya hay una grabación en curso")
            return

        # ===== OBTENER VALORES REALES DEL SDR EN ESTE MOMENTO =====
        real_sample_rate = self.current_sample_rate  # fallback
        real_freq = self.current_freq  # fallback en MHz
        
        if self.main_controller and hasattr(self.main_controller, 'bladerf'):
            bladerf = self.main_controller.bladerf
            if bladerf:
                real_sample_rate = bladerf.sample_rate
                real_freq = bladerf.frequency / 1e6  # Convertir Hz a MHz
                self.logger.info(f"📡 Sample rate real del SDR: {real_sample_rate/1e6:.2f} MSPS")
                self.logger.info(f"📡 Frecuencia real del SDR: {real_freq:.3f} MHz")
        else:
            self.logger.warning("⚠️ No se pudo obtener configuración real del SDR, usando valores actuales")
        
        # ===== VALIDAR VALORES RAZONABLES =====
        if real_sample_rate <= 0:
            real_sample_rate = 2e6  # fallback a 2 MSPS
            self.logger.warning(f"⚠️ Sample rate inválido, usando {real_sample_rate/1e6:.1f} MSPS")
        
        if real_freq < 1:
            real_freq = 100.0  # fallback a 100 MHz
            self.logger.warning(f"⚠️ Frecuencia inválida, usando {real_freq:.1f} MHz")
        
        # ===== CONFIGURAR LÍMITES DE GRABACIÓN =====
        mode = 'continuous'
        time_limit = 0
        size_limit_mb = 0
        
        if self.radio_record_time.isChecked():
            mode = 'time'
            time_limit = self.spinBox_record_duration.value()
            self.logger.info(f"⏱ Modo tiempo: {time_limit} segundos")
        elif self.radio_record_size.isChecked():
            mode = 'size'
            size_limit_mb = self.spinBox_record_size.value()
            self.logger.info(f"📦 Modo tamaño: {size_limit_mb} MB")
        else:
            self.logger.info("🔄 Modo continuo")
        
        # ===== GENERAR NOMBRE DE ARCHIVO =====
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Determinar sufijo según modo
        if mode == 'time':
            mode_str = f"TIME{time_limit}s"
        elif mode == 'size':
            mode_str = f"SIZE{size_limit_mb}MB"
        else:
            mode_str = "CONT"
        
        # Formatear sample rate (redondear a entero para nombre más limpio)
        sr_msps = real_sample_rate / 1e6
        if sr_msps >= 10:
            sr_str = f"{sr_msps:.0f}MSPS"
        else:
            sr_str = f"{sr_msps:.1f}MSPS".replace('.', '')
        
        # Crear directorio si no existe
        os.makedirs("recordings", exist_ok=True)
        
        # Nombre base SIN extensión (SigMF añadirá .sigmf-data y .sigmf-meta)
        base_filename = f"recordings/IQ_{real_freq:.0f}MHz_{sr_str}_{mode_str}_{timestamp}"
        
        self.logger.info(f"📁 Nombre base: {base_filename}")
        
        # ===== CREAR Y CONFIGURAR GRABADOR =====
        try:
            self.recorder = IQRecorder(
                self.recording_buffer,
                real_sample_rate,
                real_freq * 1e6  # Convertir MHz a Hz para SigMF
            )
            
            self.recorder.configure_recording(base_filename, mode, time_limit, size_limit_mb)
            
            # Conectar señales
            self.recorder.recording_started.connect(self._on_recorder_started)
            self.recorder.recording_stopped.connect(self._on_recorder_stopped)
            self.recorder.stats_updated.connect(self._update_recording_ui)
            
            # ===== INICIAR GRABACIÓN =====
            self.recorder.start_recording()
            
            # ===== ACTUALIZAR UI =====
            self.pushButton_record_start.setEnabled(False)
            self.pushButton_record_stop.setEnabled(True)
            self.ui_update_timer.start()
            
            # Mostrar nombre del archivo en UI (usar .bin para compatibilidad visual)
            display_name = f"{base_filename}.bin"
            self.label_record_filename.setText(os.path.basename(display_name))
            
            self.logger.info(f"⏺ Grabación iniciada: {base_filename}.sigmf-data")
            
        except Exception as e:
            self.logger.error(f"❌ Error al iniciar grabación: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self, "Error de Grabación",
                f"No se pudo iniciar la grabación:\n{str(e)}"
            )
            
            # Limpiar estado
            self.recorder = None
            self.pushButton_record_start.setEnabled(True)
            self.pushButton_record_stop.setEnabled(False)

            
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
        """Timer de respaldo para obtener stats del recorder."""
        if not (self.recorder and self.recorder.is_recording):
            return
        with self.recorder.stats_lock:
            elapsed = self.recorder.start_time
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
            "IQ Files (*.bin *.sigmf-data);;All Files (*)"
        )
        if filename:
            # Asegurar que no sea un archivo .meta
            if filename.endswith('.meta'):
                filename = filename.replace('.meta', '.bin')
                if not os.path.exists(filename):
                    filename = filename.replace('.bin', '.sigmf-data')
            
            if os.path.exists(filename):
                self._load_playback_file(filename)
            else:
                QMessageBox.warning(self, "Error", f"No se encontró el archivo de datos:\n{filename}")

    def _on_play_play_clicked(self):
        """Inicia reproducción del archivo cargado."""
        if not self.current_playback_file:
            QMessageBox.warning(self, "Error", "Primero debe abrir un archivo")
            return
        
        # Obtener velocidad actual
        current_speed = self.spinBox_play_speed.value()
        self.pending_speed = current_speed
        
        self.playback_requested.emit(self.current_playback_file, True)
        self._set_playback_ui_playing(True)
    
    def _on_play_pause_clicked(self):
        """Pausa o reanuda la reproducción."""
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

    def _on_play_stop_clicked(self):
        """Detiene la reproducción."""
        controller = self._get_main_controller()
        if not controller:
            self.logger.error("No se pudo obtener MainController para detener")
            return

        self.logger.info("⏹ Botón STOP presionado")
        controller.stop_playback()
        
        # Actualizar UI
        self._set_playback_ui_state(True)
        self._set_playback_ui_playing(False)
        self.horizontalSlider_play.setValue(0)
        self.playback_progress_timer.stop()
        self.pushButton_play_pause.setText("⏸ PAUSE")

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

    def _update_playback_slider(self):
        """
        Actualiza el slider de progreso.
        CORRECCIÓN: Maneja correctamente el ratio de progreso.
        """
        player = getattr(self.main_controller, 'player', None)
        if player is None or player.total_bytes == 0:
            return
        
        # Calcular ratio de progreso
        if hasattr(player, 'position') and player.position > 0:
            ratio = player.position / player.total_bytes
        else:
            ratio = 0
        
        # Actualizar slider sin emitir señales para evitar loops
        self.horizontalSlider_play.blockSignals(True)
        self.horizontalSlider_play.setValue(int(ratio * 1000))
        self.horizontalSlider_play.blockSignals(False)
        
        # Calcular tiempos
        sr = getattr(player, 'sample_rate', 2e6)
        speed = getattr(player, 'speed', 1.0)
        
        if sr > 0 and hasattr(player, 'position'):
            elapsed = player.position / (sr * 4)
            total = player.total_bytes / (sr * 4)
            
            # Tiempo efectivo considerando velocidad
            elapsed_effective = elapsed / speed if speed > 0 else elapsed
            
            self.label_play_status_text.setText(
                f"REPRODUCIENDO  {elapsed_effective:.1f}s / {total:.1f}s ({speed:.0f}x)"
            )
            
            # Actualizar duración en metadata si es necesario
            if hasattr(self, 'label_play_duration'):
                self.label_play_duration.setText(f"{total:.1f} s")

    def _update_playback_duration_estimate(self):
        """Actualiza la etiqueta de duración con la velocidad actual."""
        if not self.current_playback_file:
            return
        
        try:
            file_size = os.path.getsize(self.current_playback_file)
            
            # Obtener sample rate (de metadata o inferido)
            sr = self.current_sample_rate
            if sr <= 0:
                sr = 2e6  # Fallback
            
            duration_sec = file_size / (sr * 4)
            speed = self.spinBox_play_speed.value()
            estimated_sec = duration_sec / speed if speed > 0 else duration_sec
            
            self.label_play_duration.setText(
                f"{duration_sec:.1f} s ({speed}x = {estimated_sec:.1f} s)"
            )
        except Exception as e:
            self.logger.error(f"Error calculando duración: {e}")

    def _load_playback_file(self, filename: str):
        """Carga un archivo para reproducción (debe ser .bin o .sigmf-data)"""
        # Verificar que sea un archivo de datos, no metadata
        if filename.endswith('.meta'):
            filename = filename.replace('.meta', '.bin')
        
        if not os.path.exists(filename):
            self.logger.error(f"❌ Archivo no encontrado: {filename}")
            return
        
        self.label_play_filename.setText(os.path.basename(filename))
        self.current_playback_file = filename
        self.horizontalSlider_play.setValue(0)

        # Buscar metadata asociada
        meta_file = filename.replace('.bin', '.meta')
        if not os.path.exists(meta_file):
            meta_file = filename.replace('.sigmf-data', '.sigmf-meta')
        
        if os.path.exists(meta_file):
            self._load_metadata_file(meta_file)
        else:
            self._set_default_metadata(filename)

        self._set_playback_ui_state(True)
        self._update_playback_duration_estimate()

    def _load_metadata_file(self, meta_file: str):
        """Carga metadata desde archivo .meta."""
        try:
            with open(meta_file, 'r') as f:
                content = f.read()
            lines = content.splitlines()
            self.label_play_metadata.setText('\n'.join(lines[:3]))
            for line in lines:
                if 'Frequency:' in line:
                    self.label_play_freq.setText(line.split(':', 1)[1].strip())
                elif 'Sample Rate:' in line:
                    val = line.split(':', 1)[1].strip()
                    self.label_play_sr.setText(val)
                    # Extraer valor numérico para cálculos
                    try:
                        sr_val = float(val.split()[0])
                        self.current_sample_rate = sr_val * 1e6
                    except:
                        pass
                elif 'Duration:' in line:
                    self.label_play_duration.setText(line.split(':', 1)[1].strip())
                elif 'Mode:' in line:
                    self.label_play_mode.setText(line.split(':', 1)[1].strip())
        except Exception as exc:
            self.logger.error(f"Error leyendo metadata: {exc}")
            self.label_play_metadata.setText("Error leyendo metadata")

    def _set_default_metadata(self, filename: str):
        """Establece metadata por defecto con cálculo de duración correcto."""
        try:
            file_bytes = os.path.getsize(filename)
            
            # Obtener sample_rate
            sr = self.current_sample_rate
            
            # Si el sample_rate es 0 o muy bajo, intentar inferir
            if sr <= 0 or sr < 1e6:
                # Intentar inferir desde el nombre del archivo
                match = re.search(r'(\d+)MSPS', filename, re.IGNORECASE)
                if match:
                    sr = float(match.group(1)) * 1e6
                else:
                    match = re.search(r'(\d+)M', filename, re.IGNORECASE)
                    if match:
                        sr_msps = float(match.group(1))
                        if sr_msps < 100:  # Sample rate razonable
                            sr = sr_msps * 1e6
                        else:
                            sr = 2e6  # Fallback
                    else:
                        sr = 2e6  # Fallback
                        self.logger.warning(f"⚠️ Usando sample_rate por defecto: 2 MSPS")
            
            self.current_sample_rate = sr
            
            # Calcular duración correcta
            duration_s = file_bytes / (sr * 4) if sr > 0 else 0
            
            self.label_play_metadata.setText("Sin metadata (calculado)")
            self.label_play_freq.setText(f"{self.current_freq:.3f} MHz")
            self.label_play_sr.setText(f"{sr/1e6:.2f} MHz")
            self.label_play_duration.setText(f"{duration_s:.1f} s")
            self.label_play_mode.setText(f"{file_bytes/1e6:.1f} MB")
            
            self.logger.info(f"📊 Duración calculada: {duration_s:.1f}s @ {sr/1e6:.1f} MSPS")
            
        except Exception as exc:
            self.logger.error(f"Error en metadata por defecto: {exc}")
            self.label_play_metadata.setText("Error leyendo archivo")

    def _set_playback_ui_state(self, file_loaded: bool):
        """Actualiza UI según si hay archivo cargado."""
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
        """Actualiza UI según estado de reproducción."""
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
            self.pushButton_play_pause.setText("⏸ PAUSE")

    # ──────────────────────────────────────────────────────────────────────
    # UTILIDADES
    # ──────────────────────────────────────────────────────────────────────

    def _open_recordings_folder(self):
        """Abre la carpeta de grabaciones en el explorador."""
        import subprocess, platform
        folder = os.path.abspath("recordings")
        os.makedirs(folder, exist_ok=True)
        if platform.system() == "Windows":
            os.startfile(folder)
        elif platform.system() == "Darwin":
            subprocess.run(["open", folder])
        else:
            subprocess.run(["xdg-open", folder])

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

    # ──────────────────────────────────────────────────────────────────────
    # CIERRE
    # ──────────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Asegura que se detengan grabaciones activas al cerrar."""
        if self.recorder and self.recorder.is_recording:
            self.recorder.stop_recording()
            if not self.recorder.wait(3000):
                self.recorder.stop_event.set()
        event.accept()
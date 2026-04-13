import os
import re
from datetime import datetime
from PyQt5.QtWidgets import (QDockWidget, QFileDialog, QMessageBox,
                              QCheckBox, QProgressBar, QLabel, QApplication)
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

        self._ensure_labels_exist()
        self._verify_labels()

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

        self._is_seeking = False

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

        #self.horizontalSlider_play.sliderMoved.connect(self._on_seek)

        self.horizontalSlider_play.sliderPressed.connect(self._on_seek_start)
        self.horizontalSlider_play.sliderReleased.connect(self._on_seek_end)
        self.horizontalSlider_play.valueChanged.connect(self._on_seek_value_changed)

    # ──────────────────────────────────────────────────────────────────────
    # API PÚBLICA
    # ──────────────────────────────────────────────────────────────────────

    '''def set_controller(self, controller):
        """Establece la referencia al controlador principal y conecta señales."""
        self.main_controller = controller
        self.logger.info("🔗 IQManagerWidget conectado al MainController")

        # Conectar señal de playback
        if hasattr(controller, 'on_playback_requested'):
            try:
                self.playback_requested.disconnect()
            except TypeError:
                pass
            self.playback_requested.connect(controller.on_playback_requested)
            self.logger.info("✅ playback_requested → controller.on_playback_requested")
        
        # ===== CONECTAR SEÑAL DE METADATA DIRECTAMENTE AL PLAYER =====
        # Esto asegura que cuando el player emita metadata, el widget la reciba
        if hasattr(controller, 'player') and controller.player:
            try:
                controller.player.metadata_loaded.disconnect()
            except:
                pass
            controller.player.metadata_loaded.connect(self.update_metadata_display)
            self.logger.info("✅ metadata_loaded conectado directamente al widget")
        
        # También registrar callback en playback_ctrl como respaldo
        if hasattr(controller, 'playback_ctrl'):
            controller.playback_ctrl.set_metadata_callback(self.update_metadata_display)
            self.logger.info("✅ Callback de metadata registrado en playback_ctrl")'''


    def set_controller(self, controller):
        """Establece la referencia al controlador principal y conecta señales."""
        self.main_controller = controller
        self.logger.info("🔗 IQManagerWidget conectado al MainController")

        # Conectar señal de playback
        if hasattr(controller, 'on_playback_requested'):
            try:
                self.playback_requested.disconnect()
            except TypeError:
                pass
            self.playback_requested.connect(controller.on_playback_requested)
            self.logger.info("✅ playback_requested → controller.on_playback_requested")
        
        # ===== CONECTAR CALLBACK DE METADATA =====
        # El playback_ctrl llamará a este método cuando haya metadata
        if hasattr(controller, 'playback_ctrl'):
            controller.playback_ctrl.set_metadata_callback(self.update_metadata_display)
            self.logger.info("✅ Callback de metadata registrado en playback_ctrl")
        
        # También conectar directamente la señal de metadata del player cuando esté disponible
        if hasattr(controller, 'player') and controller.player:
            try:
                controller.player.metadata_loaded.disconnect()
            except:
                pass
            controller.player.metadata_loaded.connect(self.update_metadata_display)
            self.logger.info("✅ metadata_loaded conectado directamente al widget")

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
        """Actualiza UI según estado de reproducción."""
        if playing:
            self.label_play_status_icon.setText("▶")
            self.label_play_status_text.setText("REPRODUCIENDO")
            self.label_play_status_icon.setStyleSheet("color: #00ff00;")
            self.label_play_status_text.setStyleSheet("color: #00ff00; font-weight: bold;")
            self.pushButton_play_pause.setText("⏸ PAUSE")
        else:
            self.label_play_status_icon.setText("⏹")
            self.label_play_status_text.setText("DETENIDO")
            self.label_play_status_icon.setStyleSheet("color: #888888;")
            self.label_play_status_text.setStyleSheet("color: #888888;")
            self.pushButton_play_pause.setText("⏸ PAUSE")

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


    '''def update_metadata_display(self, metadata):
        """
        Método público para actualizar la UI con metadata.
        CORRECCIÓN: Forzar repaint inmediato de todos los labels.
        """
        self.logger.info("=" * 60)
        self.logger.info("📋 update_metadata_display LLAMADO")
        self.logger.info(f"   Metadata keys: {list(metadata.keys())}")
        self.logger.info("=" * 60)
        
        try:
            # Extraer valores con defaults seguros
            freq = metadata.get('frequency', 100.0)
            sr = metadata.get('sample_rate', 2e6)
            duration = metadata.get('duration', 0)
            mode = metadata.get('mode', 'CONT')
            file_size = metadata.get('file_size_mb', 0)
            filename = metadata.get('filename', '')
            timestamp = metadata.get('timestamp', '')
            total_bytes = metadata.get('total_bytes', 0)
            samples = metadata.get('samples', 0)
            
            self.logger.info(f"   Frecuencia: {freq:.3f} MHz")
            self.logger.info(f"   Sample Rate: {sr/1e6:.2f} MHz")
            self.logger.info(f"   Duración: {duration:.1f} s")
            self.logger.info(f"   Modo: {mode}")
            self.logger.info(f"   Tamaño: {file_size:.1f} MB")
            
            # ===== ACTUALIZAR TODOS LOS LABELS CON REPAINT FORZADO =====
            from PyQt5.QtWidgets import QApplication
            
            # Label de nombre de archivo
            if hasattr(self, 'label_play_filename'):
                self.label_play_filename.setText(filename if filename else "-")
                self.label_play_filename.repaint()  # Forzar repaint
                QApplication.processEvents()  # Procesar eventos inmediatamente
            
            # Label de frecuencia
            if hasattr(self, 'label_play_freq'):
                self.label_play_freq.setText(f"{freq:.3f} MHz")
                self.label_play_freq.repaint()
                QApplication.processEvents()
            
            # Label de sample rate
            if hasattr(self, 'label_play_sr'):
                self.label_play_sr.setText(f"{sr/1e6:.2f} MHz")
                self.label_play_sr.repaint()
                QApplication.processEvents()
            
            # Label de duración
            if hasattr(self, 'label_play_duration'):
                self.label_play_duration.setText(f"{duration:.1f} s")
                self.label_play_duration.repaint()
                QApplication.processEvents()
            
            # Label de modo
            if hasattr(self, 'label_play_mode'):
                self.label_play_mode.setText(mode)
                self.label_play_mode.repaint()
                QApplication.processEvents()
            
            # ===== METADATA COMPLETA FORMATEADA =====
            metadata_text = (
                f"📡 Frecuencia: {freq:.3f} MHz\n"
                f"📊 Sample Rate: {sr/1e6:.2f} MHz\n"
                f"⏱️ Duración: {duration:.1f} s\n"
                f"📁 Modo: {mode}\n"
                f"💾 Tamaño: {file_size:.1f} MB\n"
                f"📅 Timestamp: {timestamp[:19] if timestamp else 'N/A'}\n"
                f"🔢 Muestras: {samples/1e6:.1f}M"
            )
            
            if hasattr(self, 'label_play_metadata'):
                self.label_play_metadata.setText(metadata_text)
                self.label_play_metadata.repaint()
                QApplication.processEvents()
            
            # ===== FORZAR ACTUALIZACIÓN DE LA UI COMPLETA =====
            self.update()  # Actualizar el widget completo
            QApplication.processEvents()  # Procesar todos los eventos pendientes
            
            self.logger.info("✅ UI actualizada correctamente (repaint forzado)")
            
        except Exception as e:
            self.logger.error(f"❌ Error actualizando UI: {e}")
            import traceback
            traceback.print_exc()'''


    def update_metadata_display(self, metadata):
        """
        Método público para actualizar la UI con metadata.
        CORRECCIÓN: Actualiza TODOS los labels y formatea correctamente.
        """
        self.logger.info("=" * 60)
        self.logger.info("📋 update_metadata_display LLAMADO")
        self.logger.info(f"   Metadata keys: {list(metadata.keys())}")
        self.logger.info("=" * 60)
        
        try:
            # Extraer valores con defaults seguros
            freq = metadata.get('frequency', 100.0)
            sr = metadata.get('sample_rate', 2e6)
            duration = metadata.get('duration', 0)
            mode = metadata.get('mode', 'CONT')
            file_size = metadata.get('file_size_mb', 0)
            filename = metadata.get('filename', '')
            timestamp = metadata.get('timestamp', '')
            total_bytes = metadata.get('total_bytes', 0)
            samples = metadata.get('samples', 0)
            
            self.logger.info(f"   Frecuencia: {freq:.3f} MHz")
            self.logger.info(f"   Sample Rate: {sr/1e6:.2f} MHz")
            self.logger.info(f"   Duración: {duration:.1f} s")
            self.logger.info(f"   Modo: {mode}")
            self.logger.info(f"   Tamaño: {file_size:.1f} MB")
            
            # ===== ACTUALIZAR TODOS LOS LABELS =====
            # Label de nombre de archivo
            if hasattr(self, 'label_play_filename'):
                self.label_play_filename.setText(filename if filename else "-")
            
            # Label de frecuencia (formato legible)
            if hasattr(self, 'label_play_freq'):
                self.label_play_freq.setText(f"{freq:.3f} MHz")
            
            # Label de sample rate (formato legible)
            if hasattr(self, 'label_play_sr'):
                self.label_play_sr.setText(f"{sr/1e6:.2f} MHz")
            
            # Label de duración
            if hasattr(self, 'label_play_duration'):
                self.label_play_duration.setText(f"{duration:.1f} s")
            
            # Label de modo
            if hasattr(self, 'label_play_mode'):
                self.label_play_mode.setText(mode)
            
            # ===== METADATA COMPLETA FORMATEADA (LEGIBLE) =====
            # CORRECCIÓN: Formatear texto legible, NO mostrar JSON crudo
            metadata_text = (
                f"📡 Frecuencia: {freq:.3f} MHz\n"
                f"📊 Sample Rate: {sr/1e6:.2f} MHz\n"
                f"⏱️ Duración: {duration:.1f} s\n"
                f"📁 Modo: {mode}\n"
                f"💾 Tamaño: {file_size:.1f} MB\n"
                f"📅 Timestamp: {timestamp[:19] if timestamp else 'N/A'}\n"
                f"🔢 Muestras: {samples/1e6:.1f}M"
            )
            
            if hasattr(self, 'label_play_metadata'):
                self.label_play_metadata.setText(metadata_text)
                self.logger.debug(f"   Metadata text set: {metadata_text[:100]}...")
            
            self.logger.info("✅ UI actualizada correctamente")
            
        except Exception as e:
            self.logger.error(f"❌ Error actualizando UI: {e}")
            import traceback
            traceback.print_exc()


    def clear_metadata_display(self):
        """
        Limpia todos los labels de metadata.
        CORRECCIÓN: Asegurar que todos los labels se resetear correctamente.
        """
        self.logger.info("=" * 50)
        self.logger.info("🗑️ LIMPIANDO METADATA DISPLAY")
        
        # Limpiar label de nombre de archivo
        if hasattr(self, 'label_play_filename'):
            self.label_play_filename.setText("")
            self.logger.debug("   label_play_filename limpiado")
        
        # Limpiar label de frecuencia
        if hasattr(self, 'label_play_freq'):
            self.label_play_freq.setText("-")
            self.logger.debug("   label_play_freq limpiado")
        
        # Limpiar label de sample rate
        if hasattr(self, 'label_play_sr'):
            self.label_play_sr.setText("-")
            self.logger.debug("   label_play_sr limpiado")
        
        # Limpiar label de duración
        if hasattr(self, 'label_play_duration'):
            self.label_play_duration.setText("-")
            self.logger.debug("   label_play_duration limpiado")
        
        # Limpiar label de modo
        if hasattr(self, 'label_play_mode'):
            self.label_play_mode.setText("-")
            self.logger.debug("   label_play_mode limpiado")
        
        # Limpiar metadata text
        if hasattr(self, 'label_play_metadata'):
            self.label_play_metadata.setText("Cargando archivo...")
            self.logger.debug("   label_play_metadata limpiado")
        
        # Resetear slider
        if hasattr(self, 'horizontalSlider_play'):
            self.horizontalSlider_play.blockSignals(True)
            self.horizontalSlider_play.setValue(0)
            self.horizontalSlider_play.blockSignals(False)
            self.logger.debug("   slider resetado")
        
        # Resetear estado de reproducción
        if hasattr(self, 'label_play_status_text'):
            self.label_play_status_text.setText("DETENIDO")
        
        self.logger.info("✅ Metadata display limpiado correctamente")
        self.logger.info("=" * 50)

    def _on_play_open_clicked(self):
        """Abre un archivo para reproducción."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Abrir grabación IQ", "recordings/",
            "IQ Files (*.bin *.sigmf-data);;All Files (*)"
        )
        if filename:
            # ===== LIMPIAR METADATA PRIMERO =====
            self.clear_metadata_display()
            self.logger.info(f"📂 Metadata limpiada, cargando: {filename}")
            
            # Asegurar que no sea un archivo .meta
            if filename.endswith('.meta'):
                filename = filename.replace('.meta', '.bin')
                if not os.path.exists(filename):
                    filename = filename.replace('.bin', '.sigmf-data')
            
            if os.path.exists(filename):
                self._load_playback_file(filename)
            else:
                QMessageBox.warning(self, "Error", f"No se encontró el archivo de datos:\n{filename}")
                # Restaurar estado si falla
                self.label_play_metadata.setText("Error al cargar archivo")

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

            # Inyectar referencia al IQProcessor para que el recorder pueda
            # llamar attach/detach del recording_buffer directamente, sin
            # depender del event loop Qt (que puede llegar con segundos de retraso)
            if self.main_controller is not None:
                iq_proc = getattr(self.main_controller, 'iq_processor', None)
                if iq_proc is not None:
                    self.recorder.set_processor(iq_proc)
                    self.logger.info("✅ IQProcessor inyectado en recorder")
                else:
                    self.logger.warning("⚠️ iq_processor no disponible en main_controller")

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
        # El detach del IQProcessor ya ocurrió dentro de IQRecorderSimple.run()
        # antes de emitir esta señal — no hay race condition con el overflow.
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
        
        # ===== RESETEAR SLIDER A 0 =====
        self.horizontalSlider_play.blockSignals(True)
        self.horizontalSlider_play.setValue(0)
        self.horizontalSlider_play.blockSignals(False)
        
        self.playback_progress_timer.stop()
        self.pushButton_play_pause.setText("⏸ PAUSE")
        
        # Resetear banderas de seek
        self._is_seeking = False

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


    def _on_seek_start(self):
        """
        El usuario comenzó a arrastrar el slider.
        Pausamos la reproducción automáticamente para que el seek sea suave.
        """
        self.logger.info("🎚️ Seek iniciado - pausando reproducción")
        
        # Pausar si está reproduciendo
        controller = self._get_main_controller()
        if controller and controller.is_playing_back:
            # Guardar estado para reanudar después
            self._was_playing_before_seek = True
            controller.pause_playback()
        else:
            self._was_playing_before_seek = False
        
        # Marcar que estamos en modo seek
        self._is_seeking = True

    def _on_seek_value_changed(self, value):
        """
        El usuario movió el slider (durante el arrastre).
        Actualizamos la posición en tiempo real sin aplicar seek todavía.
        """
        if not self._is_seeking:
            return
        
        # Actualizar solo la visualización del tiempo
        self._update_time_from_slider_value(value)

    def _on_seek_end(self):
        """
        El usuario soltó el slider - aplicar el seek a la posición seleccionada.
        """
        self.logger.info("🎚️ Seek finalizado - aplicando nueva posición")
        
        controller = self._get_main_controller()
        if not controller or not controller.player:
            self._is_seeking = False
            return
        
        # Obtener valor final del slider (0-1000)
        final_value = self.horizontalSlider_play.value()
        
        # Calcular posición en bytes
        player = controller.player
        if player.total_bytes > 0:
            target_position = int(player.total_bytes * final_value / 1000)
            # Alinear al límite de buffer para evitar lecturas parciales
            aligned_position = (target_position // player.bytes_per_buffer) * player.bytes_per_buffer
            aligned_position = max(0, min(aligned_position, player.total_bytes - player.bytes_per_buffer))
            
            self.logger.info(f"🎯 Seek a posición: {aligned_position} bytes ({final_value/10:.1f}%)")
            
            # Aplicar seek
            player.seek(aligned_position)
            
            # Si estaba reproduciendo antes del seek, reanudar
            if self._was_playing_before_seek:
                self.logger.info("▶ Reanudando reproducción después de seek")
                controller.resume_playback()
        
        self._is_seeking = False


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

    def _update_time_from_slider_value(self, slider_value):
        """
        Actualiza las etiquetas de tiempo basado en la posición del slider.
        Usado durante el arrastre para feedback visual inmediato.
        """
        controller = self._get_main_controller()
        if not controller or not controller.player:
            return
        
        player = controller.player
        if player.total_bytes > 0:
            ratio = slider_value / 1000
            position_bytes = int(player.total_bytes * ratio)
            
            # Calcular tiempos
            sr = player.sample_rate
            speed = getattr(player, 'speed', 1.0)
            
            if sr > 0:
                total_seconds = player.total_bytes / (sr * 4)
                current_seconds = position_bytes / (sr * 4)
                current_effective = current_seconds / speed if speed > 0 else current_seconds
                total_effective = total_seconds / speed if speed > 0 else total_seconds
                
                self.label_play_status_text.setText(
                    f"🎚️ SEEK  {current_effective:.1f}s / {total_effective:.1f}s"
                )
    

    '''def _load_playback_file(self, filename):
        """Carga un archivo para reproducción con limpieza previa."""
        self.logger.info(f"📂 _load_playback_file: {filename}")
        
        # Verificar que sea un archivo de datos, no metadata
        if filename.endswith('.meta'):
            filename = filename.replace('.meta', '.bin')
        
        if not os.path.exists(filename):
            self.logger.error(f"❌ Archivo no encontrado: {filename}")
            return
        
        # Actualizar UI
        self.label_play_filename.setText(os.path.basename(filename))
        self.current_playback_file = filename
        self.horizontalSlider_play.setValue(0)
        
        # Mostrar mensaje de carga
        self.label_play_metadata.setText("Cargando archivo...")
        self.label_play_freq.setText("...")
        self.label_play_sr.setText("...")
        self.label_play_duration.setText("...")
        self.label_play_mode.setText("...")
        
        # Forzar actualización de UI
        QApplication.processEvents()
        
        # Buscar metadata asociada
        meta_file = filename.replace('.bin', '.meta')
        if not os.path.exists(meta_file):
            meta_file = filename.replace('.sigmf-data', '.sigmf-meta')
        
        if os.path.exists(meta_file):
            self._load_metadata_file(meta_file)
        else:
            self._set_default_metadata(filename)

        # Habilitar botones de reproducción (PLAY, STOP, LOOP, etc.)
        self._set_playback_ui_state(True)
        self._update_playback_duration_estimate()
        
        # El botón PLAY debe estar habilitado
        self.pushButton_play_play.setEnabled(True)
        self.pushButton_play_pause.setEnabled(False)
        self.pushButton_play_stop.setEnabled(True)
        
        self.logger.info("✅ Archivo cargado, botón PLAY habilitado")'''
    
    # widgets/iq_manager_widget.py

    def _load_playback_file(self, filename):
        """Carga un archivo para reproducción con limpieza previa."""
        self.logger.info(f"📂 _load_playback_file: {filename}")
        
        # Verificar que sea un archivo de datos, no metadata
        if filename.endswith('.meta'):
            filename = filename.replace('.meta', '.bin')
        
        if not os.path.exists(filename):
            self.logger.error(f"❌ Archivo no encontrado: {filename}")
            return
        
        # Actualizar UI
        self.label_play_filename.setText(os.path.basename(filename))
        self.current_playback_file = filename
        self.horizontalSlider_play.setValue(0)
        
        # Mostrar mensaje de carga
        self.label_play_metadata.setText("Cargando archivo...")
        self.label_play_freq.setText("...")
        self.label_play_sr.setText("...")
        self.label_play_duration.setText("...")
        self.label_play_mode.setText("...")
        
        # Forzar actualización de UI
        QApplication.processEvents()
        
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


    def _update_playback_slider(self):
        """
        Actualiza el slider de progreso con cálculo correcto de tiempo.
        """
        # No actualizar si estamos en medio de un seek manual
        if self._is_seeking:
            return
            
        player = getattr(self.main_controller, 'player', None)
        if player is None or player.total_bytes == 0:
            return
        
        # Calcular ratio de progreso
        if hasattr(player, 'position') and player.position > 0:
            ratio = player.position / player.total_bytes
        else:
            ratio = 0
        
        # Actualizar slider
        self.horizontalSlider_play.blockSignals(True)
        self.horizontalSlider_play.setValue(int(ratio * 1000))
        self.horizontalSlider_play.blockSignals(False)
        
        # ===== CORRECCIÓN: Actualizar tiempos con sample_rate correcto =====
        try:
            sr = getattr(player, 'sample_rate', 2e6)
            speed = getattr(player, 'speed', 1.0)
            total_bytes = player.total_bytes
            position = getattr(player, 'position', 0)
            
            if total_bytes > 0 and sr > 0:
                # Cálculo correcto: 4 bytes por muestra compleja (int16 I + int16 Q)
                total_seconds = total_bytes / (sr * 4)
                current_seconds = position / (sr * 4)
                
                # Tiempo efectivo considerando velocidad
                current_effective = current_seconds / speed if speed > 0 else current_seconds
                total_effective = total_seconds / speed if speed > 0 else total_seconds
                
                # Actualizar etiquetas
                if not self._is_seeking:
                    self.label_play_status_text.setText(
                        f"REPRODUCIENDO  {current_effective:.1f}s / {total_effective:.1f}s ({speed:.0f}x)"
                    )
                    self.label_play_duration.setText(f"{total_effective:.1f} s")
                    
                    # Log para debug (solo cada cierto tiempo)
                    if not hasattr(self, '_last_time_log'):
                        self._last_time_log = 0
                    import time
                    now = time.time()
                    if now - self._last_time_log > 2:
                        self.logger.debug(
                            f"⏱️ Progreso: {current_effective:.1f}/{total_effective:.1f}s "
                            f"({current_seconds:.1f}s real @ {sr/1e6:.0f}MHz)"
                        )
                        self._last_time_log = now
                        
        except Exception as e:
            self.logger.debug(f"Error en update de tiempo: {e}")


    def _update_time_labels_respaldo(self, player, ratio):
        """
        Actualiza etiquetas de tiempo como respaldo.
        """
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
                
                # Solo actualizar si no estamos en seek
                if not self._is_seeking:
                    self.label_play_status_text.setText(
                        f"REPRODUCIENDO  {current_effective:.1f}s / {total_effective:.1f}s ({speed:.0f}x)"
                    )
                    self.label_play_duration.setText(f"{total_effective:.1f} s")
        except Exception as e:
            self.logger.debug(f"Error en update de tiempo respaldo: {e}")

    def _update_time_labels_from_player(self, player, ratio):
        """
        Actualiza etiquetas de tiempo usando datos del player.
        """
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
                
                # Solo actualizar si no estamos en seek
                if not self._is_seeking:
                    self.label_play_status_text.setText(
                        f"REPRODUCIENDO  {current_effective:.1f}s / {total_effective:.1f}s ({speed:.0f}x)"
                    )
                    self.label_play_duration.setText(f"{total_effective:.1f} s")
        except Exception as e:
            self.logger.debug(f"Error en update de tiempo: {e}")

    

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

    

    

    def _load_metadata_file(self, meta_file: str):
        """Carga metadata con encoding robusto (utf-8, latin-1, fallback binario)."""
        try:
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
                self.logger.warning("⚠️ Metadata leída con reemplazo de caracteres")

            lines = content.splitlines()
            self.label_play_metadata.setText('\n'.join(lines[:3]))
            for line in lines:
                if 'Frequency:' in line:
                    self.label_play_freq.setText(line.split(':', 1)[1].strip())
                elif 'Sample Rate:' in line:
                    val = line.split(':', 1)[1].strip()
                    self.label_play_sr.setText(val)
                    try:
                        sr_val = float(val.split()[0])
                        self.current_sample_rate = sr_val * 1e6
                    except Exception:
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


    def _ensure_labels_exist(self):
        """
        Asegura que todos los labels necesarios existan en el widget.
        Crea los que falten con nombres consistentes.
        """
        # Lista de labels requeridos y sus valores por defecto
        required_labels = {
            'label_play_filename': '-',
            'label_play_freq': '-',
            'label_play_sr': '-',
            'label_play_duration': '-',
            'label_play_mode': '-',
            'label_play_metadata': 'Sin archivo cargado'
        }
        
        for label_name, default_text in required_labels.items():
            if not hasattr(self, label_name):
                # Crear label si no existe
                from PyQt5.QtWidgets import QLabel
                label = QLabel(default_text)
                setattr(self, label_name, label)
                self.logger.debug(f"✅ Label creado: {label_name}")
            else:
                # Asegurar texto por defecto
                label = getattr(self, label_name)
                if label.text() == '':
                    label.setText(default_text)

    def _verify_labels(self):
        """Verifica que todos los labels necesarios existen."""
        required_labels = ['label_play_filename', 'label_play_freq', 'label_play_sr', 
                        'label_play_duration', 'label_play_mode', 'label_play_metadata']
        
        self.logger.info("🔍 Verificando labels en IQManagerWidget:")
        for label_name in required_labels:
            if hasattr(self, label_name):
                label = getattr(self, label_name)
                self.logger.info(f"   ✅ {label_name}: {label.text() if label else 'None'}")
            else:
                self.logger.warning(f"   ❌ {label_name} NO EXISTE")


    def _on_playback_metadata(self, metadata):
        """
        Slot para metadata_loaded del player.
        CORRECCIÓN: Actualizar directamente la UI con logs para debug.
        """
        self.logger.info("=" * 60)
        self.logger.info("📋 IQManagerWidget._on_playback_metadata EJECUTADO")
        self.logger.info(f"   Metadata: {metadata}")
        self.logger.info("=" * 60)
        
        try:
            # Extraer valores
            freq = metadata.get('frequency', 100.0)
            sr = metadata.get('sample_rate', 2e6)
            duration = metadata.get('duration', 0)
            mode = metadata.get('mode', 'CONT')
            file_size = metadata.get('file_size_mb', 0)
            filename = metadata.get('filename', '-')
            
            self.logger.info(f"   Frecuencia: {freq:.3f} MHz")
            self.logger.info(f"   Sample Rate: {sr/1e6:.2f} MHz")
            self.logger.info(f"   Duración: {duration:.1f} s")
            self.logger.info(f"   Modo: {mode}")
            self.logger.info(f"   Tamaño: {file_size:.1f} MB")
            
            # Actualizar labels
            if hasattr(self, 'label_play_filename'):
                self.label_play_filename.setText(filename)
            else:
                self.logger.warning("⚠️ label_play_filename no existe")
                
            if hasattr(self, 'label_play_freq'):
                self.label_play_freq.setText(f"{freq:.3f} MHz")
                
            if hasattr(self, 'label_play_sr'):
                self.label_play_sr.setText(f"{sr/1e6:.2f} MHz")
                
            if hasattr(self, 'label_play_duration'):
                self.label_play_duration.setText(f"{duration:.1f} s")
                
            if hasattr(self, 'label_play_mode'):
                self.label_play_mode.setText(mode)
            
            # Formatear metadata completa
            metadata_text = (
                f"📡 Frecuencia: {freq:.3f} MHz\n"
                f"📊 Sample Rate: {sr/1e6:.2f} MHz\n"
                f"⏱️ Duración: {duration:.1f} s\n"
                f"📁 Modo: {mode}\n"
                f"💾 Tamaño: {file_size:.1f} MB"
            )
            
            if hasattr(self, 'label_play_metadata'):
                self.label_play_metadata.setText(metadata_text)
            
            self.logger.info("✅ UI actualizada correctamente")
            
        except Exception as e:
            self.logger.error(f"❌ Error actualizando UI con metadata: {e}")
            import traceback
            traceback.print_exc()

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


# widgets/recording_widget.py
# -*- coding: utf-8 -*-

import os
import numpy as np
from datetime import datetime
from PyQt5.QtWidgets import QDockWidget, QFileDialog, QMessageBox
from PyQt5.QtCore import pyqtSignal, QTimer, Qt
from PyQt5.uic import loadUi
import logging

class RecordingWidget(QDockWidget):
    """Widget de control de grabación IQ - Estilo SIGINT profesional"""
    
    # Señales
    recording_started = pyqtSignal(str)  # filename
    recording_stopped = pyqtSignal()
    recording_paused = pyqtSignal()
    recording_resumed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # Referencia al controller (se establece después)
        self.main_controller = None
        
        # Cargar UI
        loadUi('ui/recording_widget.ui', self)
        
        # Variables de estado
        self.is_recording = False
        self.is_paused = False
        self.record_file = None
        self.filename = None
        self.record_start_time = None
        self.bytes_written = 0
        self.sample_rate = 2e6
        self.current_freq = 100.0
        
        # Timer para actualizar información
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_info)
        self.update_timer.setInterval(500)  # 500ms
        
        # Configurar UI
        self.setup_ui()
        
        # Conectar señales
        self.setup_connections()
        
        # Actualizar visibilidad de controles según modo
        self.on_mode_changed(0)
        
        self.logger.info("✅ RecordingWidget creado")
    
    def setup_ui(self):
        """Configura elementos de UI"""
        # Estado inicial
        self.set_recording_state(False)
        
        # Configurar rangos
        self.spinBox_duration.setRange(1, 3600)
        self.spinBox_duration.setValue(10)
        
        self.spinBox_size.setRange(10, 102400)  # 10MB a 100GB
        self.spinBox_size.setValue(100)
        self.spinBox_size.setSuffix(" MB")
    
    def setup_connections(self):
        """Conecta señales"""
        self.pushButton_record.clicked.connect(self.toggle_recording)
        self.comboBox_recording_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.pushButton_open_folder.clicked.connect(self.open_recording_folder)
        self.pushButton_last_recording.clicked.connect(self.play_last_recording)
    
    def set_controller(self, controller):
        """Establece referencia al controller principal"""
        self.main_controller = controller
        self.logger.info("🔗 Controller conectado a RecordingWidget")
    
    def on_mode_changed(self, index):
        """Cambia visibilidad de controles según modo"""
        # 0: Continuo, 1: Por tiempo, 2: Por tamaño
        self.widget_duration.setVisible(index == 1)
        self.widget_size.setVisible(index == 2)
    
    def set_recording_state(self, recording):
        """Actualiza UI según estado de grabación"""
        self.is_recording = recording
        
        if recording:
            self.label_status_icon.setText("⏺")
            self.label_status_text.setText("GRABANDO")
            self.label_status_icon.setStyleSheet("color: #ff4444;")
            self.label_status_text.setStyleSheet("color: #ff4444; font-weight: bold;")
            self.pushButton_record.setText("⏹ DETENER GRABACIÓN")
            self.pushButton_record.setStyleSheet("background-color: #ff4444; color: white;")
            
            # Deshabilitar controles de modo durante grabación
            self.comboBox_recording_mode.setEnabled(False)
            self.spinBox_duration.setEnabled(False)
            self.spinBox_size.setEnabled(False)
        else:
            self.label_status_icon.setText("⏹")
            self.label_status_text.setText("DETENIDO")
            self.label_status_icon.setStyleSheet("color: #888888;")
            self.label_status_text.setStyleSheet("color: #888888;")
            self.pushButton_record.setText("⏺ INICIAR GRABACIÓN")
            self.pushButton_record.setStyleSheet("")
            
            # Habilitar controles de modo
            self.comboBox_recording_mode.setEnabled(True)
            self.on_mode_changed(self.comboBox_recording_mode.currentIndex())
    
    def toggle_recording(self):
        """Inicia/Detiene grabación"""
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()
    
    def start_recording(self):
        """Inicia nueva grabación - VERSIÓN CORREGIDA"""
        try:
            # ===== VERIFICAR QUE HAY CAPTURA ACTIVA =====
            # Usar la referencia al controller almacenada
            if self.main_controller is None:
                # Intentar buscar el controller en la jerarquía
                parent = self.parent()
                while parent is not None:
                    if hasattr(parent, 'is_running'):
                        self.main_controller = parent
                        break
                    parent = parent.parent()
            
            if self.main_controller is None or not hasattr(self.main_controller, 'is_running'):
                QMessageBox.warning(self, "Error", 
                    "No se pudo verificar el estado de la captura.\n\n"
                    "Asegúrese de que el widget esté correctamente inicializado.")
                return
            
            if not self.main_controller.is_running:
                QMessageBox.warning(self, "Error", 
                    "Debe iniciar la captura antes de grabar.\n\n"
                    "1. Configure los parámetros RF\n"
                    "2. Presione 'INICIAR' en la barra superior\n"
                    "3. Luego inicie la grabación")
                return
            # =============================================
            
            # Generar nombre de archivo
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            freq = self.current_freq
            mode = self.comboBox_recording_mode.currentText()
            
            # Crear directorio recordings si no existe
            os.makedirs("recordings", exist_ok=True)
            
            self.filename = f"recordings/IQ_{freq:.0f}MHz_{mode}_{timestamp}.bin"
            
            # Abrir archivo
            self.record_file = open(self.filename, 'wb')
            
            # Guardar metadata
            self.save_metadata()
            
            # Inicializar contadores
            self.bytes_written = 0
            self.record_start_time = datetime.now()
            
            # Actualizar UI
            self.label_filename.setText(os.path.basename(self.filename))
            self.label_freq_current.setText(f"{freq:.3f} MHz")
            self.set_recording_state(True)
            
            # Iniciar timer de actualización
            self.update_timer.start()
            
            # Emitir señal
            self.recording_started.emit(self.filename)
            
            self.logger.info(f"📼 Grabación iniciada: {self.filename}")
            
        except Exception as e:
            self.logger.error(f"Error iniciando grabación: {e}")
            QMessageBox.critical(self, "Error", f"No se pudo iniciar grabación:\n{e}")
    
    def stop_recording(self):
        """Detiene grabación actual"""
        try:
            if self.record_file:
                self.record_file.close()
                self.record_file = None
            
            # Detener timer
            self.update_timer.stop()
            
            # Calcular duración
            if self.record_start_time:
                duration = (datetime.now() - self.record_start_time).total_seconds()
                
                # Actualizar metadata con duración real
                self.update_metadata_duration(duration)
                
                self.logger.info(f"📼 Grabación detenida: {self.filename} ({duration:.1f}s, {self.bytes_written/1e6:.1f}MB)")
            
            # Actualizar UI
            self.set_recording_state(False)
            
            # Emitir señal
            self.recording_stopped.emit()
            
        except Exception as e:
            self.logger.error(f"Error deteniendo grabación: {e}")
    
    def save_metadata(self):
        """Guarda archivo .meta con información de la grabación"""
        try:
            meta_filename = self.filename.replace('.bin', '.meta')
            with open(meta_filename, 'w') as f:
                f.write(f"Filename: {os.path.basename(self.filename)}\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Frequency: {self.current_freq} MHz\n")
                f.write(f"Sample Rate: {self.sample_rate/1e6} MHz\n")
                f.write(f"Mode: {self.comboBox_recording_mode.currentText()}\n")
                f.write(f"Format: int16 IQ interleaved\n")
                f.write(f"Bytes per sample: 4\n")
        except Exception as e:
            self.logger.error(f"Error guardando metadata: {e}")
    
    def update_metadata_duration(self, duration):
        """Actualiza metadata con duración real"""
        try:
            meta_filename = self.filename.replace('.bin', '.meta')
            with open(meta_filename, 'a') as f:
                f.write(f"Duration: {duration:.1f} s\n")
                f.write(f"File size: {self.bytes_written/1e6:.1f} MB\n")
        except Exception as e:
            self.logger.error(f"Error actualizando metadata: {e}")
    
    def write_iq_data(self, iq_data):
        """Escribe datos IQ al archivo (llamado desde controller)"""
        if self.is_recording and not self.is_paused and self.record_file:
            try:
                # Convertir a int16 interleaved
                iq_int16 = np.zeros(iq_data.size * 2, dtype=np.int16)
                iq_int16[0::2] = np.round(iq_data.real * 2048).astype(np.int16)
                iq_int16[1::2] = np.round(iq_data.imag * 2048).astype(np.int16)
                
                # Escribir
                self.record_file.write(iq_int16.tobytes())
                self.bytes_written += iq_int16.nbytes
                
                # Verificar límites según modo
                self.check_limits()
                
            except Exception as e:
                self.logger.error(f"Error escribiendo IQ data: {e}")
                self.stop_recording()
    
    def check_limits(self):
        """Verifica límites de grabación según modo"""
        mode = self.comboBox_recording_mode.currentIndex()
        
        if mode == 1:  # Por tiempo
            if self.record_start_time:
                elapsed = (datetime.now() - self.record_start_time).total_seconds()
                if elapsed >= self.spinBox_duration.value():
                    self.logger.info("⏱ Límite de tiempo alcanzado")
                    self.stop_recording()
        
        elif mode == 2:  # Por tamaño
            size_mb = self.bytes_written / 1e6
            if size_mb >= self.spinBox_size.value():
                self.logger.info("📦 Límite de tamaño alcanzado")
                self.stop_recording()
    
    def update_info(self):
        """Actualiza información en UI durante grabación"""
        if self.is_recording and self.record_start_time:
            elapsed = (datetime.now() - self.record_start_time).total_seconds()
            size_mb = self.bytes_written / 1e6
            
            self.label_size_current.setText(f"{size_mb:.1f} MB")
            self.label_time_current.setText(f"{elapsed:.1f} s")
    
    def open_recording_folder(self):
        """Abre la carpeta de grabaciones"""
        import subprocess
        import platform
        
        folder = os.path.abspath("recordings")
        os.makedirs(folder, exist_ok=True)
        
        if platform.system() == "Windows":
            os.startfile(folder)
        elif platform.system() == "Darwin":  # macOS
            subprocess.run(["open", folder])
        else:  # Linux
            subprocess.run(["xdg-open", folder])
        
        self.logger.info(f"📂 Abriendo carpeta: {folder}")
    
    def play_last_recording(self):
        """Reproduce la última grabación (placeholder)"""
        QMessageBox.information(self, "Reproducir", 
            "Funcionalidad de reproducción en desarrollo.\n\n"
            "Por ahora puedes usar herramientas externas:\n"
            "• GNU Radio (con archivo .bin)\n"
            "• Inspectrum\n"
            "• baudline\n\n"
            f"Última grabación: {self.filename}")
    
    def update_rf_info(self, freq_mhz, sample_rate):
        """Actualiza información RF desde controller"""
        self.current_freq = freq_mhz
        self.sample_rate = sample_rate
        
        if not self.is_recording:
            self.label_freq_current.setText(f"{freq_mhz:.3f} MHz")
    
    def closeEvent(self, event):
        """Asegurar que se cierre el archivo si está grabando"""
        if self.is_recording:
            self.stop_recording()
        event.accept()
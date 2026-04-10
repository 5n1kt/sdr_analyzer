# widgets/audio_widget_compact.py
# -*- coding: utf-8 -*-

from PyQt5.QtWidgets import QDockWidget, QApplication, QLabel
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QPainter, QColor, QBrush, QPen
from PyQt5.uic import loadUi
import logging
import pyaudio


class VUMeterCompact(QLabel):
    """VU Meter compacto de 30px de alto"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = -60  # dB
        self.peak = -60
        self.setMinimumHeight(26)
        self.setMaximumHeight(26)
        
        # Timer para decaimiento del peak
        self.peak_timer = QTimer()
        self.peak_timer.timeout.connect(self._decay_peak)
        self.peak_timer.start(50)
    
    def set_level(self, level_db):
        self.level = max(-60, min(0, level_db))
        if self.level > self.peak:
            self.peak = self.level
        self.update()
    
    def _decay_peak(self):
        if self.peak > -60:
            self.peak = max(-60, self.peak - 0.5)
            self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        
        # Fondo
        painter.fillRect(rect, QColor(30, 30, 30))
        
        # Calcular posición del nivel
        level_pos = int((self.level + 60) / 60 * rect.width())
        level_pos = max(0, min(rect.width(), level_pos))
        
        # Color según nivel
        if self.level < -20:
            color = QColor(0, 255, 0)
        elif self.level < -6:
            color = QColor(255, 255, 0)
        else:
            color = QColor(255, 0, 0)
        
        # Dibujar barra
        painter.fillRect(0, 0, level_pos, rect.height(), color)
        
        # Dibujar peak
        peak_pos = int((self.peak + 60) / 60 * rect.width())
        peak_pos = max(0, min(rect.width(), peak_pos))
        painter.fillRect(peak_pos-2, 0, 4, rect.height(), QColor(255, 255, 255))
        
        # Dibujar texto del nivel
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(rect, Qt.AlignCenter, f"{self.level:.1f} dB")


class AudioWidgetCompact(QDockWidget):
    """Widget de demodulación compacto estilo GQRX"""
    
    # Señales
    mode_changed = pyqtSignal(str)
    volume_changed = pyqtSignal(float)
    squelch_changed = pyqtSignal(float, bool)
    bfo_changed = pyqtSignal(int, bool)  # (freq, enabled)
    filter_changed = pyqtSignal(str, str)  # (lowpass, highpass)
    mute_toggled = pyqtSignal(bool)
    test_tone_requested = pyqtSignal()

    # ===== NUEVA SEÑAL =====
    demodulator_toggled = pyqtSignal(bool)  # True para activar, False para desactivar
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # Cargar UI
        loadUi('ui/audio_widget_compact.ui', self)
        
        # Reemplazar el label_vu con nuestro VUMeterCompact
        self.vu_meter = VUMeterCompact()
        self.frame_vu_meter.layout().replaceWidget(self.label_vu, self.vu_meter)
        self.label_vu.deleteLater()
        
        # Configurar valores iniciales
        self.setup_ui()
        self.setup_connections()
        
        # Estado
        self.is_active = False
        self.current_mode = 'FM'

        # ===== NUEVO: Estado del demodulador =====
        self.demodulator_enabled = True  # Activo por defecto
        
        # Cargar dispositivos de audio
        self.load_audio_devices()
        
        self.logger.info("✅ AudioWidgetCompact creado")
    
    def setup_ui(self):
        """Configura valores iniciales de la UI"""
        # Sliders
        self.horizontalSlider_volume.setValue(80)
        self.horizontalSlider_squelch.setValue(10)
        
        # BFO group inicialmente deshabilitado
        self.groupBox_bfo.setChecked(False)
        self.spinBox_bfo.setEnabled(False)
        self.checkBox_bfo_auto.setEnabled(False)
        
        # Estado inicial squelch
        self.update_squelch_indicator(False)
        
        # Mute button
        self.pushButton_mute.setChecked(False)

        # ===== NUEVO: Configurar botón de demodulador =====
        # Asumimos que el botón en el UI se llama 'pushButton_demodulator'
        self.pushButton_demodulator.setCheckable(True)
        self.pushButton_demodulator.setChecked(True)  # Activo por defecto
        self.pushButton_demodulator.setText("🔊 DEMOD. ON")
        self.pushButton_demodulator.setStyleSheet("""
            QPushButton:checked {
                background-color: #00aa00;
                color: white;
                font-weight: bold;
            }
            QPushButton:!checked {
                background-color: #aa0000;
                color: white;
                font-weight: bold;
            }
        """)
    
    def setup_connections(self):
        """Conecta señales de la UI"""
        self.comboBox_mode.currentTextChanged.connect(self.on_mode_changed)
        self.horizontalSlider_volume.valueChanged.connect(self.on_volume_changed)
        self.horizontalSlider_squelch.valueChanged.connect(self.on_squelch_changed)
        self.checkBox_squelch_enable.toggled.connect(self.on_squelch_enabled)
        self.pushButton_mute.toggled.connect(self.on_mute_toggled)
        self.groupBox_bfo.toggled.connect(self.on_bfo_toggled)
        self.spinBox_bfo.valueChanged.connect(self.on_bfo_changed)
        self.checkBox_bfo_auto.toggled.connect(self.on_bfo_auto_toggled)
        self.comboBox_lowpass.currentTextChanged.connect(self.on_filter_changed)
        self.comboBox_highpass.currentTextChanged.connect(self.on_filter_changed)
        self.pushButton_test_tone.clicked.connect(self.test_tone_requested)

        # ===== NUEVA CONEXIÓN =====
        self.pushButton_demodulator.toggled.connect(self.on_demodulator_toggled)
        self.checkBox_agc.toggled.connect(self.on_agc_toggled)
        self.pushButton_record.toggled.connect(self.on_record_toggled)
    
    '''def load_audio_devices(self):
        """Carga lista de dispositivos de audio disponibles"""
        try:
            p = pyaudio.PyAudio()
            self.comboBox_audio_device.clear()
            
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxOutputChannels'] > 0:  # Solo dispositivos de salida
                    name = info['name']
                    self.comboBox_audio_device.addItem(name, i)
            
            p.terminate()
        except Exception as e:
            self.logger.error(f"Error cargando dispositivos de audio: {e}")'''
    
    # En audio_widget_compact.py, reemplaza load_audio_devices():

    def load_audio_devices(self):
        """Carga dispositivos de audio con nombres legibles"""
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            self.comboBox_audio_device.clear()
            
            # Opción por defecto primero
            self.comboBox_audio_device.addItem("🔊 Por defecto del sistema", -1)
            
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxOutputChannels'] > 0:  # Solo dispositivos de salida
                    # Limpiar nombre para mostrarlo mejor
                    name = info['name']
                    if 'ALC897 Analog' in name:
                        name = "🎧 Analógico (HDA Intel PCH)"
                    elif 'HDMI' in name:
                        name = f"📺 {name}"
                    
                    self.comboBox_audio_device.addItem(name, i)
            
            p.terminate()
            
            # Seleccionar el analógico por defecto si existe
            for idx in range(self.comboBox_audio_device.count()):
                if "Analógico" in self.comboBox_audio_device.itemText(idx):
                    self.comboBox_audio_device.setCurrentIndex(idx)
                    break
            
            self.logger.info(f"✅ Cargados {self.comboBox_audio_device.count()} dispositivos de audio")
            
        except Exception as e:
            self.logger.error(f"Error cargando dispositivos: {e}")
    
    # -----------------------------------------------------------------------
    # SLOTS PÚBLICOS
    # -----------------------------------------------------------------------
    def update_vu(self, level_db):
        """Actualiza el medidor VU"""
        self.vu_meter.set_level(level_db)
    
    def update_squelch_indicator(self, is_open):
        """Actualiza indicador de squelch"""
        if is_open:
            self.label_squelch_indicator.setText("🟢")
            self.label_squelch_indicator.setToolTip("Squelch abierto - audio pasando")
        else:
            self.label_squelch_indicator.setText("🔴")
            self.label_squelch_indicator.setToolTip("Squelch cerrado - silenciado")
    
    def set_active_state(self, active):
        """Actualiza estado del demodulador"""
        self.is_active = active
        if active and self.demodulator_enabled:
            self.label_status_icon.setText("🔊")
            self.setStyleSheet("""
                QLabel#label_status_icon { color: #00ff00; }
            """)
        else:
            self.label_status_icon.setText("🔇")
            self.setStyleSheet("""
                QLabel#label_status_icon { color: #888888; }
            """)

    def on_demodulator_toggled(self, enabled):
        """Manejador para el botón de activación del demodulador"""
        self.demodulator_enabled = enabled
        if enabled:
            self.pushButton_demodulator.setText("🔊 DEMOD. ON")
        else:
            self.pushButton_demodulator.setText("🔇 DEMOD. OFF")
        self.demodulator_toggled.emit(enabled)
        self.logger.info(f"🔊 Demodulador {'activado' if enabled else 'desactivado'}")

    def on_agc_toggled(self, enabled: bool):
        self.agc_toggled.emit(enabled)  # añadir señal: agc_toggled = pyqtSignal(bool)

    def on_record_toggled(self, checked: bool):
        if checked:
            self.pushButton_record.setText("⏹ STOP")
            self.record_requested.emit()   # añadir señal: record_requested = pyqtSignal()
        else:
            self.pushButton_record.setText("⏺ GRABAR")
            self.record_stop.emit()        # añadir señal: record_stop = pyqtSignal()

    def update_snr(self, snr_db: float):
        self.progressBar_snr.setValue(int(snr_db))
        self.label_snr_value.setText(f"{snr_db:.1f} dB")

    def update_recording_state(self, active: bool, filename: str):
        if active:
            import os
            self.label_record_filename.setText(os.path.basename(filename))
        else:
            self.label_record_filename.setText("sin archivo")
            self.label_record_time.setText("--:--")
            self.pushButton_record.setChecked(False)
            self.pushButton_record.setText("⏺ GRABAR")
    
    # -----------------------------------------------------------------------
    # SLOTS INTERNOS
    # -----------------------------------------------------------------------
    def on_mode_changed(self, mode):
        """Cambio de modo de demodulación"""
        self.current_mode = mode
        self.mode_changed.emit(mode)
        
        # Habilitar BFO solo para SSB/CW
        bfo_needed = mode in ['LSB', 'USB', 'CW']
        self.groupBox_bfo.setEnabled(bfo_needed)
        if not bfo_needed:
            self.groupBox_bfo.setChecked(False)
    
    def on_volume_changed(self, value):
        """Cambio de volumen"""
        volume = value / 100.0
        self.label_volume_value.setText(f"{value}%")
        self.volume_changed.emit(volume)
    
    def on_squelch_changed(self, value):
        """Cambio de umbral de squelch"""
        threshold = value / 100.0
        self.label_squelch_value.setText(f"{threshold:.2f}")
        self.squelch_changed.emit(
            threshold, 
            self.checkBox_squelch_enable.isChecked()
        )
    
    def on_squelch_enabled(self, enabled):
        """Habilitar/deshabilitar squelch"""
        self.squelch_changed.emit(
            self.horizontalSlider_squelch.value() / 100.0,
            enabled
        )
    
    def on_mute_toggled(self, muted):
        """Toggle mute"""
        if muted:
            self.pushButton_mute.setText("🔇")
        else:
            self.pushButton_mute.setText("🔊")
        self.mute_toggled.emit(muted)
    
    def on_bfo_toggled(self, enabled):
        """Activar/desactivar BFO"""
        self.spinBox_bfo.setEnabled(enabled)
        self.checkBox_bfo_auto.setEnabled(enabled)
        if enabled:
            self.bfo_changed.emit(
                self.spinBox_bfo.value(),
                self.checkBox_bfo_auto.isChecked()
            )
    
    def on_bfo_changed(self, freq_hz):
        """Cambio de frecuencia BFO"""
        if self.groupBox_bfo.isChecked():
            self.bfo_changed.emit(freq_hz, self.checkBox_bfo_auto.isChecked())
    
    def on_bfo_auto_toggled(self, auto):
        """Cambio modo automático BFO"""
        if self.groupBox_bfo.isChecked():
            self.bfo_changed.emit(self.spinBox_bfo.value(), auto)
    
    def on_filter_changed(self):
        """Cambio en filtros de audio"""
        lowpass = self.comboBox_lowpass.currentText()
        highpass = self.comboBox_highpass.currentText()
        self.filter_changed.emit(lowpass, highpass)
    
    def get_audio_device(self):
        """Retorna el índice del dispositivo de audio seleccionado"""
        return self.comboBox_audio_device.currentData()

# widgets/fft_controls_widget.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
from PyQt5.QtWidgets import QDockWidget
from PyQt5.QtCore import pyqtSignal
from PyQt5.uic import loadUi
import logging


# =======================================================================
# WIDGET DE CONTROL FFT
# =======================================================================
class FFTControlsWidget(QDockWidget):
    """Widget de control de parámetros FFT - BLOQUEO VISIBLE"""
    
    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    settings_changed = pyqtSignal(dict)
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        # Estado
        self.is_running = False
        self.pending_fft_size = None
        
        # Cargar UI
        loadUi('ui/fft_controls_widget.ui', self)
        
        # Configurar UI
        self.setup_ui()
        
        # Conectar señales
        self.setup_connections()
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN DE UI
    # -----------------------------------------------------------------------
    def setup_ui(self):
        """Configura elementos de UI"""
        # TAMAÑO FFT - se bloquea durante captura
        self.comboBox_fft_size.addItems([
            "256", "512", "1024", "2048", 
            "4096", "8192", "16384"
        ])
        self.comboBox_fft_size.setCurrentIndex(2)  # 1024 default
        
        # VENTANA - siempre habilitada
        self.comboBox_window_type.addItems([
            "Rectangular", "Hann", "Hamming", 
            "Blackman", "Kaiser"
        ])
        self.comboBox_window_type.setCurrentIndex(1)  # Hann default
        
        # PROMEDIADO - siempre habilitado
        self.horizontalSlider_averaging.setRange(1, 100)
        self.horizontalSlider_averaging.setValue(1)
        self.horizontalSlider_averaging.valueChanged.connect(
            lambda v: self.label_averaging_value.setText(f"{v}")
        )
        
        # OVERLAP - siempre habilitado
        self.horizontalSlider_overlap.setRange(0, 95)
        self.horizontalSlider_overlap.setValue(50)
        self.horizontalSlider_overlap.valueChanged.connect(
            lambda v: self.label_overlap_value.setText(f"{v}%")
        )
    
    def setup_connections(self):
        """Conecta señales"""
        self.comboBox_fft_size.currentIndexChanged.connect(self.on_size_changed)
        self.comboBox_window_type.currentIndexChanged.connect(self.on_setting_changed)
        self.horizontalSlider_averaging.valueChanged.connect(self.on_setting_changed)
        self.horizontalSlider_overlap.valueChanged.connect(self.on_setting_changed)
        #self.pushButton_apply_fft.clicked.connect(self.apply_settings)
        #self.pushButton_reset_fft.clicked.connect(self.reset_settings)
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - CONTROL DE ESTADO
    # -----------------------------------------------------------------------
    def set_controls_enabled(self, enabled):
        """Habilita/deshabilita SOLO el tamaño FFT visualmente"""
        self.comboBox_fft_size.setEnabled(enabled)
    
    def on_capture_started(self):
        """Llamado cuando comienza la captura"""
        self.is_running = True
        self.set_controls_enabled(False)
        self.logger.info("🔒 Tamaño FFT bloqueado")
    
    def on_capture_stopped(self):
        """Llamado cuando termina la captura"""
        self.is_running = False
        self.set_controls_enabled(True)
        self.logger.info("🔓 Tamaño FFT desbloqueado")
        
        # Aplicar cambio pendiente automáticamente
        if self.pending_fft_size:
            self.logger.info(
                f"✅ Aplicando tamaño FFT pendiente: {self.pending_fft_size}"
            )
            settings = {'fft_size': int(self.pending_fft_size)}
            self.settings_changed.emit(settings)
            self.pending_fft_size = None
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - GETTERS
    # -----------------------------------------------------------------------
    def get_settings(self):
        """Obtiene configuración actual"""
        return {
            'fft_size': int(self.comboBox_fft_size.currentText()),
            'window': self.comboBox_window_type.currentText(),
            'averaging': self.horizontalSlider_averaging.value(),
            'overlap': self.horizontalSlider_overlap.value()
        }
    
    def get_pending_size(self):
        """Retorna tamaño FFT pendiente"""
        return self.pending_fft_size
    
    # -----------------------------------------------------------------------
    # SLOTS DE SEÑALES
    # -----------------------------------------------------------------------
    def on_size_changed(self):
        """Cambio de tamaño FFT - pendiente si está capturando"""
        new_size = self.comboBox_fft_size.currentText()
        
        if self.is_running:
            self.pending_fft_size = new_size
            self.logger.info(f"⏳ Tamaño FFT pendiente: {new_size}")
        else:
            self.pending_fft_size = None
            settings = {'fft_size': int(new_size)}
            self.settings_changed.emit(settings)
    
    def on_setting_changed(self):
        """Cambio de ventana, promediado u overlap - siempre inmediato"""
        settings = self.get_settings()
        if self.pending_fft_size:
            settings.pop('fft_size', None)
        if settings:
            self.settings_changed.emit(settings)
    
    def apply_settings(self):
        """Aplica configuración actual"""
        settings = self.get_settings()
        self.settings_changed.emit(settings)
    
    def reset_settings(self):
        """Restaura valores por defecto"""
        self.comboBox_fft_size.setCurrentIndex(2)  # 1024
        self.comboBox_window_type.setCurrentIndex(1)  # Hann
        self.horizontalSlider_averaging.setValue(1)
        self.horizontalSlider_overlap.setValue(50)
        self.pending_fft_size = None
        self.apply_settings()
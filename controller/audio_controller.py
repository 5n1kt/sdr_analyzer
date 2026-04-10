# controller/audio_controller.py
# -*- coding: utf-8 -*-

import logging
import pyaudio
from PyQt5.QtCore import QObject

from workers.demodulator_worker import DemodulatorWorker
from widgets.audio_widget_compact import AudioWidgetCompact


class AudioController(QObject):
    """Controlador de audio - Integración con pipeline existente"""
    
    def __init__(self, main_controller):
        super().__init__()
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.AudioController")
        
        self.widget = None
        self.worker = None
        self.is_active = False
        
        self.logger.info("✅ AudioController inicializado")
    
    def create_widget(self):
        """Crea y configura el widget"""
        if self.widget is None:
            self.widget = AudioWidgetCompact(self.main)
            
            # Conectar señales del widget
            self.widget.mode_changed.connect(self.on_mode_changed)
            self.widget.volume_changed.connect(self.on_volume_changed)
            self.widget.squelch_changed.connect(self.on_squelch_changed)
            self.widget.bfo_changed.connect(self.on_bfo_changed)
            self.widget.filter_changed.connect(self.on_filter_changed)
            self.widget.mute_toggled.connect(self.on_mute_toggled)
            self.widget.test_tone_requested.connect(self.on_test_tone)
            # ===== NUEVA CONEXIÓN =====
            self.widget.demodulator_toggled.connect(self.on_demodulator_toggled)
            
            # Cargar dispositivos de audio
            self._load_audio_devices()
        
        return self.widget
    
    def _load_audio_devices(self):
        """Carga dispositivos en el combo box"""
        try:
            p = pyaudio.PyAudio()
            self.widget.comboBox_audio_device.clear()
            
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxOutputChannels'] > 0:
                    name = info['name']
                    self.widget.comboBox_audio_device.addItem(name, i)
            
            p.terminate()
            
            # Conectar señal después de cargar
            self.widget.comboBox_audio_device.currentIndexChanged.connect(
                self.on_audio_device_changed
            )
            
        except Exception as e:
            self.logger.error(f"Error cargando dispositivos: {e}")
    
    # -----------------------------------------------------------------------
    # ACTIVACIÓN (llamado desde RFController)
    # -----------------------------------------------------------------------
    def on_capture_started(self):
        """Se llama cuando la captura en vivo comienza (desde RFController)"""
        # Ya no iniciamos el worker automáticamente. Solo actualizamos el widget
        # para que sepa que la captura está activa, pero el worker se iniciará
        # cuando el usuario presione el botón.
        self.logger.info("🔊 Captura iniciada, demodulador listo para activarse")
        # Aseguramos que el widget sepa que el pipeline de datos está listo
        # pero el worker aún no está activo.
        self.widget.is_active = False  # El widget mostrará "🔇" hasta que se active
        self.widget.label_status_icon.setText("🔇")
        self.widget.label_status_icon.setStyleSheet("color: #888888;")
    
    def on_capture_stopped(self):
        """Se llama cuando la captura termina"""
        # Siempre detenemos el worker si está activo
        self._stop_worker()

    '''def on_capture_started(self):
        """Inicia demodulador - VERSIÓN SIMPLIFICADA"""
        if not self.main.ring_buffer:
            self.logger.warning("⚠️ No hay ring buffer")
            return
        
        self.logger.info("🔊 Iniciando demodulador...")
        
        self.worker = DemodulatorWorker(
            self.main.ring_buffer,
            self.main.bladerf.sample_rate
        )
        
        # Conectar señales
        self.worker.vu_level.connect(self.widget.update_vu)
        self.worker.squelch_changed.connect(self.widget.update_squelch_indicator)
        self.worker.error_occurred.connect(self.on_error)
        
        self.worker.start()
        self.widget.set_active_state(True)
        self.is_active = True
        
        self.logger.info("✅ Demodulador activo")
    
    def on_capture_stopped(self):
        """Se llama cuando la captura termina"""
        if self.worker:
            self.logger.info("🔇 Deteniendo demodulador...")
            self.worker.stop()
            self.worker = None
        
        self.widget.set_active_state(False)
        self.is_active = False
        self.logger.info("✅ Demodulador detenido")'''
    
    # -----------------------------------------------------------------------
    # SLOTS DEL WIDGET
    # -----------------------------------------------------------------------
    def on_mode_changed(self, mode):
        """Cambia modo"""
        if self.worker:
            self.worker.set_mode(mode)
            self.logger.info(f"📻 Modo: {mode}")
    
    def on_volume_changed(self, volume):
        """Cambia volumen"""
        if self.worker:
            self.worker.set_volume(volume)
    
    def on_squelch_changed(self, threshold, enabled):
        """Cambia squelch"""
        if self.worker:
            self.worker.set_squelch(threshold, enabled)
    
    def on_bfo_changed(self, freq_hz, auto):
        """Cambia BFO"""
        if self.worker:
            enabled = self.widget.groupBox_bfo.isChecked()
            self.worker.set_bfo(freq_hz, enabled, auto)
    
    def on_filter_changed(self, lowpass, highpass):
        """Cambia filtros"""
        if self.worker:
            # Convertir textos a Hz
            lpf_map = {'2.4k': 2400, '3.0k': 3000, '3.5k': 3500,
                      '5.0k': 5000, '8.0k': 8000, '10k': 10000}
            hpf_map = {'OFF': 0, '50': 50, '100': 100, '200': 200, '300': 300}
            
            lpf_hz = lpf_map.get(lowpass, 5000)
            hpf_hz = hpf_map.get(highpass, 0)
            
            self.worker.set_lowpass(lpf_hz)
            self.worker.set_highpass(hpf_hz)
    
    def on_mute_toggled(self, muted):
        """Mute"""
        if self.worker:
            self.worker.set_volume(0.0 if muted else self.widget.horizontalSlider_volume.value() / 100.0)
    
    # En audio_controller.py, modifica on_audio_device_changed():

    def on_audio_device_changed(self, index):
        """Cambia dispositivo de audio"""
        if self.worker:
            device_idx = self.widget.comboBox_audio_device.currentData()
            self.logger.info(f"🎧 Cambiando a dispositivo: {device_idx}")
            
            if device_idx == -1:  # Por defecto
                self.worker.set_audio_device(None)
            else:
                self.worker.set_audio_device(device_idx)
    
    def on_test_tone(self):
        """Genera tono de prueba (1kHz)"""
        self.logger.info("🔊 Tono de prueba")
        # Implementar si es necesario
    
    def on_error(self, msg):
        """Maneja errores"""
        self.logger.error(f"❌ {msg}")
        self.main.statusbar.showMessage(f"Error audio: {msg}", 3000)


    # -----------------------------------------------------------------------
    # NUEVO SLOT
    # -----------------------------------------------------------------------
    def on_demodulator_toggled(self, enabled):
        """Activa o desactiva el worker de demodulación"""
        if enabled:
            self._start_worker()
        else:
            self._stop_worker()

    # -----------------------------------------------------------------------
    # MÉTODOS PRIVADOS PARA GESTIÓN DEL WORKER
    # -----------------------------------------------------------------------
    def _start_worker(self):
        """Inicia el worker de demodulación (lógica extraída de on_capture_started)"""
        if not self.main.ring_buffer:
            self.logger.warning("⚠️ No hay ring buffer, no se puede iniciar demodulador")
            return
        
        if self.worker is not None:
            self.logger.warning("⚠️ Worker ya existente, deteniéndolo primero...")
            self._stop_worker()
        
        self.logger.info("🔊 Iniciando demodulador...")
        
        self.worker = DemodulatorWorker(
            self.main.ring_buffer,
            self.main.bladerf.sample_rate
        )
        
        # Conectar señales
        self.worker.vu_level.connect(self.widget.update_vu)
        self.worker.squelch_changed.connect(self.widget.update_squelch_indicator)
        self.worker.error_occurred.connect(self.on_error)
        
        self.worker.start()
        self.widget.set_active_state(True)
        self.is_active = True
        
        self.logger.info("✅ Demodulador activo")
    
    def _stop_worker(self):
        """Detiene el worker de demodulación"""
        if self.worker:
            self.logger.info("🔇 Deteniendo demodulador...")
            self.worker.stop()
            self.worker = None
        
        self.widget.set_active_state(False)
        self.is_active = False
        self.logger.info("✅ Demodulador detenido")
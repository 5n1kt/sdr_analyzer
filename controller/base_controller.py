# controller/base_controller.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import os
import logging
import traceback
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QHBoxLayout, QFileDialog
from PyQt5.QtCore import QTimer, Qt
from PyQt5.uic import loadUi
import numpy as np

# --- CORRECCIÓN: Eliminar import de bladerf_manager ---
# from bladerf_manager import BladeRFManager  # <-- ¡ELIMINADO! Ya no se usa

from widgets.rf_controls import RFControlsWidget
from widgets.fft_controls import FFTControlsWidget
from widgets.visualization import VisualizationWidget
from widgets.waterfall_plot import WaterfallPlot
from widgets.spectrum_plot import SpectrumPlot
from widgets.iq_manager_widget import IQManagerWidget
from widgets.frequency_spinner import FrequencySpinner

from widgets.tscm_widget import TSCMWidget

from workers.shared_buffer import IQRingBuffer
from workers.iq_processor_zerocopy import IQProcessorZeroCopy
from workers.fft_processor_zerocopy import FFTProcessorZeroCopy
from workers.iq_player import IQPlayer

# =======================================================================
# IMPORTAR SUBCONTROLADORES
# =======================================================================
from controller.rf_controller import RFController
from controller.fft_controller import FFTController
from controller.playback_controller import PlaybackController
from controller.ui_controller import UIController
from controller.frequency_controller import FrequencyController
from controller.detector_controller import DetectorController
from controller.audio_controller import AudioController

from controller.tscm_controller import TSCMController


from utils.theme_manager import ThemeManager
from utils.config_manager import ConfigManager


# =======================================================================
# CONTROLADOR PRINCIPAL (UNIFICADO)
# =======================================================================
class MainController(QMainWindow):
    """
    Controlador principal que coordina todos los módulos.
    """
    
    # -----------------------------------------------------------------------
    # CONSTANTES DE CLASE
    # -----------------------------------------------------------------------
    FLOOR_DB = -120.0
    CEILING_DB = 0.0
    PERSISTENCE_DEFAULT = 0.5
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        # Crear UNA SOLA instancia de ThemeManager
        from utils.theme_manager import ThemeManager
        self.theme_manager = ThemeManager()
        self.logger.info(f"✅ ThemeManager creado en MainController (id: {id(self.theme_manager)})")
                
        # Cargar UI principal
        loadUi('mainwindow.ui', self)
       
        # ===== INICIALIZAR COMPONENTES =====
        self._init_components()
        
        # ===== INICIALIZAR SUBCONTROLADORES =====
        self._init_subcontrollers()
        
        # ===== CONFIGURAR UI =====
        self._setup_ui()
        
        # ===== INICIALIZAR HARDWARE =====
        self.initialize_sdr()  # <-- Cambiado de initialize_bladerf()

        self._setup_power_meter()

        self._setup_record_button()
        
        # ===== TIMER PARA ACTUALIZACIÓN =====
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(100)

        # Inicializar config_manager
        self.config_manager = ConfigManager(self.theme_manager)
        
        # Cargar configuración
        self.config_manager.load_all_settings(self)


        # AHORA, después de cargar la configuración, intentar cargar Artemis
        if hasattr(self, 'artemis_widget') and hasattr(self.artemis_widget, 'auto_load_from_config'):
            db_path = self.config_manager.settings.value("artemis/database_path", "", type=str)
            if db_path and os.path.exists(db_path):
                self.artemis_widget.auto_load_from_config(db_path)
                self.logger.info(f"🔄 Cargando Artemis DB desde configuración: {db_path}")

        if hasattr(self, 'playback_ctrl') and hasattr(self, 'iq_manager'):
            #self.playback_ctrl.set_metadata_callback(self.iq_manager._on_playback_metadata)
            self.playback_ctrl.set_metadata_callback(self.iq_manager.update_metadata_display)
            self.logger.info("✅ Callback de metadata conectado")
        
        self.logger.info("✅ Controlador principal inicializado")
    
    def _init_components(self):
        """Inicializa los componentes básicos"""
        # Componentes de hardware - ahora usa SDRDevice
        self.bladerf = None  # Esta variable sigue llamándose 'bladerf' por compatibilidad
                             # pero ahora contendrá un objeto SDRDevice (BladeRFDevice)
        
        # Procesadores
        self.iq_processor = None
        self.fft_processor = None
        
        # Buffers
        self.ring_buffer = None
        self.recording_ring_buffer = None
        
        # Estado
        self.is_running = False
        
        # Variables para reproducción
        self.player = None
        self.is_playing_back = False
        self.playback_ring_buffer = None
        self.playback_fft_processor = None
        
        # Variables para persistencia
        self.max_hold = None
        self.min_hold = None
        self.persistence_factor = self.PERSISTENCE_DEFAULT
        self.plot_max = False
        self.plot_min = False

        # Flag para reiniciar curvas max/min
        self.reset_max_min_flag = False

    def _init_subcontrollers(self):
        """Inicializa los subcontroladores especializados"""
        # RF Controller
        self.rf_ctrl = RFController(self)
        
        # FFT Controller
        self.fft_ctrl = FFTController(self)
        
        # Playback Controller
        self.playback_ctrl = PlaybackController(self)
        
        # UI Controller
        self.ui_ctrl = UIController(self)
        
        # Frequency Controller
        self.freq_ctrl = FrequencyController(self)

        # Detector Controller
        self.detector_ctrl = DetectorController(self)

        # Audio Controller
        self.audio_ctrl = AudioController(self)
        
        # TSCM Controller
        self.tscm_ctrl = TSCMController(self)
        
        self.logger.info("✅ Subcontroladores inicializados")
    
    def _setup_ui(self):
        """Configura la UI delegando en UI Controller"""
        self.ui_ctrl.setup_dock_widgets()
        self.ui_ctrl.setup_plots()
        self.ui_ctrl.setup_menu()
        self.ui_ctrl.setup_connections()

        self._connect_tscm_signals()

        # Conectar VisualizationWidget al controlador
        if hasattr(self, 'viz_widget'):
            self.viz_widget.set_main_controller(self)
            self.logger.info("🔗 VisualizationWidget conectado al MainController")


        if hasattr(self, 'artemis_widget'):
            self.artemis_widget.database_loaded.connect(self._on_artemis_db_loaded)
            self.logger.info("🔗 ArtemisWidget conectado para guardar configuración")

        # TSCM Widget
        self.tscm_widget = TSCMWidget(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tscm_widget)
        
        # Conectar TSCM Controller con su Widget
        self.tscm_ctrl.set_widget(self.tscm_widget)
        
        # Conectar FFTController con TSCMController
        if hasattr(self, 'fft_ctrl'):
            self.fft_ctrl.set_tscm_controller(self.tscm_ctrl)
    
        # Inicializar indicador de modo al final del __init__
        if hasattr(self, 'label_mode_indicator'):
            self.update_mode_indicator('live')
            self.logger.info("📻 Indicador de modo inicializado: LIVE")



    # En base_controller.py, dentro de _setup_ui() o similar

    def _setup_tscm_connections(self):
        """Conecta las señales TSCM entre el widget FFT y el controlador FFT."""
        self.logger.info("🔗 Configurando conexiones TSCM...")
        
        if hasattr(self, 'fft_ctrl') and hasattr(self, 'fft_widget'):
            self.fft_ctrl.connect_fft_widget_signals()
            self.logger.info("✅ Conexiones TSCM establecidas")
        else:
            self.logger.error("❌ No se pudo conectar TSCM: fft_ctrl o fft_widget no existen")

    '''def _connect_tscm_signals(self):
        """Conecta las señales TSCM entre FFTControlsWidget y FFTController."""
        self.logger.info("=" * 60)
        self.logger.info("🔗 Conectando señales TSCM...")
        
        if hasattr(self, 'fft_ctrl') and hasattr(self, 'fft_widget'):
            self.logger.info(f"   fft_ctrl: {type(self.fft_ctrl).__name__}")
            self.logger.info(f"   fft_widget: {type(self.fft_widget).__name__}")
            
            # Verificar que el controlador tiene el método
            if hasattr(self.fft_ctrl, 'connect_fft_widget_signals'):
                self.fft_ctrl.connect_fft_widget_signals()
                self.logger.info("✅ Conexiones TSCM establecidas")
            else:
                self.logger.error("❌ fft_ctrl NO tiene método connect_fft_widget_signals")
        else:
            self.logger.error("❌ fft_ctrl o fft_widget no existen")
            self.logger.info(f"   fft_ctrl existe: {hasattr(self, 'fft_ctrl')}")
            self.logger.info(f"   fft_widget existe: {hasattr(self, 'fft_widget')}")
        
        self.logger.info("=" * 60)'''

    def _connect_tscm_signals(self):
        """
        Conecta las señales TSCM entre TSCMWidget y TSCMController.
        NOTA: Ya no usa FFTController para esto.
        """
        self.logger.info("=" * 60)
        self.logger.info("🔗 Conectando señales TSCM...")
        
        # Verificar que tenemos TSCM Controller y Widget
        if hasattr(self, 'tscm_ctrl') and hasattr(self, 'tscm_widget'):
            self.logger.info(f"   tscm_ctrl: {type(self.tscm_ctrl).__name__}")
            self.logger.info(f"   tscm_widget: {type(self.tscm_widget).__name__}")
            
            # Conectar el widget al controlador
            if hasattr(self.tscm_ctrl, 'set_widget'):
                self.tscm_ctrl.set_widget(self.tscm_widget)
                self.logger.info("✅ Widget TSCM conectado al controlador")
            else:
                self.logger.error("❌ tscm_ctrl NO tiene método set_widget")
            
            # Conectar FFTController con TSCMController
            if hasattr(self, 'fft_ctrl') and hasattr(self.fft_ctrl, 'set_tscm_controller'):
                self.fft_ctrl.set_tscm_controller(self.tscm_ctrl)
                self.logger.info("✅ FFTController vinculado con TSCMController")
            else:
                self.logger.warning("⚠️ FFTController no tiene set_tscm_controller (TSCM usará método alternativo)")
        else:
            self.logger.error("❌ tscm_ctrl o tscm_widget no existen")
            self.logger.info(f"   tscm_ctrl existe: {hasattr(self, 'tscm_ctrl')}")
            self.logger.info(f"   tscm_widget existe: {hasattr(self, 'tscm_widget')}")
        
        self.logger.info("=" * 60)

    # -----------------------------------------------------------------------
    # MÉTODOS DELEGADOS A SUBCONTROLADORES
    # -----------------------------------------------------------------------
    
    # ===== SDR Methods =====
    def initialize_sdr(self, device_type: str = 'bladerf'):
        """Inicializa el SDR usando la fábrica (delegado a RF Controller)"""
        return self.rf_ctrl.initialize_sdr(device_type)
    
    def toggle_rx(self):
        """Alternar recepción, deteniendo reproducción si es necesario."""
        # Si estamos reproduciendo, detener reproducción primero
        if self.is_playing_back:
            self.logger.info("🔄 Deteniendo reproducción para iniciar recepción")
            self.playback_ctrl.stop_playback(restore_rx=True)
            import time
            time.sleep(0.3)
        
        # Ahora alternar recepción normalmente
        if not self.is_running:
            self.rf_ctrl.start_rx()
        else:
            self.rf_ctrl.stop_rx()
    
    def start_rx(self):
        """Delegado a RF Controller"""
        self.rf_ctrl.start_rx()
    
    def stop_rx(self):
        """Delegado a RF Controller"""
        self.rf_ctrl.stop_rx()
    
    def update_rf_settings(self, settings):
        """Delegado a RF Controller"""
        self.rf_ctrl.update_rf_settings(settings)
    
    # ===== FFT Methods =====
    def update_fft_settings(self, settings):
        """Delegado a FFT Controller"""
        self.fft_ctrl.update_fft_settings(settings)
    
    def update_spectrum(self, fft_data):
        """Delegado a FFT Controller"""
        self.fft_ctrl.update_spectrum(fft_data)
    
    # ===== Playback Methods =====
    def on_playback_requested(self, filename, play):
        """Delegado a Playback Controller"""
        if hasattr(self, 'playback_ctrl'):
            self.playback_ctrl.on_playback_requested(filename, play)
        else:
            self.logger.error("❌ playback_ctrl no disponible")
    
    def start_playback(self, filename):
        """Delegado a Playback Controller"""
        if hasattr(self, 'playback_ctrl'):
            self.playback_ctrl.start_playback(filename)
    
    def stop_playback(self):
        """Delegado a Playback Controller"""
        if hasattr(self, 'playback_ctrl'):
            self.playback_ctrl.stop_playback()

    def pause_playback(self):
        """Delegado a Playback Controller"""
        if hasattr(self, 'playback_ctrl'):
            self.playback_ctrl.pause_playback()

    def resume_playback(self):
        """Delegado a Playback Controller"""
        if hasattr(self, 'playback_ctrl'):
            self.playback_ctrl.resume_playback()

    def set_loop_mode(self, enabled: bool):
        """Delegado a Playback Controller"""
        if hasattr(self, 'playback_ctrl'):
            self.playback_ctrl.set_loop_mode(enabled)
    
    # ===== Frequency Methods =====
    def on_frequency_spinner_changed(self, freq_mhz):
        """Delegado a Frequency Controller"""
        self.freq_ctrl.on_frequency_spinner_changed(freq_mhz)
    
    def on_frequency_changed_from_plot(self, freq_mhz):
        """Delegado a Frequency Controller"""
        self.freq_ctrl.on_frequency_changed_from_plot(freq_mhz)
    
    def on_double_spinbox_freq_changed(self):
        """Delegado a Frequency Controller"""
        if hasattr(self, 'freq_ctrl'):
            self.freq_ctrl.on_double_spinbox_freq_changed()
    
    def sync_frequency_widgets(self, freq_mhz):
        """Delegado a Frequency Controller"""
        self.freq_ctrl.sync_frequency_widgets(freq_mhz)
    
    # ===== UI Methods =====
    def update_viz_settings(self, settings):
        """Delegado a UI Controller"""
        self.ui_ctrl.update_viz_settings(settings)
    
    def update_display(self):
        """Delegado a UI Controller"""
        self.ui_ctrl.update_display()
    
    # ===== Métodos de utilidad =====
    def _update_plot_range(self, freq_mhz):
        """Actualiza el rango del gráfico de espectro"""
        try:
            if not hasattr(self, 'spectrum_plot'):
                return
            
            if self.is_playing_back and self.player:
                sample_rate = self.player.sample_rate
            else:
                sample_rate = self.bladerf.sample_rate if self.bladerf else 2e6
            
            sample_rate_mhz = sample_rate / 1e6
            min_freq = freq_mhz - sample_rate_mhz/2
            max_freq = freq_mhz + sample_rate_mhz/2
            
            self.spectrum_plot.plot_widget.setXRange(min_freq, max_freq)
            
        except Exception as e:
            self.logger.error(f"Error actualizando rango del plot: {e}")
    
    def _update_plot_range_with_sr(self, freq_mhz, sample_rate_hz):
        """Actualiza el rango del gráfico con un sample rate específico"""
        try:
            if not hasattr(self, 'spectrum_plot'):
                return
            
            sample_rate_mhz = sample_rate_hz / 1e6
            min_freq = freq_mhz - sample_rate_mhz/2
            max_freq = freq_mhz + sample_rate_mhz/2
            
            self.spectrum_plot.plot_widget.setXRange(min_freq, max_freq)
            
        except Exception as e:
            self.logger.error(f"Error actualizando rango con SR: {e}")
    
    # ===== Métodos del menú =====
    def on_save_config(self):
        """Guarda la configuración actual"""
        try:
            self.config_manager.save_all_settings(self)
            self.statusbar.showMessage("✅ Configuración guardada", 2000)
        except Exception as e:
            self.logger.error(f"Error guardando configuración: {e}")
            self.statusbar.showMessage("❌ Error guardando configuración", 2000)
    
    def on_load_config(self):
        """Carga la configuración guardada"""
        try:
            self.config_manager.load_all_settings(self)
            self.statusbar.showMessage("📂 Configuración cargada", 2000)
        except Exception as e:
            self.logger.error(f"Error cargando configuración: {e}")
            self.statusbar.showMessage("❌ Error cargando configuración", 2000)
    
    def on_export_profile(self):
        """Exporta perfil a archivo JSON"""
        try:
            from PyQt5.QtWidgets import QFileDialog
            
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Exportar Perfil",
                "profiles/",
                "Perfiles SDR (*.json);;Todos los archivos (*)"
            )
            
            if filename:
                if not filename.endswith('.json'):
                    filename += '.json'
                
                if self.config_manager.export_settings(filename):
                    self.statusbar.showMessage(f"📤 Perfil exportado: {filename}", 3000)
                else:
                    self.statusbar.showMessage("❌ Error exportando perfil", 3000)
        except Exception as e:
            self.logger.error(f"Error exportando perfil: {e}")
            self.statusbar.showMessage("❌ Error exportando perfil", 3000)
    
    def on_import_profile(self):
        """Importa perfil desde archivo JSON"""
        try:
            from PyQt5.QtWidgets import QFileDialog, QMessageBox
            
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "Importar Perfil",
                "profiles/",
                "Perfiles SDR (*.json);;Todos los archivos (*)"
            )
            
            if filename:
                reply = QMessageBox.question(
                    self,
                    "Importar Perfil",
                    "¿Aplicar la configuración inmediatamente?",
                    QMessageBox.Yes | QMessageBox.No
                )
                
                controller_to_use = self if reply == QMessageBox.Yes else None
                
                if self.config_manager.import_settings(filename, controller_to_use):
                    self.statusbar.showMessage(f"📥 Perfil importado: {filename}", 3000)
                else:
                    self.statusbar.showMessage("❌ Error importando perfil", 3000)
        except Exception as e:
            self.logger.error(f"Error importando perfil: {e}")
            self.statusbar.showMessage("❌ Error importando perfil", 3000)
    
    def on_reset_config(self):
        """Resetea la configuración a valores por defecto"""
        try:
            from PyQt5.QtWidgets import QMessageBox
            
            reply = QMessageBox.question(
                self,
                "Resetear Configuración",
                "¿Está seguro de que desea resetear TODA la configuración?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.config_manager.clear_all_settings()
                
                if hasattr(self, 'rf_widget'):
                    self.rf_widget.reset_settings()
                if hasattr(self, 'fft_widget'):
                    self.fft_widget.reset_settings()
                if hasattr(self, 'viz_widget'):
                    self.viz_widget.reset_settings()
                
                self.sync_frequency_widgets(100.0)
                self.statusbar.showMessage("🔄 Configuración reseteada", 3000)
                self.logger.info("Configuración reseteada a valores por defecto")
                
        except Exception as e:
            self.logger.error(f"Error reseteando configuración: {e}")
            self.statusbar.showMessage("❌ Error reseteando configuración", 3000)
    
    def on_about(self):
        """Muestra información sobre la aplicación"""
        try:
            from PyQt5.QtWidgets import QMessageBox
            
            info = (
                "<h2>SIMANEEM</h2>"
                "<p><b>Versión:</b> 1.0.0</p>"
                "<p><b>Hardware soportado:</b> BladeRF 2.0 micro</p>"
                "<p><b>Características:</b></p>"
                "<ul>"
                "<li>Análisis espectral en tiempo real</li>"
                "<li>Grabación y reproducción IQ</li>"
                "<li>Persistencia de configuración</li>"
                "<li>Soporte para perfiles exportables</li>"
                "</ul>"
                "<p><b>Desarrollado para:</b> ININDETEC - DCD</p>"
            )
            
            QMessageBox.about(self, "Acerca de SIMANEEM", info)
            
        except Exception as e:
            self.logger.error(f"Error mostrando acerca de: {e}")
    
    def on_show_config_path(self):
        """Muestra la ruta del archivo de configuración"""
        try:
            from PyQt5.QtWidgets import QMessageBox
            
            path = self.config_manager.get_settings_file_path()
            QMessageBox.information(
                self,
                "Ruta de Configuración",
                f"<b>Archivo de configuración:</b><br><br>{path}"
            )
        except Exception as e:
            self.logger.error(f"Error mostrando ruta de configuración: {e}")
            self.statusbar.showMessage("❌ Error obteniendo ruta", 2000)
    
    # ===== Métodos de depuración =====
    def get_system_info(self):
        """Retorna información del sistema para debugging"""
        info = {
            'sdr_initialized': self.bladerf is not None,
            'is_running': self.is_running,
            'is_playing_back': self.is_playing_back,
            'sample_rate': self.bladerf.sample_rate if self.bladerf else None,
            'frequency': self.bladerf.frequency if self.bladerf else None,
        }
        return info
    
    # ===== Manejo de cierre =====
    def closeEvent(self, event):
        """Cierre de aplicación - coordina todos los subcontroladores"""
        self.logger.info("🔻 Cerrando aplicación...")
        
        try:
            # Detener todo
            self.stop_rx()
            self.stop_playback()
            
            # Cerrar hardware
            if self.bladerf:
                self.bladerf.close()
            
            # Guardar configuración
            try:
                self.config_manager.save_all_settings(self)
                self.logger.info("✅ Configuración guardada al cerrar")
            except Exception as e:
                self.logger.error(f"Error guardando configuración al cerrar: {e}")
            
            self.logger.info("✅ Aplicación cerrada correctamente")
            event.accept()
            
        except Exception as e:
            self.logger.error(f"Error durante el cierre: {e}")
            traceback.print_exc()
            event.accept()


    def _on_artemis_db_loaded(self):
        """Guarda la ruta de Artemis DB cuando se carga una nueva base de datos"""
        if hasattr(self, 'config_manager'):
            self.config_manager._save_artemis_settings(self)
            self.logger.info("💾 Ruta de Artemis DB guardada en configuración")



    
    def _setup_power_meter(self):
        """Configura el medidor de potencia en la barra superior."""
        # Timer para actualizar la potencia periódicamente
        self.power_update_timer = QTimer()
        self.power_update_timer.timeout.connect(self._update_power_display)
        self.power_update_timer.start(100)  # 10 Hz
        
        # Rango de potencia (dBm o dBFS)
        self.power_min_db = -120.0
        self.power_max_db = 0.0
        
        # Estado de saturación
        self.saturation_detected = False
        self.saturation_count = 0
        
        self.logger.info("✅ Medidor de potencia configurado")

    def _update_power_display(self):
        """
        Actualiza el display de potencia en tiempo real.
        Obtiene la potencia en la frecuencia actual del marcador.
        """
        try:
            if not hasattr(self, 'spectrum_plot'):
                return
            
            # Obtener frecuencia actual del spinner
            if hasattr(self, 'frequency_spinner'):
                current_freq_mhz = self.frequency_spinner.getFrequency()
            elif hasattr(self, 'doubleSpinBox_freq'):
                current_freq_mhz = self.doubleSpinBox_freq.value()
            else:
                return
            
            # Obtener potencia en esa frecuencia
            power_db = self._get_power_at_frequency(current_freq_mhz)
            
            if power_db is not None:
                self._update_power_label(power_db)
                self._update_power_progress_bar(power_db)
                self._check_saturation(power_db)
            
        except Exception as e:
            self.logger.debug(f"Error actualizando medidor de potencia: {e}")

    def _get_power_at_frequency(self, freq_mhz: float) -> float:
        """
        Obtiene la potencia en la frecuencia especificada.
        Usa el espectro actual del FFTController.
        """
        try:
            if not hasattr(self, 'fft_ctrl'):
                return None
            
            fft_ctrl = self.fft_ctrl
            if not hasattr(fft_ctrl, '_prev_spectrum') or fft_ctrl._prev_spectrum is None:
                return None
            
            spectrum = fft_ctrl._prev_spectrum
            
            # Obtener parámetros actuales
            if self.is_playing_back and self.player:
                sample_rate = self.player.sample_rate
                center_freq_hz = self.player.freq_mhz * 1e6
            elif self.bladerf:
                sample_rate = self.bladerf.sample_rate
                center_freq_hz = self.bladerf.frequency
            else:
                sample_rate = 2e6
                center_freq_hz = freq_mhz * 1e6
            
            center_freq_mhz = center_freq_hz / 1e6
            sample_rate_mhz = sample_rate / 1e6
            
            # Calcular eje de frecuencias
            fft_size = len(spectrum)
            freq_axis = np.linspace(
                center_freq_mhz - sample_rate_mhz / 2,
                center_freq_mhz + sample_rate_mhz / 2,
                fft_size
            )
            
            # Encontrar el bin más cercano
            idx = np.argmin(np.abs(freq_axis - freq_mhz))
            return float(spectrum[idx])
            
        except Exception as e:
            self.logger.debug(f"Error obteniendo potencia: {e}")
            return None

    def _update_power_label(self, power_db: float):
        """Actualiza la etiqueta numérica de potencia."""
        if hasattr(self, 'label_power_value'):
            if power_db > -10:
                color = "#ff4444"  # Rojo - Señal muy fuerte
            elif power_db > -40:
                color = "#ffff00"  # Amarillo - Señal moderada
            elif power_db > -70:
                color = "#00ff00"  # Verde - Señal normal
            else:
                color = "#888888"  # Gris - Señal débil/ruido
            
            # Determinar unidad (dBFS vs dBm)
            unit = "dBFS"  # Por defecto
            if hasattr(self, 'bladerf') and self.bladerf:
                # Si hay calibración, usar dBm
                unit = "dBm"
            
            self.label_power_value.setText(f"{power_db:.1f}") #{unit}
            self.label_power_value.setStyleSheet(
                f"font-weight: bold; font-size: 12pt; color: {color};"
            )

    def _update_power_progress_bar(self, power_db: float):
        """Actualiza la barra de progreso de potencia."""
        if hasattr(self, 'progressBar_power'):
            # Mapear de [-120, 0] a [0, 100]
            normalized = (power_db - self.power_min_db) / (self.power_max_db - self.power_min_db)
            normalized = max(0.0, min(1.0, normalized))
            
            self.progressBar_power.setValue(int(normalized * 100))

    def _check_saturation(self, power_db: float):
        """
        Verifica si la señal está saturando el ADC.
        Umbral de saturación: > -1.0 dBFS
        """
        if power_db > -1.0:
            self.saturation_count += 1
        else:
            self.saturation_count = max(0, self.saturation_count - 1)
        
        is_saturated = self.saturation_count >= 3
        
        if is_saturated and not self.saturation_detected:
            self.saturation_detected = True
            if hasattr(self, 'label_saturation'):
                self.label_saturation.setVisible(True)
                self.label_saturation.setToolTip(
                    "⚠️ ADC SATURADO - ¡Reduzca la ganancia inmediatamente!\n"
                    "La señal está recortando y los datos son inválidos."
                )
            self.logger.warning("⚠️ ADC SATURATION DETECTED!")
            
        elif not is_saturated and self.saturation_detected:
            self.saturation_detected = False
            if hasattr(self, 'label_saturation'):
                self.label_saturation.setVisible(False)

    def update_power_meter_range(self, min_db: float, max_db: float):
        """
        Actualiza el rango del medidor de potencia.
        Llamado cuando cambian los umbrales en VisualizationWidget.
        """
        self.power_min_db = min_db
        self.power_max_db = max_db
        self.logger.debug(f"Power meter range updated: [{min_db}, {max_db}] dB")



    
    def _setup_record_button(self):
        """Configura el botón de grabación rápida en la barra superior."""
        if hasattr(self, 'pushButton_record_main'):
            self.pushButton_record_main.clicked.connect(self._on_record_main_clicked)
            self.logger.info("✅ Botón de grabación rápida configurado")

    
    def _on_record_main_clicked(self):
        """Maneja el clic en el botón de grabación rápida."""
        if not hasattr(self, 'iq_manager'):
            self.logger.warning("⚠️ IQ Manager no disponible")
            return
        
        iq_manager = self.iq_manager
        
        if hasattr(iq_manager, 'recorder') and iq_manager.recorder and iq_manager.recorder.is_recording:
            # Detener grabación
            iq_manager._on_record_stop_clicked()
            # ===== NUEVO: Actualizar indicador =====
            if hasattr(self, 'update_mode_indicator'):
                self.update_mode_indicator()  # Auto-detectar
            # =====================================
        else:
            # Iniciar grabación
            iq_manager._on_record_start_clicked()
            # ===== NUEVO: Actualizar indicador =====
            if hasattr(self, 'update_mode_indicator'):
                self.update_mode_indicator('rec')
            # =====================================
    
    '''def _on_record_main_clicked(self):
        """Maneja el clic en el botón de grabación rápida."""
        if not hasattr(self, 'iq_manager'):
            self.logger.warning("⚠️ IQ Manager no disponible")
            return
        
        iq_manager = self.iq_manager
        
        # Verificar si el recorder está activo
        if hasattr(iq_manager, 'recorder') and iq_manager.recorder and iq_manager.recorder.is_recording:
            # Detener grabación
            iq_manager._on_record_stop_clicked()
        else:
            # Iniciar grabación
            iq_manager._on_record_start_clicked()'''
    
    '''def update_record_button_state(self, is_recording: bool):
        """
        Actualiza el estado visual del botón de grabación.
        Llamado desde IQManagerWidget cuando cambia el estado de grabación.
        """
        if not hasattr(self, 'pushButton_record_main'):
            return
        
        if is_recording:
            self.pushButton_record_main.setText("⏹ DETENER GRAB.")
            self.pushButton_record_main.setStyleSheet("""
                QPushButton {
                    background-color: #ff4444;
                    color: white;
                    border: 1px solid #cc0000;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #ff6666;
                }
            """)
        else:
            self.pushButton_record_main.setText("⏺ GRABAR")
            self.pushButton_record_main.setStyleSheet("""
                QPushButton {
                    background-color: #cc0000;
                    color: white;
                    border: 1px solid #990000;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #ff1a1a;
                }
                QPushButton:disabled {
                    background-color: #666666;
                    border: 1px solid #444444;
                    color: #aaaaaa;
                }
            """)'''

    # controller/base_controller.py

    def update_record_button_state(self, is_recording: bool):
        """Actualiza el estado visual del botón de grabación."""
        if not hasattr(self, 'pushButton_record_main'):
            return
        
        if is_recording:
            self.pushButton_record_main.setText("⏹")
            self.pushButton_record_main.setStyleSheet("""
                QPushButton {
                    background-color: #ff4444;
                    color: white;
                    border: 1px solid #cc0000;
                    border-radius: 2px;
                    padding: 4px;
                    font-weight: bold;
                }
            """)
            # ===== NUEVO: Actualizar indicador de modo =====
            if hasattr(self, 'update_mode_indicator'):
                self.update_mode_indicator('rec')
            # ==============================================
        else:
            self.pushButton_record_main.setText("⏺")
            self.pushButton_record_main.setStyleSheet("""
                QPushButton {
                    background-color: #3a1a1a;
                    color: #ff8888;
                    border: 1px solid #6a2a2a;
                    border-radius: 2px;
                    padding: 4px;
                    font-weight: bold;
                }
                QPushButton:disabled {
                    background-color: #2a2a2a;
                    border: 1px solid #3a3a3a;
                    color: #666666;
                }
            """)
            # ===== NUEVO: Restaurar indicador de modo =====
            if hasattr(self, 'update_mode_indicator'):
                self.update_mode_indicator()  # Auto-detectar
            # ==============================================
    
    def set_record_button_enabled(self, enabled: bool):
        """Habilita/deshabilita el botón de grabación."""
        if hasattr(self, 'pushButton_record_main'):
            self.pushButton_record_main.setEnabled(enabled)


    # controller/base_controller.py

    def update_mode_indicator(self, mode: str = None):
        """
        Actualiza el indicador de modo en la barra superior.
        Prioridad: REC > TSCM > SCAN > PLAY > LIVE
        """
        if not hasattr(self, 'label_mode_indicator'):
            return
        
        if mode is None:
            # Auto-detectar con prioridad
            if hasattr(self, 'iq_manager') and self.iq_manager.recorder and self.iq_manager.recorder.is_recording:
                mode = 'rec'
            elif hasattr(self, 'tscm_ctrl') and self.tscm_ctrl.is_diff_mode_active():
                mode = 'tscm'
            elif self.is_playing_back:
                mode = 'play'
            elif hasattr(self, 'detector_ctrl') and hasattr(self.detector_ctrl, 'widget'):
                if self.detector_ctrl.widget.is_scanning:
                    mode = 'scanner'
                else:
                    mode = 'live'
            else:
                mode = 'live'
        
        styles = {
            'live': {
                'text': 'LIVE',
                'style': (
                    "font-weight: bold; font-size: 10pt; "
                    "color: #88cc88; background-color: #1a2a1a; "
                    "border: 1px solid #2a6a2a; border-radius: 2px; "
                    "padding: 2px 8px; text-transform: uppercase; letter-spacing: 2px;"
                ),
                'tooltip': 'Sistema en vivo - Captura RF activa'
            },
            'rec': {
                'text': 'REC',
                'style': (
                    "font-weight: bold; font-size: 10pt; "
                    "color: #ff4444; background-color: #2a1010; "
                    "border: 1px solid #aa2a2a; border-radius: 2px; "
                    "padding: 2px 8px; text-transform: uppercase; letter-spacing: 2px;"
                ),
                'tooltip': 'GRABANDO - Archivo IQ en escritura'
            },
            'play': {
                'text': 'PLAY',
                'style': (
                    "font-weight: bold; font-size: 10pt; "
                    "color: #88aadd; background-color: #1a1a2a; "
                    "border: 1px solid #2a4a8a; border-radius: 2px; "
                    "padding: 2px 8px; text-transform: uppercase; letter-spacing: 2px;"
                ),
                'tooltip': 'Reproduciendo archivo IQ - Análisis forense'
            },
            'scanner': {
                'text': 'SCAN',
                'style': (
                    "font-weight: bold; font-size: 10pt; "
                    "color: #ddcc44; background-color: #2a2a1a; "
                    "border: 1px solid #8a8a2a; border-radius: 2px; "
                    "padding: 2px 8px; text-transform: uppercase; letter-spacing: 2px;"
                ),
                'tooltip': 'Escaneo de señales activo - Búsqueda en progreso'
            },
            'tscm': {
                'text': 'TSCM',
                'style': (
                    "font-weight: bold; font-size: 10pt; "
                    "color: #ff8844; background-color: #2a1a0a; "
                    "border: 1px solid #8a4a2a; border-radius: 2px; "
                    "padding: 2px 8px; text-transform: uppercase; letter-spacing: 2px;"
                ),
                'tooltip': 'Modo Contravigilancia - Análisis diferencial activo'
            }
        }
        
        config = styles.get(mode, styles['live'])
        self.label_mode_indicator.setText(config['text'])
        self.label_mode_indicator.setStyleSheet(config['style'])
        self.label_mode_indicator.setToolTip(config['tooltip'])
        
        self.logger.info(f"📻 Indicador de modo: {config['text']}")
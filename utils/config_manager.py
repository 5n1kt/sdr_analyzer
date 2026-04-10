# utils/config_manager.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import json
import os
import logging
from datetime import datetime
from PyQt5.QtCore import QSettings, QByteArray, QPoint, QSize, QDir
from PyQt5.QtWidgets import QDockWidget, QApplication



# =======================================================================
# GESTOR DE CONFIGURACIÓN
# =======================================================================
class ConfigManager:
    """
    Gestor de configuración para la aplicación SDR.
    Utiliza QSettings para persistencia multiplataforma.
    """
    
    # -----------------------------------------------------------------------
    # CONSTANTES
    # -----------------------------------------------------------------------
    ORGANIZATION = "INIDETEC - DCD"
    APPLICATION = "SIMANEEM"
    
    # Versión del esquema de configuración
    CONFIG_VERSION = "1.0"
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self,theme_manager=None):
        self.logger = logging.getLogger(__name__)
        self.theme_manager = theme_manager
        self.logger.info(f"✅ ConfigManager inicializado con theme_manager id: {id(theme_manager) if theme_manager else 'None'}")
        
        # Inicializar QSettings
        QSettings.setDefaultFormat(QSettings.IniFormat)
        self.settings = QSettings(self.ORGANIZATION, self.APPLICATION)
        
        self.logger.info(f"✅ ConfigManager inicializado")
        self.logger.info(f"   Archivo: {self.settings.fileName()}")
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - GUARDAR CONFIGURACIÓN
    # -----------------------------------------------------------------------
    def save_all_settings(self, controller):
        """
        Guarda toda la configuración desde el controller.
        """
        self.logger.info("💾 Guardando configuración...")
        
        # Guardar versión
        self.settings.setValue("config_version", self.CONFIG_VERSION)
        self.settings.setValue("last_save", datetime.now().isoformat())
        
        # Guardar cada sección
        self._save_rf_settings(controller)
        self._save_fft_settings(controller)
        self._save_viz_settings(controller)
        self._save_window_settings(controller)
        self._save_theme_settings(controller)
        
        self.settings.sync()
        self.logger.info("✅ Configuración guardada")
    
    def _save_rf_settings(self, controller):
        """Guarda configuración RF - USA EL VALOR DEL SPINNER SI ESTÁ DISPONIBLE"""
        if not hasattr(controller, 'rf_widget'):
            return
        
        # ===== PRIORIDAD: Usar frequency_spinner si existe =====
        if hasattr(controller, 'frequency_spinner'):
            freq_mhz = controller.frequency_spinner.frequency_mhz
            self.logger.debug(f"   Usando frecuencia del spinner: {freq_mhz:.3f} MHz")
        else:
            # Fallback al doubleSpinBox
            freq_mhz = controller.rf_widget.doubleSpinBox_freq.value()
        
        self.settings.beginGroup("rf")
        self.settings.setValue("frequency_mhz", freq_mhz)
        self.settings.setValue("sample_rate", controller.rf_widget.comboBox_sample_rate.currentData())
        self.settings.setValue("bandwidth", controller.rf_widget.comboBox_bandwidth.currentData())
        self.settings.setValue("gain", controller.rf_widget.horizontalSlider_gain.value())
        
        gain_mode_index = controller.rf_widget.comboBox_gain_mode.currentIndex()
        gain_modes = [1, 0, 2, 3, 4]
        self.settings.setValue("gain_mode", gain_modes[gain_mode_index])
        
        self.settings.setValue("agc", controller.rf_widget.checkBox_agc.isChecked())
        self.settings.endGroup()
        
        self.logger.debug(f"   RF settings saved: {freq_mhz:.3f} MHz")
    
    def _save_fft_settings(self, controller):
        """Guarda configuración FFT"""
        if not hasattr(controller, 'fft_widget'):
            return
        
        widget = controller.fft_widget
        settings = widget.get_settings()
        
        self.settings.beginGroup("fft")
        self.settings.setValue("fft_size", settings['fft_size'])
        self.settings.setValue("window", settings['window'])
        self.settings.setValue("averaging", settings['averaging'])
        self.settings.setValue("overlap", settings['overlap'])
        self.settings.endGroup()
        
        self.logger.debug("   FFT settings saved")
    
    def _save_viz_settings(self, controller):
        """Guarda configuración de visualización"""
        if not hasattr(controller, 'viz_widget'):
            return
        
        widget = controller.viz_widget
        settings = widget.get_settings()
        
        self.settings.beginGroup("visualization")

        self.settings.setValue("color_map", settings['color_map'])
        self.settings.setValue("persistence", settings['persistence'])
        self.settings.setValue("plot_max", settings['plot_max'])
        self.settings.setValue("plot_min", settings['plot_min'])
        self.settings.setValue("min_threshold", settings.get('min_threshold', -120))
        self.settings.setValue("max_threshold", settings.get('max_threshold', 0))

        # ===== NUEVAS VARIABLES =====
        # Tiempo de hold (modo y segundos)
        self.settings.setValue("hold_mode", settings.get('hold_mode', 'manual'))
        self.settings.setValue("hold_seconds", settings.get('hold_seconds', 0))
        
        # Persistencia (ya la guardamos como 'persistence', pero asegurarnos)
        # Nota: 'persistence' ya existe arriba
        
        self.settings.endGroup()
        
        self.logger.debug(
            f"   Visualization settings saved: "
            f"persistence={settings.get('persistence')}%, "
            f"hold_mode={settings.get('hold_mode')}, "
            f"hold_seconds={settings.get('hold_seconds')}s, "
            f"plot_max={settings.get('plot_max')}, "
            f"plot_min={settings.get('plot_min')}"
        )
        
    
    def _save_window_settings(self, controller):
        """Guarda geometría y estado de la ventana"""
        self.settings.beginGroup("window")
        
        # Geometría de la ventana principal
        self.settings.setValue("geometry", controller.saveGeometry())
        self.settings.setValue("windowState", controller.saveState())
        
        # Estado de los docks (visibilidad)
        dock_states = {}
        for dock in controller.findChildren(QDockWidget):
            dock_states[dock.objectName()] = not dock.isHidden()
        self.settings.setValue("dock_states", json.dumps(dock_states))
        
        self.settings.endGroup()
        self.logger.debug("   Window settings saved")


    def _save_theme_settings(self, controller):
        """Guarda configuración del tema."""
        if not hasattr(controller, 'theme_manager'):
            return
        
        self.settings.beginGroup("theme")
        self.settings.setValue("current_theme", controller.theme_manager.current_theme)
        self.settings.endGroup()

    # utils/config_manager.py - En _load_theme_settings

    def _load_theme_settings(self, controller):
        """Carga configuración del tema."""
        # Usar el theme_manager que recibimos, no crear uno nuevo
        if not self.theme_manager:
            self.logger.warning("⚠️ No hay theme_manager disponible")
            return
        
        self.settings.beginGroup("theme")
        theme_key = self.settings.value("current_theme", "dark", type=str)
        
        # Aplicar tema guardado usando el theme_manager existente
        app = QApplication.instance()
        if app:
            self.theme_manager.apply_theme_to_app(app, theme_key)
        
        # Actualizar checks en el menú
        if hasattr(controller, 'ui_ctrl'):
            controller.ui_ctrl._update_theme_menu_checks(theme_key)
        
        # Actualizar colores del espectro
        if hasattr(controller, 'spectrum_plot'):
            theme = self.theme_manager.get_theme_colors(theme_key)
            controller.spectrum_plot.set_curve_colors(
                active_color=theme['spectrum_default'].name(),
                max_color=theme['max_hold_default'].name(),
                min_color=theme['min_hold_default'].name()
            )
        
        self.settings.endGroup()
        self.logger.debug(f"   Theme loaded: {theme_key}")
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - CARGAR CONFIGURACIÓN
    # -----------------------------------------------------------------------
    def load_all_settings(self, controller):
        """
        Carga toda la configuración y la aplica al controller.
        Retorna True si se cargó correctamente.
        """
        self.logger.info("📂 Cargando configuración...")
        
        # Verificar versión
        saved_version = self.settings.value("config_version", "0.0")
        if saved_version != self.CONFIG_VERSION:
            self.logger.warning(
                f"⚠️ Versión de configuración diferente: "
                f"{saved_version} vs {self.CONFIG_VERSION}"
            )
        
        # Cargar cada sección
        self._load_rf_settings(controller)
        self._load_fft_settings(controller)
        self._load_viz_settings(controller)
        self._load_window_settings(controller)
        self._load_theme_settings( controller)
        
        self.logger.info("✅ Configuración cargada")
        return True
    
    def _load_rf_settings(self, controller):
        """Carga configuración RF - VERSIÓN FINAL CON SINCRONIZACIÓN"""
        if not hasattr(controller, 'rf_widget'):
            return
        
        self.settings.beginGroup("rf")
        
        settings = {}
        
        freq_mhz = self.settings.value("frequency_mhz", 100.0, type=float)
        settings['frequency'] = freq_mhz * 1e6
        
        settings['sample_rate'] = self.settings.value(
            "sample_rate", 2e6, type=float
        )
        settings['bandwidth'] = self.settings.value(
            "bandwidth", 1e6, type=float
        )
        settings['gain'] = self.settings.value("gain", 50, type=int)
        settings['gain_mode'] = self.settings.value("gain_mode", 1, type=int)
        settings['agc'] = self.settings.value("agc", False, type=bool)
        
        self.settings.endGroup()
        
        # Aplicar configuración RF
        controller.rf_widget.blockSignals(True)
        
        # Sample rate
        index = controller.rf_widget.comboBox_sample_rate.findData(settings['sample_rate'])
        if index >= 0:
            controller.rf_widget.comboBox_sample_rate.setCurrentIndex(index)
        
        # Bandwidth
        index = controller.rf_widget.comboBox_bandwidth.findData(settings['bandwidth'])
        if index >= 0:
            controller.rf_widget.comboBox_bandwidth.setCurrentIndex(index)
        
        # Ganancia
        controller.rf_widget.horizontalSlider_gain.setValue(settings['gain'])
        
        # Modo de ganancia
        gain_modes = [1, 0, 2, 3, 4]
        if settings['gain_mode'] in gain_modes:
            idx = gain_modes.index(settings['gain_mode'])
            controller.rf_widget.comboBox_gain_mode.setCurrentIndex(idx)
        
        # AGC
        controller.rf_widget.checkBox_agc.setChecked(settings['agc'])
        
        controller.rf_widget.blockSignals(False)
        
        # ===== SINCRONIZAR TODOS LOS WIDGETS DE FRECUENCIA =====
        if hasattr(controller, 'sync_frequency_widgets'):
            controller.sync_frequency_widgets(freq_mhz)
        else:
            # Fallback si no existe el método
            if hasattr(controller, 'doubleSpinBox_freq'):
                controller.doubleSpinBox_freq.setValue(freq_mhz)
            if hasattr(controller, 'frequency_spinner'):
                controller.frequency_spinner.setFrequency(freq_mhz)
        
        self.logger.debug(
            f"   RF loaded: {freq_mhz:.3f} MHz, "
            f"{settings['sample_rate']/1e6:.1f} MSPS"
        )
    
    def _load_fft_settings(self, controller):
        """Carga configuración FFT"""
        if not hasattr(controller, 'fft_widget'):
            return
        
        self.settings.beginGroup("fft")
        
        fft_size = self.settings.value("fft_size", 1024, type=int)
        window = self.settings.value("window", "Hann", type=str)
        averaging = self.settings.value("averaging", 1, type=int)
        overlap = self.settings.value("overlap", 50, type=int)
        
        self.settings.endGroup()
        
        # Aplicar configuración
        controller.fft_widget.blockSignals(True)
        
        # Tamaño FFT
        index = controller.fft_widget.comboBox_fft_size.findText(str(fft_size))
        if index >= 0:
            controller.fft_widget.comboBox_fft_size.setCurrentIndex(index)
        
        # Ventana
        index = controller.fft_widget.comboBox_window_type.findText(window)
        if index >= 0:
            controller.fft_widget.comboBox_window_type.setCurrentIndex(index)
        
        # Promediado
        controller.fft_widget.horizontalSlider_averaging.setValue(averaging)
        
        # Overlap
        controller.fft_widget.horizontalSlider_overlap.setValue(overlap)
        
        controller.fft_widget.blockSignals(False)
        
        self.logger.debug(
            f"   FFT loaded: {fft_size}, {window}, "
            f"avg={averaging}, overlap={overlap}%"
        )
    
    def _load_viz_settings(self, controller):
        """Carga configuración de visualización"""
        if not hasattr(controller, 'viz_widget'):
            return
        
        self.settings.beginGroup("visualization")
        
        color_map = self.settings.value("color_map", "Viridis", type=str)
        persistence = self.settings.value("persistence", 50, type=int)
        plot_max = self.settings.value("plot_max", False, type=bool)
        plot_min = self.settings.value("plot_min", False, type=bool)
        min_threshold = self.settings.value("min_threshold", -120, type=int)
        max_threshold = self.settings.value("max_threshold", 0, type=int)
        # ===== NUEVAS VARIABLES =====
        hold_mode = self.settings.value("hold_mode", "manual", type=str)
        hold_seconds = self.settings.value("hold_seconds", 0, type=int)
        
        self.settings.endGroup()
        
        # Aplicar configuración
        controller.viz_widget.blockSignals(True)
        
        # Colormap
        index = controller.viz_widget.comboBox_color_map.findText(color_map)
        if index >= 0:
            controller.viz_widget.comboBox_color_map.setCurrentIndex(index)
        else:
            # Fallback a viridis si no encuentra
            index = controller.viz_widget.comboBox_color_map.findData('viridis')
            if index >= 0:
                controller.viz_widget.comboBox_color_map.setCurrentIndex(index)
        
        # Persistencia
        controller.viz_widget.horizontalSlider_persistence.setValue(persistence)
        controller.viz_widget.label_persistence_value.setText(f"{persistence}%")
        
        # Checkboxes
        controller.viz_widget.checkBox_plot_max.setChecked(plot_max)
        controller.viz_widget.checkBox_plot_min.setChecked(plot_min)
        
        # Umbrales
        if hasattr(controller.viz_widget, 'min_spin'):
            controller.viz_widget.min_spin.setValue(min_threshold)
        if hasattr(controller.viz_widget, 'max_spin'):
            controller.viz_widget.max_spin.setValue(max_threshold)
        
        # ===== NUEVAS CONFIGURACIONES =====
        # Tiempo de hold
        if hasattr(controller.viz_widget, 'comboBox_hold_time'):
            # Mapear hold_seconds a índice
            seconds_to_index = {0: 0, 1: 1, 2: 2, 5: 3, 10: 4, 30: 5, 60: 6}
            index = seconds_to_index.get(hold_seconds, 0)
            controller.viz_widget.comboBox_hold_time.setCurrentIndex(index)
            
            # Actualizar modo
            controller.viz_widget.hold_mode = hold_mode
            controller.viz_widget.hold_seconds = hold_seconds
            
            # Configurar timer si es necesario
            if hold_mode == 'timed' and hold_seconds > 0:
                controller.viz_widget.hold_timer.start(hold_seconds * 1000)
            else:
                controller.viz_widget.hold_timer.stop()
        
        controller.viz_widget.blockSignals(False)
        
        self.logger.debug(
            f"   Viz loaded: {color_map}, persist={persistence}%, "
            f"range={min_threshold}/{max_threshold} dB, "
            f"hold={hold_mode}/{hold_seconds}s, "
            f"max={plot_max}, min={plot_min}"
        )
    
    def _load_window_settings(self, controller):
        """Carga geometría y estado de la ventana"""
        self.settings.beginGroup("window")
        
        # Geometría
        geometry = self.settings.value("geometry")
        if geometry:
            controller.restoreGeometry(geometry)
        
        # Estado de ventana
        window_state = self.settings.value("windowState")
        if window_state:
            controller.restoreState(window_state)
        
        # Estado de docks (cargar después de restaurar estado)
        dock_states_json = self.settings.value("dock_states", "{}", type=str)
        try:
            dock_states = json.loads(dock_states_json)
            for dock in controller.findChildren(QDockWidget):
                if dock.objectName() in dock_states:
                    dock.setVisible(dock_states[dock.objectName()])
        except:
            pass
        
        self.settings.endGroup()
        self.logger.debug("   Window settings loaded")
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - UTILIDADES
    # -----------------------------------------------------------------------
    def clear_all_settings(self):
        """Borra toda la configuración guardada"""
        self.settings.clear()
        self.logger.warning("🗑️ Toda la configuración ha sido borrada")
    
    def export_settings(self, filename):
        """
        Exporta la configuración a un archivo JSON.
        Útil para compartir perfiles entre instalaciones.
        """
        export_data = {}
        
        # Recorrer todos los grupos
        for group in ["rf", "fft", "visualization", "window"]:
            self.settings.beginGroup(group)
            export_data[group] = {}
            for key in self.settings.allKeys():
                export_data[group][key] = self.settings.value(key)
            self.settings.endGroup()
        
        # Añadir metadatos
        export_data['_metadata'] = {
            'export_date': datetime.now().isoformat(),
            'config_version': self.CONFIG_VERSION,
            'application': self.APPLICATION
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
            self.logger.info(f"📤 Configuración exportada a {filename}")
            return True
        except Exception as e:
            self.logger.error(f"Error exportando configuración: {e}")
            return False
    
    def import_settings(self, filename, controller):
        """
        Importa configuración desde un archivo JSON.
        """
        try:
            with open(filename, 'r') as f:
                import_data = json.load(f)
            
            # Verificar metadatos
            metadata = import_data.get('_metadata', {})
            self.logger.info(f"📥 Importando configuración de {metadata.get('export_date', 'desconocida')}")
            
            # Cargar cada grupo
            for group, values in import_data.items():
                if group == '_metadata':
                    continue
                
                self.settings.beginGroup(group)
                for key, value in values.items():
                    self.settings.setValue(key, value)
                self.settings.endGroup()
            
            self.settings.sync()
            
            # Cargar en el controller
            self.load_all_settings(controller)
            
            self.logger.info(f"✅ Configuración importada de {filename}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error importando configuración: {e}")
            return False
    
    def get_settings_file_path(self):
        """Retorna la ruta del archivo de configuración"""
        return self.settings.fileName()
    

    # utils/config_manager.py - En _load_theme_settings

    def _load_theme_settings(self, controller):
        """Carga configuración del tema."""
        if not hasattr(controller, 'theme_manager'):
            return
        
        self.settings.beginGroup("theme")
        theme_key = self.settings.value("current_theme", "dark", type=str)
        
        # Aplicar tema guardado
        app = QApplication.instance()
        if app:
            controller.theme_manager.apply_theme_to_app(app, theme_key)
        
        # ACTUALIZADO: Ya no hay selector, solo actualizar el menú
        if hasattr(controller, 'ui_ctrl'):
            controller.ui_ctrl._update_theme_menu_checks(theme_key)
        
        # Actualizar colores del espectro
        if hasattr(controller, 'spectrum_plot'):
            theme = controller.theme_manager.get_theme_colors(theme_key)
            controller.spectrum_plot.set_curve_colors(
                active_color=theme['spectrum_default'].name(),
                max_color=theme['max_hold_default'].name(),
                min_color=theme['min_hold_default'].name()
            )
        
        self.settings.endGroup()
        self.logger.debug(f"   Theme loaded: {theme_key}")
# controller/ui_controller.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import logging
from PyQt5.QtWidgets import QHBoxLayout, QMessageBox
from PyQt5.QtCore import Qt
import pyqtgraph as pg

from widgets.rf_controls import RFControlsWidget
from widgets.fft_controls import FFTControlsWidget
from widgets.visualization import VisualizationWidget
from widgets.waterfall_plot import WaterfallPlot
from widgets.spectrum_plot import SpectrumPlot
from widgets.iq_manager_widget import IQManagerWidget
from widgets.frequency_spinner import FrequencySpinner


#from widgets.theme_selector_widget import ThemeSelectorWidget


# =======================================================================
# CONTROLADOR DE UI
# =======================================================================
class UIController:
    """Gestiona la interfaz de usuario y widgets"""
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, main_controller):
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.UIController")
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN DE DOCKS
    # -----------------------------------------------------------------------
    '''def setup_dock_widgets(self):
        """Configura los widgets dockables"""
        self.logger.info("🔧 Configurando dock widgets...")
        
        # RF Controls
        self.main.rf_widget = RFControlsWidget(self.main.bladerf)
        self.main.rf_widget.setWindowTitle("Configuración RF")
        self.main.rf_widget.setObjectName("dock_rf_controls")
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.rf_widget)

        # ===== NUEVO: Widget de audio compacto =====
        if hasattr(self.main, 'audio_ctrl'):
            self.main.audio_widget = self.main.audio_ctrl.create_widget()
            self.main.audio_widget.setWindowTitle("DEMODULADOR")
            self.main.audio_widget.setObjectName("dock_audio")
            self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.audio_widget)
            self.logger.info("✅ Widget de audio añadido")
        
        # FFT Controls
        self.main.fft_widget = FFTControlsWidget()
        self.main.fft_widget.setWindowTitle("Configuración FFT")
        self.main.fft_widget.setObjectName("dock_fft_controls")
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.fft_widget)

        # Visualization
        self.main.viz_widget = VisualizationWidget()
        self.main.viz_widget.setWindowTitle("Visualización")
        self.main.viz_widget.setObjectName("dock_visualization")
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.viz_widget)
        
        # Detector FPV Widget
        if hasattr(self.main, 'detector_ctrl'):
            self.main.detector_widget = self.main.detector_ctrl.create_widget()
            self.main.detector_widget.setWindowTitle("DETECTOR DE SEÑALES")
            self.main.detector_widget.setObjectName("dock_signal_detector")
            self.main.addDockWidget(Qt.RightDockWidgetArea, self.main.detector_widget)
            self.logger.info("✅ Widget detector de señales añadido")

        # IQ Manager
        self.main.iq_manager = IQManagerWidget(self.main)
        self.main.iq_manager.set_controller(self.main)
        self.main.iq_manager.setWindowTitle("GESTOR IQ")
        self.main.iq_manager.setObjectName("dock_iq_manager")
        self.main.addDockWidget(Qt.RightDockWidgetArea, self.main.iq_manager)

        # Conectar señal de cambio de tema
        #self.main.theme_selector.theme_changed.connect(self.on_theme_changed)

            
        self.logger.info("✅ Dock widgets configurados")'''

    def setup_dock_widgets(self):
        """Configura los widgets dockables - MISMO ORDEN QUE EL MENÚ"""
        
        # 1. RF Controls (hardware)
        self.main.rf_widget = RFControlsWidget(self.main.bladerf)
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.rf_widget)
        
        # 2. FFT Controls (análisis)
        self.main.fft_widget = FFTControlsWidget()
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.fft_widget)
        
        # 3. Visualization (presentación)
        self.main.viz_widget = VisualizationWidget()
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.viz_widget)
        
        # 4. Audio (demodulación)
        self.main.audio_widget = self.main.audio_ctrl.create_widget()
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.audio_widget)
        
        # 5. Detector (detección automática)
        self.main.detector_widget = self.main.detector_ctrl.create_widget()
        self.main.addDockWidget(Qt.RightDockWidgetArea, self.main.detector_widget)
        
        # 6. IQ Manager (almacenamiento)
        self.main.iq_manager = IQManagerWidget(self.main)
        self.main.addDockWidget(Qt.RightDockWidgetArea, self.main.iq_manager)
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN DE GRÁFICOS
    # -----------------------------------------------------------------------
    def setup_plots(self):
        """Configura los gráficos"""
        pg.setConfigOptions(antialias=True, useOpenGL=False)
        
        # Limpiar layouts
        self._clear_layout(self.main.groupBox_spectrum.layout())
        self._clear_layout(self.main.groupBox_waterfall.layout())
        
        # Espectro con marcador
        self.main.spectrum_plot = SpectrumPlot(self.main, self.logger)
        self.main.spectrum_plot.frequencyChanged.connect(
            self.main.on_frequency_changed_from_plot
        )

        # ===== NUEVO: Configurar líneas del detector =====
        #self.main.spectrum_plot._setup_detector_lines()

        self.main.groupBox_spectrum.layout().addWidget(
            self.main.spectrum_plot.plot_widget
        )
        
        # Waterfall
        self.main.waterfall = WaterfallPlot()
        waterfall_widget = self.main.waterfall.get_plot_widget()
        self.main.groupBox_waterfall.layout().addWidget(waterfall_widget)
        
        # Conectar waterfall a visualization
        if hasattr(self.main, 'viz_widget'):
            self.main.viz_widget.set_waterfall(self.main.waterfall)
        
        # Configurar FrequencySpinner
        self._setup_frequency_widget()
        
        self.logger.info("✅ Gráficos configurados")
    
   

    def _setup_frequency_widget(self):
        """Configura el widget de frecuencia con spinner"""
        if not hasattr(self.main, 'widget_frequency_spinner'):
            self.logger.error("❌ No se encuentra widget_frequency_spinner")
            return
        
        # Obtener frecuencia inicial
        initial_freq = 100.0
        if hasattr(self.main, 'doubleSpinBox_freq'):
            initial_freq = self.main.doubleSpinBox_freq.value()
        
        # Crear FrequencySpinner
        self.main.frequency_spinner = FrequencySpinner(
            initial_freq_mhz=initial_freq,
            parent=self.main  # Importante: pasar self.main
        )
        
        # Limpiar y agregar al layout
        container = self.main.widget_frequency_spinner
        if container.layout() is None:
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
        else:
            layout = container.layout()
            self._clear_layout(layout)

        # Ajustar altura del contenedor para acomodar el spinner más grande
        container.setMinimumHeight(50)  # Asegurar espacio suficiente
        container.setMaximumHeight(55)
        
        layout.addWidget(self.main.frequency_spinner)
        
        # Conectar señal de cambio de frecuencia
        self.main.frequency_spinner.frequencyChanged.connect(
            self.main.on_frequency_spinner_changed
        )
        
        self.logger.info(f"✅ FrequencySpinner creado: {initial_freq:.3f} MHz")
    
    def _clear_layout(self, layout):
        """Limpia un layout"""
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN DE CONEXIONES
    # -----------------------------------------------------------------------
    def setup_connections(self):
        """Conecta las señales de la UI"""
        self.main.pushButton_start_stop_main.clicked.connect(self.main.toggle_rx)
        self.main.rf_widget.settings_changed.connect(self.main.update_rf_settings)
        self.main.fft_widget.settings_changed.connect(self.main.update_fft_settings)
        self.main.viz_widget.settings_changed.connect(self.main.update_viz_settings)

        if hasattr(self.main, 'doubleSpinBox_freq'):
            self.main.doubleSpinBox_freq.editingFinished.connect(
                self.main.on_double_spinbox_freq_changed
            )
        
        self.main.iq_manager.playback_requested.connect(
            self.main.on_playback_requested
        )
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN DE MENÚ
    # -----------------------------------------------------------------------

    def setup_menu(self):
        """Configura el menú de la aplicación"""
        menubar = self.main.menuBar()
        
        # ===== Menú Archivo (existente) =====
        file_menu = menubar.addMenu("Archivo")
        
        save_action = file_menu.addAction("💾 Guardar Configuración")
        save_action.triggered.connect(self.main.on_save_config)
        save_action.setShortcut("Ctrl+S")
        
        load_action = file_menu.addAction("📂 Cargar Configuración")
        load_action.triggered.connect(self.main.on_load_config)
        load_action.setShortcut("Ctrl+L")
        
        file_menu.addSeparator()
        
        export_action = file_menu.addAction("📤 Exportar Perfil...")
        export_action.triggered.connect(self.main.on_export_profile)
        
        import_action = file_menu.addAction("📥 Importar Perfil...")
        import_action.triggered.connect(self.main.on_import_profile)
        
        file_menu.addSeparator()
        
        reset_action = file_menu.addAction("🔄 Resetear Configuración")
        reset_action.triggered.connect(self.main.on_reset_config)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("❌ Salir")
        exit_action.triggered.connect(self.main.close)
        exit_action.setShortcut("Ctrl+Q")
        
        # ===== NUEVO: Menú Ver con selector de temas =====
        view_menu = menubar.addMenu("Ver")
        
        # Submenú para temas
        theme_menu = view_menu.addMenu("🎨 Tema Visual")
        
        # Obtener temas del ThemeManager
        if hasattr(self.main, 'theme_manager'):
            for theme_key, theme_name in self.main.theme_manager.get_theme_names():
                action = theme_menu.addAction(theme_name)
                action.setData(theme_key)
                action.setCheckable(True)
                
                # Marcar el tema actual
                if theme_key == self.main.theme_manager.current_theme:
                    action.setChecked(True)
                
                # Conectar acción
                action.triggered.connect(lambda checked, k=theme_key: self.on_theme_selected(k))
        
        theme_menu.addSeparator()
        
        # Acción para personalizar (opcional)
        customize_action = theme_menu.addAction("⚙️ Personalizar...")
        customize_action.triggered.connect(self.on_customize_theme)
        customize_action.setEnabled(False)  # Por ahora deshabilitado
        
        view_menu.addSeparator()
        
        # ===== ORDEN CORREGIDO DE DOCKS =====
        # 1. Configuración RF (hardware primero)
        if hasattr(self.main, 'rf_widget'):
            action = self.main.rf_widget.toggleViewAction()
            action.setText(" Configuración RF")
            view_menu.addAction(action)
        
        # 2. Configuración FFT (análisis espectral)
        if hasattr(self.main, 'fft_widget'):
            action = self.main.fft_widget.toggleViewAction()
            action.setText(" Configuración FFT")
            view_menu.addAction(action)
        
        # 3. Visualización (cómo se ve)
        if hasattr(self.main, 'viz_widget'):
            action = self.main.viz_widget.toggleViewAction()
            action.setText(" Visualización")
            view_menu.addAction(action)
        
        view_menu.addSeparator()  # Separador después de configuración
        
        # 4. Demodulador (escucha)
        if hasattr(self.main, 'audio_widget'):
            action = self.main.audio_widget.toggleViewAction()
            action.setText(" Demodulador")
            view_menu.addAction(action)
        
        # 5. Detector de Señales (detección automática)
        if hasattr(self.main, 'detector_widget'):
            action = self.main.detector_widget.toggleViewAction()
            action.setText(" Detector de Señales")
            view_menu.addAction(action)
        
        view_menu.addSeparator()  # Separador antes de almacenamiento
        
        # 6. Gestor IQ (grabación/reproducción - último paso)
        if hasattr(self.main, 'iq_manager'):
            action = self.main.iq_manager.toggleViewAction()
            action.setText(" Gestor IQ")
            view_menu.addAction(action)
    
    # ===== Menú Ayuda (sin cambios) =====
        help_menu = menubar.addMenu("Ayuda")
        
        about_action = help_menu.addAction("ℹ️ Acerca de")
        about_action.triggered.connect(self.main.on_about)
        
        config_path_action = help_menu.addAction("📁 Ruta de Configuración")
        config_path_action.triggered.connect(self.main.on_show_config_path)

    def on_theme_selected(self, theme_key):
        """Manejador cuando se selecciona un tema del menú."""
        if not hasattr(self.main, 'theme_manager'):
            return
        
        self.logger.info(f"🎨 Tema seleccionado: {theme_key}")
        
        # Aplicar tema
        app = self.main.window()  # Obtener QApplication instance
        self.main.theme_manager.apply_theme_to_app(app, theme_key)
        
        # Actualizar checks en el menú
        self._update_theme_menu_checks(theme_key)
        
        # Actualizar colores del espectro
        if hasattr(self.main, 'spectrum_plot'):
            theme = self.main.theme_manager.get_theme_colors(theme_key)
            self.main.spectrum_plot.set_curve_colors(
                active_color=theme['spectrum_default'].name(),
                max_color=theme['max_hold_default'].name(),
                min_color=theme['min_hold_default'].name()
            )
        
        # Guardar preferencia
        if hasattr(self.main, 'config_manager'):
            self.main.config_manager.settings.setValue("theme", theme_key)

    def _update_theme_menu_checks(self, selected_key):
        """Actualiza los checks en el menú de temas."""
        # Buscar el menú Ver y dentro el submenú de temas
        menubar = self.main.menuBar()
        
        for action in menubar.actions():
            if action.text() == "Ver":
                view_menu = action.menu()
                if view_menu:
                    for view_action in view_menu.actions():
                        if view_action.text() == "Tema Visual":
                            theme_menu = view_action.menu()
                            if theme_menu:
                                for theme_action in theme_menu.actions():
                                    if theme_action.data():
                                        theme_action.setChecked(
                                            theme_action.data() == selected_key
                                        )
                            break
                break

    def on_customize_theme(self):
        """Abrir diálogo de personalización de temas (futuro)."""
        self.logger.info("⚙️ Personalización de temas - Pendiente de implementar")
        # Aquí se podría abrir un diálogo para modificar colores
    
    # -----------------------------------------------------------------------
    # ACTUALIZACIÓN DE VISUALIZACIÓN
    # -----------------------------------------------------------------------
    '''def update_viz_settings(self, settings):
        """Actualiza configuración de visualización"""
        # Debug colores
        if 'curve_colors' in settings:
            colors = settings['curve_colors']
            self.logger.info(f"🎨 Colores: {colors}")
            
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.set_curve_colors(
                    active_color=colors.get('active'),
                    max_color=colors.get('max'),
                    min_color=colors.get('min')
                )
        
        # Umbrales
        if 'min_threshold' in settings and 'max_threshold' in settings:
            self.logger.info(
                f"📊 Umbrales: min={settings['min_threshold']}, "
                f"max={settings['max_threshold']}"
            )
        
        # Colormap'''
    '''if 'color_map' in settings:
            if hasattr(self.main, 'waterfall'):
                self.main.waterfall.set_colormap(settings['color_map'])
            
            try:
                if hasattr(self.main, 'viz_widget'):
                    active, max_c, min_c = self.main.viz_widget.get_colors_from_colormap(
                        settings['color_map']
                    )
                    if hasattr(self.main, 'spectrum_plot'):
                        self.main.spectrum_plot.set_curve_colors(
                            active_color=active,
                            max_color=max_c,
                            min_color=min_c
                        )
            except Exception as e:
                self.logger.debug(f"No se pudieron aplicar colores: {e}")'''
        
        # Persistencia
    ''' if 'persistence' in settings:
            self.main.persistence_factor = settings['persistence'] / 100.0
        
        # Max/Min hold
        if 'plot_max' in settings:
            self.main.plot_max = settings['plot_max']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.enable_max_hold(self.main.plot_max)
        
        if 'plot_min' in settings:
            self.main.plot_min = settings['plot_min']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.enable_min_hold(self.main.plot_min)

        # ===== NUEVO: Reiniciar max/min =====
        if 'reset_max_min' in settings and settings['reset_max_min']:
            self.logger.info("🔄 Señal para reiniciar max/min recibida")
            self.main.reset_max_min_flag = True
        
        # ===== NUEVO: Configurar modo de hold =====
        if 'hold_mode' in settings:
            self.logger.info(f"⏱️ Modo hold: {settings['hold_mode']}, cada {settings.get('hold_seconds', 0)} s")
            # Aquí podrías guardar en configuración si es necesario
        
        # Limpiar persistencia
        if 'clear_persistence' in settings and settings['clear_persistence']:
            self._clear_persistence()
        
        # Rango de waterfall
        if 'min_threshold' in settings and 'max_threshold' in settings:
            if hasattr(self.main, 'waterfall'):
                self.main.waterfall.set_display_range(
                    settings['min_threshold'],
                    settings['max_threshold']
                )
    
    def _clear_persistence(self):
        """Limpia todos los buffers de persistencia"""
        if hasattr(self.main, 'waterfall'):
            self.main.waterfall.clear()
        if self.main.max_hold is not None:
            self.main.max_hold.fill(self.main.FLOOR_DB)
        if self.main.min_hold is not None:
            self.main.min_hold.fill(self.main.CEILING_DB)
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.clear_hold()'''

    
    # controller/ui_controller.py

    '''def update_viz_settings(self, settings):
        """Actualiza configuración de visualización"""
        
        # ===== 1. PROCESAR REINICIO DE CURVAS MAX/MIN (antes que nada) =====
        if 'reset_max_min' in settings and settings['reset_max_min']:
            self.logger.info("🔄 Reiniciando buffers de max/min")
            if self.main.max_hold is not None:
                # Reiniciar max_hold al valor actual del espectro
                # (esto se maneja en fft_controller al recibir el flag)
                self.main.reset_max_min_flag = True
            
            # Si también hay clear_persistence, no lo procesamos dos veces
            if 'clear_persistence' in settings:
                # Quitamos el flag para no limpiar waterfall dos veces
                pass
        
        # ===== 2. LIMPIAR WATERFALL (separado de max/min) =====
        if 'clear_persistence' in settings and settings['clear_persistence']:
            self.logger.info("🗑️ Limpiando waterfall")
            self._clear_persistence()  # Este método solo limpia waterfall
        
        # ===== 3. COLORES DE CURVAS =====
        if 'curve_colors' in settings:
            colors = settings['curve_colors']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.set_curve_colors(
                    active_color=colors.get('active'),
                    max_color=colors.get('max'),
                    min_color=colors.get('min')
                )
        
        # ===== 4. UMBRALES =====
        if 'min_threshold' in settings and 'max_threshold' in settings:
            if hasattr(self.main, 'waterfall'):
                self.main.waterfall.set_display_range(
                    settings['min_threshold'],
                    settings['max_threshold']
                )
        
        # ===== 5. PERSISTENCIA WATERFALL =====
        if 'persistence' in settings:
            self.main.persistence_factor = settings['persistence'] / 100.0
        
        # ===== 6. VISIBILIDAD DE CURVAS =====
        if 'plot_max' in settings:
            self.main.plot_max = settings['plot_max']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.enable_max_hold(self.main.plot_max)
        
        if 'plot_min' in settings:
            self.main.plot_min = settings['plot_min']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.enable_min_hold(self.main.plot_min)'''
    
    def update_viz_settings(self, settings):
        """Actualiza configuración de visualización - VERSIÓN COMPLETA"""
        
        # ===== 1. PROCESAR REINICIO DE CURVAS MAX/MIN =====
        if 'reset_max_min' in settings and settings['reset_max_min']:
            self.logger.info("🔄 Reiniciando buffers de max/min")
            if self.main.max_hold is not None:
                self.main.reset_max_min_flag = True
        
        # ===== 2. LIMPIAR WATERFALL =====
        if 'clear_persistence' in settings and settings['clear_persistence']:
            self.logger.info("🗑️ Limpiando waterfall")
            self._clear_persistence()
        
        # ===== 3. COLORES DE CURVAS =====
        if 'curve_colors' in settings:
            colors = settings['curve_colors']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.set_curve_colors(
                    active_color=colors.get('active'),
                    max_color=colors.get('max'),
                    min_color=colors.get('min')
                )
        
        # ===== 4. UMBRALES =====
        if 'min_threshold' in settings and 'max_threshold' in settings:
            if hasattr(self.main, 'waterfall'):
                self.main.waterfall.set_display_range(
                    settings['min_threshold'],
                    settings['max_threshold']
                )
        
        # ===== 5. PERSISTENCIA WATERFALL =====
        if 'persistence' in settings:
            self.main.persistence_factor = settings['persistence'] / 100.0
            self.logger.info(f"📊 Persistencia: {self.main.persistence_factor:.2f}")
        
        # ===== 6. VISIBILIDAD DE CURVAS =====
        if 'plot_max' in settings:
            self.main.plot_max = settings['plot_max']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.enable_max_hold(self.main.plot_max)
        
        if 'plot_min' in settings:
            self.main.plot_min = settings['plot_min']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.enable_min_hold(self.main.plot_min)
        
        # ===== 7. MODO DE HOLD (tiempo) =====
        if 'hold_mode' in settings:
            self.logger.info(
                f"⏱️ Modo hold: {settings['hold_mode']}, "
                f"cada {settings.get('hold_seconds', 0)} s"
            )

                # ===== NUEVO: Band Plan =====
        if 'show_band_plan' in settings:
            show_bands = settings['show_band_plan']
            self.logger.info(f"📡 Band Plan: {'mostrar' if show_bands else 'ocultar'}")
            
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.set_band_plan_visible(show_bands)
                
                # Log de cuántas bandas se están mostrando
                if show_bands and hasattr(self.main.spectrum_plot, 'band_plan'):
                    bands_count = len(self.main.spectrum_plot.band_plan.get_all_bands())
                    self.logger.info(f"📡 Mostrando {bands_count} bandas desde bands.json")

    def _clear_persistence(self):
        """Limpia SOLO el waterfall, no las curvas max/min"""
        if hasattr(self.main, 'waterfall'):
            self.main.waterfall.clear()
            self.logger.debug("💧 Waterfall limpiado")
    
    def update_display(self):
        """Actualiza UI periódicamente"""
        if self.main.is_running and self.main.bladerf:
            try:
                freq = self.main.bladerf.get_frequency()
                sample_rate = self.main.bladerf.sample_rate
                
                if hasattr(self.main, 'iq_manager'):
                    self.main.iq_manager.set_rf_info(freq/1e6, sample_rate)
            except:
                pass

    def on_theme_changed(self, theme_key):
        """Manejador cuando cambia el tema."""
        self.logger.info(f"🎨 Tema cambiado a: {theme_key}")
        
        # Actualizar colores del espectro según el tema
        if hasattr(self.main, 'spectrum_plot'):
            theme = self.main.theme_manager.get_theme_colors(theme_key)
            
            # Aplicar colores por defecto del tema
            self.main.spectrum_plot.set_curve_colors(
                active_color=theme['spectrum_default'].name(),
                max_color=theme['max_hold_default'].name(),
                min_color=theme['min_hold_default'].name()
            )
        
        # Guardar preferencia de tema en configuración
        if hasattr(self.main, 'config_manager'):
            self.main.config_manager.settings.setValue("theme", theme_key)

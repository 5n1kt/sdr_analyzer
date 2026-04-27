# -*- coding: utf-8 -*-

"""
UI Controller - Interface Management
=====================================
Manages the user interface: dock widgets, plots, menus, and theme integration.

This controller handles:
    - Creating and arranging dock widgets
    - Setting up spectrum plot and waterfall
    - Configuring menu bar with file, view, and help menus
    - Theme application and menu check synchronization
    - Visualization settings updates (persistence, hold curves, band plan)
"""

import logging
import pyqtgraph as pg
from PyQt5.QtWidgets import QHBoxLayout, QMessageBox
from PyQt5.QtCore import Qt

from widgets.rf_controls import RFControlsWidget
from widgets.fft_controls import FFTControlsWidget
from widgets.visualization import VisualizationWidget
from widgets.waterfall_plot import WaterfallPlot
from widgets.spectrum_plot import SpectrumPlot
from widgets.iq_manager_widget import IQManagerWidget
from widgets.frequency_spinner import FrequencySpinner

from widgets.artemis_widget import ArtemisWidget

from widgets.tscm_widget import TSCMWidget


# ============================================================================
# UI CONTROLLER
# ============================================================================

class UIController:
    """
    Manages all UI components and their interactions.
    """
    
    def __init__(self, main_controller):
        """
        Initialize UI controller.
        
        Args:
            main_controller: Reference to main controller
        """
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.UIController")
    
    # ------------------------------------------------------------------------
    # DOCK WIDGETS
    # ------------------------------------------------------------------------
    
    def setup_dock_widgets(self) -> None:
        """Create and arrange all dockable widgets."""
    
        # 1. RF Controls
        self.main.rf_widget = RFControlsWidget(self.main.bladerf)
        self.main.rf_widget.setObjectName("dock_rf_controls")
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.rf_widget)
        
        # 2. FFT Controls
        self.main.fft_widget = FFTControlsWidget()
        self.main.fft_widget.setObjectName("dock_fft_controls")
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.fft_widget)
        
        # 3. Visualization
        self.main.viz_widget = VisualizationWidget()
        self.main.viz_widget.setObjectName("dock_visualization")
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.viz_widget)
        
        # 4. Audio
        self.main.audio_widget = self.main.audio_ctrl.create_widget()
        self.main.audio_widget.setObjectName("dock_audio")
        self.main.addDockWidget(Qt.LeftDockWidgetArea, self.main.audio_widget)
        
        # 5. Detector
        self.main.detector_widget = self.main.detector_ctrl.create_widget()
        self.main.detector_widget.setObjectName("dock_signal_detector")
        self.main.addDockWidget(Qt.RightDockWidgetArea, self.main.detector_widget)
        
        # 6. IQ Manager
        self.main.iq_manager = IQManagerWidget(self.main)
        self.main.iq_manager.set_controller(self.main)
        self.main.iq_manager.setObjectName("dock_iq_manager")
        self.main.addDockWidget(Qt.RightDockWidgetArea, self.main.iq_manager)
        
        # 7. Artemis
        self.main.artemis_widget = ArtemisWidget(self.main)
        self.main.artemis_widget.setObjectName("dock_artemis")
        self.main.addDockWidget(Qt.RightDockWidgetArea, self.main.artemis_widget)
        
        # 8. TSCM
        self.main.tscm_widget = TSCMWidget(self.main)
        self.main.tscm_widget.setObjectName("dock_tscm")
        self.main.addDockWidget(Qt.RightDockWidgetArea, self.main.tscm_widget)
       
        
        # Conectar señal de sintonización
        self.main.artemis_widget.signal_selected.connect(
            self.main.on_frequency_changed_from_plot
        )
        
        # Conectar señal de carga para guardar configuración
        self.main.artemis_widget.database_loaded.connect(self._on_artemis_db_loaded)
        
        self.logger.info("✅ Dock widgets configured")
    
    # ------------------------------------------------------------------------
    # PLOTS
    # ------------------------------------------------------------------------
    
    def setup_plots(self) -> None:
        """Configure spectrum plot and waterfall."""
        pg.setConfigOptions(antialias=True, useOpenGL=False)
        
        # Clear existing layouts
        self._clear_layout(self.main.groupBox_spectrum.layout())
        self._clear_layout(self.main.groupBox_waterfall.layout())
        
        # Spectrum plot with interactive marker
        self.main.spectrum_plot = SpectrumPlot(self.main, self.logger)
        self.main.spectrum_plot.frequencyChanged.connect(
            self.main.on_frequency_changed_from_plot
        )
        self.main.groupBox_spectrum.layout().addWidget(
            self.main.spectrum_plot.plot_widget
        )
        
        # Waterfall plot
        self.main.waterfall = WaterfallPlot()
        waterfall_widget = self.main.waterfall.get_plot_widget()
        self.main.groupBox_waterfall.layout().addWidget(waterfall_widget)
        
        # Connect waterfall to visualization widget
        if hasattr(self.main, 'viz_widget'):
            self.main.viz_widget.set_waterfall(self.main.waterfall)
        
        # Setup frequency spinner
        self._setup_frequency_widget()
        
        self.logger.info("✅ Plots configured")
    
    def _setup_frequency_widget(self) -> None:
        """Configure the frequency spinner widget."""
        if not hasattr(self.main, 'widget_frequency_spinner'):
            self.logger.error("❌ widget_frequency_spinner not found")
            return
        
        # Get initial frequency
        initial_freq = 100.0
        if hasattr(self.main, 'doubleSpinBox_freq'):
            initial_freq = self.main.doubleSpinBox_freq.value()
        
        # Create frequency spinner
        self.main.frequency_spinner = FrequencySpinner(
            initial_freq_mhz=initial_freq,
            parent=self.main
        )
        
        # Add to layout
        container = self.main.widget_frequency_spinner
        if container.layout() is None:
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
        else:
            layout = container.layout()
            self._clear_layout(layout)
        
        container.setMinimumHeight(50)
        container.setMaximumHeight(55)
        layout.addWidget(self.main.frequency_spinner)
        
        # Connect signal
        self.main.frequency_spinner.frequencyChanged.connect(
            self.main.on_frequency_spinner_changed
        )
        
        self.logger.info(f"✅ FrequencySpinner created: {initial_freq:.3f} MHz")
    
    def _clear_layout(self, layout) -> None:
        """Clear all widgets from a layout."""
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
    
    # ------------------------------------------------------------------------
    # CONNECTIONS
    # ------------------------------------------------------------------------
    
    def setup_connections(self) -> None:
        """Connect UI signals to controllers."""
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
        
        self.logger.info("✅ Connections configured")
    
    # ------------------------------------------------------------------------
    # MENU
    # ------------------------------------------------------------------------
    
    def setup_menu(self) -> None:
        """Configure the application menu bar."""
        menubar = self.main.menuBar()
        
        # File Menu
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
        
        # View Menu with Theme Submenu
        view_menu = menubar.addMenu("Ver")
        
        # Theme submenu
        theme_menu = view_menu.addMenu("🎨 Tema Visual")
        
        if hasattr(self.main, 'theme_manager'):
            for theme_key, theme_name in self.main.theme_manager.get_theme_names():
                action = theme_menu.addAction(theme_name)
                action.setData(theme_key)
                action.setCheckable(True)
                if theme_key == self.main.theme_manager.current_theme:
                    action.setChecked(True)
                action.triggered.connect(
                    lambda checked, k=theme_key: self._on_theme_selected(k)
                )
        
        view_menu.addSeparator()
        
        # Dock toggle actions in specific order
        if hasattr(self.main, 'rf_widget'):
            action = self.main.rf_widget.toggleViewAction()
            action.setText(" Configuración RF")
            view_menu.addAction(action)
        
        if hasattr(self.main, 'fft_widget'):
            action = self.main.fft_widget.toggleViewAction()
            action.setText(" Configuración FFT")
            view_menu.addAction(action)
        
        if hasattr(self.main, 'viz_widget'):
            action = self.main.viz_widget.toggleViewAction()
            action.setText(" Visualización")
            view_menu.addAction(action)
        
        view_menu.addSeparator()
        
        if hasattr(self.main, 'audio_widget'):
            action = self.main.audio_widget.toggleViewAction()
            action.setText(" Demodulador")
            view_menu.addAction(action)

        view_menu.addSeparator()

        if hasattr(self.main, 'tscm_widget'):
            action = self.main.tscm_widget.toggleViewAction()
            action.setText("Análisis Diferencial")
            view_menu.addAction(action)
        
        if hasattr(self.main, 'detector_widget'):
            action = self.main.detector_widget.toggleViewAction()
            action.setText(" Detector de Señales")
            view_menu.addAction(action)
        
        view_menu.addSeparator()
        
        if hasattr(self.main, 'iq_manager'):
            action = self.main.iq_manager.toggleViewAction()
            action.setText(" Gestor IQ")
            view_menu.addAction(action)

        if hasattr(self.main, 'artemis_widget'):
            action = self.main.artemis_widget.toggleViewAction()
            action.setText(" Base de Datos Artemis")
            view_menu.addAction(action)

        # Help Menu
        help_menu = menubar.addMenu("Ayuda")
        
        about_action = help_menu.addAction("ℹ️ Acerca de")
        about_action.triggered.connect(self.main.on_about)
        
        config_path_action = help_menu.addAction("📁 Ruta de Configuración")
        config_path_action.triggered.connect(self.main.on_show_config_path)
        
        self.logger.info("✅ Menu configured")
    
    def _on_theme_selected(self, theme_key: str) -> None:
        """Handle theme selection from menu."""
        if not hasattr(self.main, 'theme_manager'):
            return
        
        self.logger.info(f"🎨 Theme selected: {theme_key}")
        
        # Apply theme
        app = self.main.window()
        self.main.theme_manager.apply_theme_to_app(app, theme_key)
        
        # Update menu checks
        self._update_theme_menu_checks(theme_key)
        
        # Update spectrum colors
        if hasattr(self.main, 'spectrum_plot'):
            theme = self.main.theme_manager.get_theme_colors(theme_key)
            self.main.spectrum_plot.set_curve_colors(
                active_color=theme['spectrum_default'].name(),
                max_color=theme['max_hold_default'].name(),
                min_color=theme['min_hold_default'].name()
            )
        
        # Save preference
        if hasattr(self.main, 'config_manager'):
            self.main.config_manager.settings.setValue("theme", theme_key)
    
    def _update_theme_menu_checks(self, selected_key: str) -> None:
        """Update check marks in theme submenu."""
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
    

    def _on_artemis_db_loaded(self):
        """Guarda la ruta cuando se carga una base de datos"""
        if hasattr(self.main, 'config_manager') and hasattr(self.main, 'artemis_widget'):
            self.main.config_manager._save_artemis_settings(self.main)
            self.logger.info("💾 Ruta de Artemis DB guardada en configuración")

    # ------------------------------------------------------------------------
    # VISUALIZATION SETTINGS
    # ------------------------------------------------------------------------
    
    def update_viz_settings(self, settings: dict) -> None:
        """
        Update visualization settings from widget.
        
        Args:
            settings: Dictionary with visualization parameters
        """
        # Process combined clear (waterfall + max/min)
        if settings.get('clear_persistence') or settings.get('reset_max_min'):
            if settings.get('clear_persistence'):
                self.logger.info("🗑️ Clearing waterfall")
                self._clear_persistence()
            
            if settings.get('reset_max_min'):
                self.logger.info("🔄 Resetting max/min buffers")
                if self.main.max_hold is not None:
                    self.main.reset_max_min_flag = True
                if hasattr(self.main, 'spectrum_plot'):
                    self.main.spectrum_plot.clear_hold()
            
            # Exit if only clear commands
            if set(settings.keys()) <= {'clear_persistence', 'reset_max_min'}:
                return
        
        # Curve colors
        if 'curve_colors' in settings:
            colors = settings['curve_colors']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.set_curve_colors(
                    active_color=colors.get('active'),
                    max_color=colors.get('max'),
                    min_color=colors.get('min')
                )
        
        # Display thresholds
        if 'min_threshold' in settings and 'max_threshold' in settings:
            if hasattr(self.main, 'waterfall'):
                self.main.waterfall.set_display_range(
                    settings['min_threshold'],
                    settings['max_threshold']
                )

            # Actualizar rango del medidor de potencia
            if hasattr(self.main, 'update_power_meter_range'):
                self.main.update_power_meter_range(
                    settings['min_threshold'],
                    settings['max_threshold']
                )
        
        # Waterfall persistence
        if 'persistence' in settings:
            self.main.persistence_factor = settings['persistence'] / 100.0
            self.logger.info(f"📊 Persistence: {self.main.persistence_factor:.2f}")
        
        # Hold curve visibility
        if 'plot_max' in settings:
            self.main.plot_max = settings['plot_max']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.enable_max_hold(self.main.plot_max)
        
        if 'plot_min' in settings:
            self.main.plot_min = settings['plot_min']
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.enable_min_hold(self.main.plot_min)
        
        # Hold mode
        if 'hold_mode' in settings:
            self.logger.info(
                f"⏱️ Hold mode: {settings['hold_mode']}, "
                f"every {settings.get('hold_seconds', 0)} s"
            )
        
        # Band plan
        if 'show_band_plan' in settings:
            show_bands = settings['show_band_plan']
            self.logger.info(f"📡 Band Plan: {'show' if show_bands else 'hide'}")
            
            if hasattr(self.main, 'spectrum_plot'):
                self.main.spectrum_plot.set_band_plan_visible(show_bands)
                
                if show_bands and hasattr(self.main.spectrum_plot, 'band_plan'):
                    bands_count = len(self.main.spectrum_plot.band_plan.get_all_bands())
                    self.logger.info(f"📡 Showing {bands_count} bands from bands.json")
    
    def _clear_persistence(self) -> None:
        """Clear only the waterfall, not max/min curves."""
        if hasattr(self.main, 'waterfall'):
            self.main.waterfall.clear()
            self.logger.debug("💧 Waterfall cleared")
    
    # ------------------------------------------------------------------------
    # DISPLAY UPDATE
    # ------------------------------------------------------------------------
    
    def update_display(self) -> None:
        """Periodic UI update (called by timer)."""
        if self.main.is_running and self.main.bladerf:
            try:
                freq = self.main.bladerf.frequency
                sample_rate = self.main.bladerf.sample_rate
                
                if hasattr(self.main, 'iq_manager'):
                    self.main.iq_manager.set_rf_info(freq/1e6, sample_rate)
            except Exception:
                pass
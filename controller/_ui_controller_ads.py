# controller/ui_controller_ads.py
# -*- coding: utf-8 -*-

"""
UI Controller with PyQtAds (Qt Advanced Docking System)
"""

import logging
import pyqtgraph as pg
from PyQt5.QtWidgets import QHBoxLayout, QWidget, QVBoxLayout, QSplitter
from PyQt5.QtCore import Qt
from PyQtAds import CDockManager, DockWidgetArea

from widgets.rf_controls import RFControlsWidget
from widgets.fft_controls import FFTControlsWidget
from widgets.visualization import VisualizationWidget
from widgets.waterfall_plot import WaterfallPlot
from widgets.spectrum_plot import SpectrumPlot
from widgets.iq_manager_widget import IQManagerWidget
from widgets.frequency_spinner import FrequencySpinner
from widgets.artemis_widget import ArtemisWidget
from widgets.tscm_widget import TSCMWidget
from widgets.station_info_widget import StationInfoWidget


class UIControllerADS:
    """
    UI Controller using PyQtAds (Qt Advanced Docking System)
    Permite organizar los 10+ dock widgets en múltiples monitores
    """
    
    def __init__(self, main_controller):
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.UIControllerADS")
        self.dock_manager = None
    
    def setup_dock_manager(self):
        """
        Inicializar el Dock Manager de PyQtAds
        Este reemplaza el sistema nativo de QDockWidget
        """
        # Crear el dock manager (se convierte en el central widget)
        self.dock_manager = CDockManager(self.main)
        
        # Configurar opciones avanzadas
        self.dock_manager.setConfigFlags(
            CDockManager.DefaultOpaqueConfig |
            CDockManager.DockAreaHasUndockButton |
            CDockManager.DockAreaHasCloseButton
        )
        
        self.logger.info("✅ PyQtAds Dock Manager initialized")
        return self.dock_manager
    
    def setup_dock_widgets(self):
        """
        Crear y organizar todos los dock widgets usando PyQtAds
        Soporta organización en múltiples monitores y pestañas
        """
        
        # ========== ÁREA IZQUIERDA ==========
        # 1. RF Controls
        self.main.rf_widget = RFControlsWidget(self.main.bladerf)
        self.main.rf_widget.setObjectName("dock_rf_controls")
        self.main.rf_widget.setWindowTitle("CONFIGURACIÓN RF")
        
        # 2. FFT Controls
        self.main.fft_widget = FFTControlsWidget()
        self.main.fft_widget.setObjectName("dock_fft_controls")
        self.main.fft_widget.setWindowTitle("CONFIGURACIÓN FFT")
        
        # 3. Visualization
        self.main.viz_widget = VisualizationWidget()
        self.main.viz_widget.setObjectName("dock_visualization")
        self.main.viz_widget.setWindowTitle("VISUALIZACIÓN")
        
        # 4. Audio/Demodulador
        self.main.audio_widget = self.main.audio_ctrl.create_widget()
        self.main.audio_widget.setObjectName("dock_audio")
        self.main.audio_widget.setWindowTitle("DEMODULADOR")
        
        # Añadir al área izquierda
        self.dock_manager.addDockWidget(
            DockWidgetArea.LeftDockWidgetArea, 
            self.main.rf_widget
        )
        self.dock_manager.addDockWidget(
            DockWidgetArea.LeftDockWidgetArea, 
            self.main.fft_widget
        )
        self.dock_manager.addDockWidget(
            DockWidgetArea.LeftDockWidgetArea, 
            self.main.viz_widget
        )
        self.dock_manager.addDockWidget(
            DockWidgetArea.BottomDockWidgetArea, 
            self.main.audio_widget
        )
        
        # Agrupar RF y FFT en pestañas
        self.dock_manager.tabifyDockWidget(self.main.fft_widget, self.main.rf_widget)
        self.dock_manager.tabifyDockWidget(self.main.viz_widget, self.main.fft_widget)
        
        # ========== ÁREA DERECHA ==========
        # 5. Station Info
        self.main.station_widget = StationInfoWidget(self.main)
        self.main.station_widget.setObjectName("dock_station")
        self.main.station_widget.setWindowTitle("ESTACIÓN")
        
        # 6. IQ Manager
        self.main.iq_manager = IQManagerWidget(self.main)
        self.main.iq_manager.set_controller(self.main)
        self.main.iq_manager.setObjectName("dock_iq_manager")
        self.main.iq_manager.setWindowTitle("GESTOR IQ")
        
        # 7. Artemis DB
        self.main.artemis_widget = ArtemisWidget(self.main)
        self.main.artemis_widget.setObjectName("dock_artemis")
        self.main.artemis_widget.setWindowTitle("BASE DE DATOS ARTEMIS")
        
        # 8. Signal Detector
        self.main.detector_widget = self.main.detector_ctrl.create_widget()
        self.main.detector_widget.setObjectName("dock_signal_detector")
        self.main.detector_widget.setWindowTitle("DETECTOR DE SEÑALES")
        
        # 9. TSCM Analysis
        self.main.tscm_widget = TSCMWidget(self.main)
        self.main.tscm_widget.setObjectName("dock_tscm")
        self.main.tscm_widget.setWindowTitle("ANÁLISIS Δ (TSCM)")
        
        # Añadir al área derecha
        self.dock_manager.addDockWidget(
            DockWidgetArea.RightDockWidgetArea, 
            self.main.station_widget
        )
        self.dock_manager.addDockWidget(
            DockWidgetArea.RightDockWidgetArea, 
            self.main.iq_manager
        )
        self.dock_manager.addDockWidget(
            DockWidgetArea.RightDockWidgetArea, 
            self.main.artemis_widget
        )
        self.dock_manager.addDockWidget(
            DockWidgetArea.RightDockWidgetArea, 
            self.main.detector_widget
        )
        self.dock_manager.addDockWidget(
            DockWidgetArea.RightDockWidgetArea, 
            self.main.tscm_widget
        )
        
        # Agrupar en pestañas el área derecha
        self.dock_manager.tabifyDockWidget(self.main.iq_manager, self.main.station_widget)
        self.dock_manager.tabifyDockWidget(self.main.artemis_widget, self.main.iq_manager)
        self.dock_manager.tabifyDockWidget(self.main.detector_widget, self.main.artemis_widget)
        self.dock_manager.tabifyDockWidget(self.main.tscm_widget, self.main.detector_widget)
        
        self.logger.info("✅ 9 dock widgets configurados con PyQtAds")
    
    def setup_central_area(self):
        """
        Configurar el área central con espectro y waterfall
        Esta área NO es un dock, es el contenido principal
        """
        # Crear widget central con splitter vertical
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Splitter vertical para espectro y waterfall
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(3)
        
        # Grupo de espectro
        from PyQt5.QtWidgets import QGroupBox
        spectrum_group = QGroupBox("ESPECTRO")
        spectrum_layout = QVBoxLayout(spectrum_group)
        spectrum_layout.setContentsMargins(1, 8, 1, 1)
        
        # Grupo de waterfall
        waterfall_group = QGroupBox("WATERFALL")
        waterfall_layout = QVBoxLayout(waterfall_group)
        waterfall_layout.setContentsMargins(1, 8, 1, 1)
        
        splitter.addWidget(spectrum_group)
        splitter.addWidget(waterfall_group)
        splitter.setSizes([400, 300])
        
        layout.addWidget(splitter)
        
        # Establecer como widget central
        self.main.setCentralWidget(central_widget)
        
        # Guardar referencias para los plots
        self.main.spectrum_container = spectrum_group
        self.main.waterfall_container = waterfall_group
        
        return spectrum_group, waterfall_group
    
    def setup_plots(self):
        """Configurar los plots en el área central"""
        pg.setConfigOptions(antialias=True, useOpenGL=False)
        
        # Crear área central
        spectrum_group, waterfall_group = self.setup_central_area()
        
        # Limpiar layouts existentes
        self._clear_layout(spectrum_group.layout())
        self._clear_layout(waterfall_group.layout())
        
        # Spectrum plot con marcador interactivo
        self.main.spectrum_plot = SpectrumPlot(self.main, self.logger)
        self.main.spectrum_plot.frequencyChanged.connect(
            self.main.on_frequency_changed_from_plot
        )
        spectrum_group.layout().addWidget(self.main.spectrum_plot.plot_widget)
        
        # Waterfall plot
        self.main.waterfall = WaterfallPlot()
        waterfall_widget = self.main.waterfall.get_plot_widget()
        waterfall_group.layout().addWidget(waterfall_widget)
        
        # Conectar waterfall al widget de visualización
        if hasattr(self.main, 'viz_widget'):
            self.main.viz_widget.set_waterfall(self.main.waterfall)
        
        # Configurar spinner de frecuencia
        self._setup_frequency_widget()
        
        self.logger.info("✅ Plots configurados en área central")
    
    def _setup_frequency_widget(self):
        """Configurar el widget de frecuencia en la barra superior"""
        if not hasattr(self.main, 'widget_frequency_spinner'):
            self.logger.error("❌ widget_frequency_spinner not found")
            return
        
        initial_freq = 100.0
        if hasattr(self.main, 'doubleSpinBox_freq'):
            initial_freq = self.main.doubleSpinBox_freq.value()
        
        self.main.frequency_spinner = FrequencySpinner(
            initial_freq_mhz=initial_freq,
            parent=self.main
        )
        
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
        
        self.main.frequency_spinner.frequencyChanged.connect(
            self.main.on_frequency_spinner_changed
        )
        
        self.logger.info(f"✅ FrequencySpinner configurado")
    
    def _clear_layout(self, layout):
        """Limpiar todos los widgets de un layout"""
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
    
    def setup_connections(self):
        """Conectar señales de los widgets"""
        # Botones principales
        self.main.pushButton_start_stop_main.clicked.connect(self.main.toggle_rx)
        
        # Widgets de configuración
        if hasattr(self.main, 'rf_widget'):
            self.main.rf_widget.settings_changed.connect(self.main.update_rf_settings)
        
        if hasattr(self.main, 'fft_widget'):
            self.main.fft_widget.settings_changed.connect(self.main.update_fft_settings)
        
        if hasattr(self.main, 'viz_widget'):
            self.main.viz_widget.settings_changed.connect(self.main.update_viz_settings)
        
        # Control de frecuencia
        if hasattr(self.main, 'doubleSpinBox_freq'):
            self.main.doubleSpinBox_freq.editingFinished.connect(
                self.main.on_double_spinbox_freq_changed
            )
        
        # IQ Manager
        if hasattr(self.main, 'iq_manager'):
            self.main.iq_manager.playback_requested.connect(
                self.main.on_playback_requested
            )
        
        # Artemis
        if hasattr(self.main, 'artemis_widget'):
            self.main.artemis_widget.signal_selected.connect(
                self.main.on_frequency_changed_from_plot
            )
            self.main.artemis_widget.database_loaded.connect(self._on_artemis_db_loaded)
        
        self.logger.info("✅ Conexiones configuradas")
    
    def setup_menu(self):
        """Configurar el menú con opciones para mostrar/ocultar docks"""
        menubar = self.main.menuBar()
        
        # Menú Archivo
        file_menu = menubar.addMenu("Archivo")
        
        save_action = file_menu.addAction("💾 Guardar Layout")
        save_action.triggered.connect(self.save_current_layout)
        save_action.setShortcut("Ctrl+S")
        
        load_action = file_menu.addAction("📂 Cargar Layout")
        load_action.triggered.connect(self.load_saved_layout)
        load_action.setShortcut("Ctrl+L")
        
        file_menu.addSeparator()
        
        reset_action = file_menu.addAction("🔄 Resetear Layout")
        reset_action.triggered.connect(self.reset_layout)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("❌ Salir")
        exit_action.triggered.connect(self.main.close)
        exit_action.setShortcut("Ctrl+Q")
        
        # Menú Ver - Docks
        view_menu = menubar.addMenu("Ver")
        
        # Añadir acciones de toggle para cada dock
        docks = [
            (self.main.rf_widget, "Configuración RF"),
            (self.main.fft_widget, "Configuración FFT"),
            (self.main.viz_widget, "Visualización"),
            (self.main.audio_widget, "Demodulador"),
            (self.main.station_widget, "Estación"),
            (self.main.iq_manager, "Gestor IQ"),
            (self.main.artemis_widget, "Base de Datos"),
            (self.main.detector_widget, "Detector de Señales"),
            (self.main.tscm_widget, "Análisis TSCM"),
        ]
        
        for dock, name in docks:
            if dock:
                action = dock.toggleViewAction()
                action.setText(f" {name}")
                view_menu.addAction(action)
        
        # Menú Ayuda
        help_menu = menubar.addMenu("Ayuda")
        
        about_action = help_menu.addAction("ℹ️ Acerca de")
        about_action.triggered.connect(self.main.on_about)
        
        self.logger.info("✅ Menú configurado")
    
    def save_current_layout(self):
        """Guardar el layout actual de los docks"""
        import os
        from PyQt5.QtWidgets import QFileDialog
        
        filename, _ = QFileDialog.getSaveFileName(
            self.main,
            "Guardar Layout de Docks",
            "layouts/",
            "Layout files (*.layout);;All files (*)"
        )
        
        if filename:
            os.makedirs("layouts", exist_ok=True)
            if not filename.endswith('.layout'):
                filename += '.layout'
            
            state = self.dock_manager.saveState()
            with open(filename, 'wb') as f:
                f.write(state)
            
            self.logger.info(f"💾 Layout guardado: {filename}")
            self.main.statusbar.showMessage(f"Layout guardado: {filename}", 2000)
    
    def load_saved_layout(self):
        """Cargar un layout guardado"""
        from PyQt5.QtWidgets import QFileDialog
        
        filename, _ = QFileDialog.getOpenFileName(
            self.main,
            "Cargar Layout de Docks",
            "layouts/",
            "Layout files (*.layout);;All files (*)"
        )
        
        if filename:
            with open(filename, 'rb') as f:
                state = f.read()
            
            self.dock_manager.restoreState(state)
            self.logger.info(f"📐 Layout cargado: {filename}")
            self.main.statusbar.showMessage(f"Layout cargado: {filename}", 2000)
    
    def reset_layout(self):
        """Resetear el layout a la configuración por defecto"""
        from PyQt5.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self.main,
            "Resetear Layout",
            "¿Restaurar layout por defecto?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Limpiar todos los docks
            self.dock_manager.removeAllDockWidgets()
            
            # Reconfigurar
            self.setup_dock_widgets()
            
            self.logger.info("🔄 Layout reseteado a configuración por defecto")
            self.main.statusbar.showMessage("Layout reseteado", 2000)
    
    def _on_artemis_db_loaded(self):
        """Guardar ruta de Artemis DB cuando se carga"""
        if hasattr(self.main, 'config_manager') and hasattr(self.main, 'artemis_widget'):
            self.main.config_manager._save_artemis_settings(self.main)
            self.logger.info("💾 Ruta de Artemis DB guardada")


    def _load_auto_layout(self):
        """Cargar layout automático si existe"""
        import os
        auto_layout = "layouts/auto.layout"
        if os.path.exists(auto_layout):
            try:
                with open(auto_layout, 'rb') as f:
                    state = f.read()
                self.dock_manager.restoreState(state)
                self.logger.info(f"📐 Layout automático cargado: {auto_layout}")
            except Exception as e:
                self.logger.warning(f"No se pudo cargar layout automático: {e}")
    
    def save_auto_layout(self):
        """Guardar layout automático"""
        import os
        try:
            os.makedirs("layouts", exist_ok=True)
            state = self.dock_manager.saveState()
            with open("layouts/auto.layout", 'wb') as f:
                f.write(state)
            self.logger.info("💾 Layout automático guardado")
            return True
        except Exception as e:
            self.logger.warning(f"No se pudo guardar layout: {e}")
            return False
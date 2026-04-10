# widgets/theme_selector_widget.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
from PyQt5.QtWidgets import QDockWidget, QApplication
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QColor, QPalette
from PyQt5.uic import loadUi
import logging

from utils.theme_manager import ThemeManager


# =======================================================================
# WIDGET SELECTOR DE TEMAS
# =======================================================================
class ThemeSelectorWidget(QDockWidget):
    """
    Widget para seleccionar y aplicar temas visuales.
    """
    
    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    theme_changed = pyqtSignal(str)  # Nombre del tema seleccionado
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # Cargar UI
        loadUi('ui/theme_selector_widget.ui', self)
        
        # Inicializar gestor de temas
        self.theme_manager = ThemeManager()
        
        # Estado
        self.current_theme = 'dark'
        
        # Configurar UI
        self.setup_ui()
        self.setup_connections()
        
        self.logger.info("✅ ThemeSelectorWidget creado")
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN DE UI
    # -----------------------------------------------------------------------
    def setup_ui(self):
        """Configura elementos de UI."""
        # Cargar temas en combo box
        for theme_key, theme_name in self.theme_manager.get_theme_names():
            self.comboBox_theme.addItem(theme_name, theme_key)
        
        # Seleccionar tema oscuro por defecto
        index = self.comboBox_theme.findData('dark')
        self.comboBox_theme.setCurrentIndex(index)
        
        # Actualizar vista previa
        self.update_preview('dark')
    
    def setup_connections(self):
        """Conecta señales."""
        self.comboBox_theme.currentIndexChanged.connect(self.on_theme_selected)
        self.pushButton_apply.clicked.connect(self.on_apply_clicked)
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS
    # -----------------------------------------------------------------------
    def update_preview(self, theme_key):
        """Actualiza la vista previa del tema seleccionado."""
        theme = self.theme_manager.get_theme_colors(theme_key)
        
        # Actualizar colores de vista previa
        self.label_preview_bg.setStyleSheet(
            f"background-color: {theme['background'].name()}; "
            f"color: {theme['foreground'].name()}; "
            f"border: 1px solid {theme['grid'].name()};"
        )
        
        self.label_preview_text.setStyleSheet(
            f"background-color: {theme['text_bg'].name()}; "
            f"color: {theme['text_fg'].name()}; "
            f"border: 1px solid {theme['grid'].name()};"
        )
        
        self.label_preview_grid.setStyleSheet(
            f"background-color: {theme['grid'].name()}; "
            f"color: {theme['background'].name()}; "
            f"border: 1px solid {theme['grid'].name()};"
        )
        
        # Actualizar descripción
        self.label_description.setText(theme['description'])
    
    def apply_theme(self, theme_key):
        """Aplica el tema a la aplicación."""
        app = QApplication.instance()
        theme = self.theme_manager.apply_theme_to_app(app, theme_key)
        
        self.current_theme = theme_key
        self.theme_changed.emit(theme_key)
        
        self.logger.info(f"🎨 Tema aplicado: {theme['name']}")
    
    # -----------------------------------------------------------------------
    # SLOTS
    # -----------------------------------------------------------------------
    def on_theme_selected(self, index):
        """Manejador cuando se selecciona un tema en el combo box."""
        theme_key = self.comboBox_theme.currentData()
        self.update_preview(theme_key)
    
    def on_apply_clicked(self):
        """Manejador cuando se hace click en Aplicar."""
        theme_key = self.comboBox_theme.currentData()
        self.apply_theme(theme_key)
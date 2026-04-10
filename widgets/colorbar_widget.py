# widgets/colorbar_widget.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import pyqtgraph as pg
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import pyqtSignal
import logging


# =======================================================================
# WIDGET DE BARRA DE COLOR SIMPLIFICADO
# =======================================================================
class ColorBarWidget(QWidget):
    """Widget de barra de color con histograma - VERSIÓN SIMPLIFICADA"""
    
    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    levels_changed = pyqtSignal(float, float)
    colormap_changed = pyqtSignal(str)
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # Layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Crear HistogramLUTWidget
        self.histogram = pg.HistogramLUTWidget()
        self.histogram.setFixedWidth(80)
        self.histogram.setMaximumWidth(100)
        
        # Configurar gradiente inicial
        self.histogram.item.gradient.loadPreset('viridis')
        
        # Guardar referencia al gradient item
        self.gradient = self.histogram.item.gradient
        
        # Conectar señales
        self.histogram.item.sigLevelChangeFinished.connect(self._on_levels_changed)
        self.histogram.item.sigLookupTableChanged.connect(self._on_colormap_changed)
        
        # Añadir al layout
        self.layout.addWidget(self.histogram)
        
        self.logger.debug("✅ ColorBarWidget creado")
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS
    # -----------------------------------------------------------------------
    def set_image_item(self, image_item):
        """Conectar al ImageItem del waterfall"""
        if image_item is not None:
            self.histogram.setImageItem(image_item)
            self.logger.debug("📊 Colorbar conectado al ImageItem")
    
    def set_levels(self, min_level, max_level):
        """Establecer niveles mínimo y máximo"""
        self.histogram.setLevels(min_level, max_level)
        self.logger.debug(f"📊 Niveles colorbar: {min_level:.1f} - {max_level:.1f} dB")
    
    def set_colormap(self, colormap_name):
        """Cambiar mapa de colores"""
        try:
            preset_name = colormap_name.lower()
            self.histogram.item.gradient.loadPreset(preset_name)
            self.logger.debug(f"🎨 Mapa de colores cambiado a: {colormap_name}")
        except Exception as e:
            self.logger.error(f"Error cambiando colormap a {colormap_name}: {e}")
            try:
                self.histogram.item.gradient.loadPreset('viridis')
            except:
                pass
    
    def auto_range(self):
        """Autoajustar rango basado en los datos"""
        self.histogram.autoHistogramRange()
        self.logger.debug("📊 Auto range aplicado")
    
    def get_levels(self):
        """Obtener niveles actuales"""
        return self.histogram.getLevels()
    
    # -----------------------------------------------------------------------
    # SLOTS PRIVADOS
    # -----------------------------------------------------------------------
    def _on_levels_changed(self):
        """Manejador cuando cambian los niveles"""
        levels = self.histogram.getLevels()
        if levels and len(levels) >= 2:
            self.logger.debug(f"📊 Niveles ajustados: {levels[0]:.1f} - {levels[1]:.1f} dB")
            self.levels_changed.emit(levels[0], levels[1])
    
    def _on_colormap_changed(self):
        """Manejador cuando cambia el mapa de colores"""
        self.logger.debug("🎨 Mapa de colores cambiado manualmente")
        self.colormap_changed.emit("unknown")
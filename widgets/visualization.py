# widgets/visualization.py - Versión corregida

# =======================================================================
# IMPORTS
# =======================================================================
from PyQt5.QtWidgets import QDockWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QSpinBox, QWidget, QPushButton
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from PyQt5.uic import loadUi
import pyqtgraph as pg
import numpy as np
import logging


# =======================================================================
# CONSTANTES - COLORMAPS VÁLIDOS DE PYQTGRAPH
# =======================================================================
COLORMAPS_VALIDOS = {
    # Perceptuales (recomendados para datos continuos)
    'viridis': {'name': 'Viridis', 'desc': 'Perceptual uniforme', 'type': 'perceptual'},
    'plasma': {'name': 'Plasma', 'desc': 'Perceptual uniforme', 'type': 'perceptual'},
    'inferno': {'name': 'Inferno', 'desc': 'Perceptual uniforme', 'type': 'perceptual'},
    'magma': {'name': 'Magma', 'desc': 'Perceptual uniforme', 'type': 'perceptual'},
    
    # Térmicos
    'thermal': {'name': 'Térmico', 'desc': 'Negro → Rojo → Amarillo', 'type': 'thermal'},
    'flame': {'name': 'Llama', 'desc': 'Negro → Rojo → Naranja', 'type': 'thermal'},
    'yellowy': {'name': 'Amarillo', 'desc': 'Negro → Amarillo', 'type': 'thermal'},
    
    # Divergentes
    'bipolar': {'name': 'Bipolar', 'desc': 'Azul → Blanco → Rojo', 'type': 'divergent'},
    'cyclic': {'name': 'Cíclico', 'desc': 'Para ángulos/fases', 'type': 'cyclic'},
    
    # Grises
    'greyclip': {'name': 'Gris con clipping', 'desc': 'Escala de grises con extremos recortados', 'type': 'grayscale'},
    'grey': {'name': 'Gris', 'desc': 'Escala de grises lineal', 'type': 'grayscale'},
    
    # Arcoíris (clásico)
    'spectrum': {'name': 'Espectro', 'desc': 'Arcoíris completo', 'type': 'rainbow'}
}

# Nombres para mostrar en el ComboBox (en orden)
COLORMAPS_DISPLAY = [
    ('viridis', 'Viridis'),
    ('plasma', 'Plasma'),
    ('inferno', 'Inferno'),
    ('magma', 'Magma'),
    ('---', '──────────'),
    ('thermal', 'Térmico'),
    ('flame', 'Llama'),
    ('yellowy', 'Amarillo'),
    ('---', '──────────'),
    ('bipolar', 'Bipolar'),
    ('cyclic', 'Cíclico'),
    ('---', '──────────'),
    ('grey', 'Gris'),
    ('greyclip', 'Gris clipping'),
    ('---', '──────────'),
    ('spectrum', 'Espectro')
]


# =======================================================================
# WIDGET DE CONTROL DE VISUALIZACIÓN
# =======================================================================
class VisualizationWidget(QDockWidget):
    """Widget de control de visualización - CON COLORBAR FUNCIONAL"""
    
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
        
        # Cargar UI
        loadUi('ui/visualization_widget.ui', self)
        
        # ===== ESTADO =====
        self.min_threshold = -120
        self.max_threshold = 0
        self.waterfall = None
        self.imageitem = None
        self.update_count = 0
        self.current_colormap = 'viridis'  # Por defecto
        self.colorbar = None

        # ===== NUEVO: Control de tiempo para max/min =====
        self.hold_mode = 'manual'  # 'manual', 'timed'
        self.hold_seconds = 0
        self.hold_timer = QTimer()
        self.hold_timer.timeout.connect(self.on_hold_timeout)
        
        # ===== CONFIGURAR UI =====
        self.setup_ui()
        self.setup_connections()
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN DE UI
    # -----------------------------------------------------------------------
    def setup_ui(self):
        """Configura elementos de UI"""
        # Limpiar ComboBox
        self.comboBox_color_map.clear()
        
        # Añadir opciones agrupadas
        for key, display in COLORMAPS_DISPLAY:
            if key == '---':
                self.comboBox_color_map.insertSeparator(self.comboBox_color_map.count())
            else:
                self.comboBox_color_map.addItem(display, key)
        
        # Seleccionar viridis por defecto
        index = self.comboBox_color_map.findData('viridis')
        self.comboBox_color_map.setCurrentIndex(index)
        
        # Slider de persistencia
        self.horizontalSlider_persistence.setRange(1, 99)
        self.horizontalSlider_persistence.setValue(50)
        self.horizontalSlider_persistence.valueChanged.connect(
            lambda v: self.label_persistence_value.setText(f"{v}%")
        )
        
        # Checkboxes
        self.checkBox_plot_max.setChecked(False)
        self.checkBox_plot_min.setChecked(False)
        
        # Conectar señales de los spinboxes de umbral (ya existen en el UI)
        self.min_spin.valueChanged.connect(self.on_threshold_changed)
        self.max_spin.valueChanged.connect(self.on_threshold_changed)
        
        # Colorbar
        self._setup_colorbar()
        
        # Botones
        self.pushButton_auto_range.clicked.connect(self.auto_range)
        self.pushButton_clear_persistence.clicked.connect(self.clear_persistence)

        # ===== NUEVO: Configurar comboBox_hold_time =====
        self.comboBox_hold_time.setCurrentIndex(0)  # Manual por defecto
        self.comboBox_hold_time.currentIndexChanged.connect(self.on_hold_time_changed)
        
        # Botón de prueba
        self.pushButton_test.clicked.connect(self.test_colors)
    
    def _setup_colorbar(self):
        """Configura la barra de color usando GradientEditorItem"""
        try:
            frame = self.frame_colorbar
            
            if frame.layout() is None:
                frame.setLayout(QVBoxLayout())
            
            layout = frame.layout()
            
            # Limpiar widgets existentes
            self._clear_layout(layout)
            
            # Crear HistogramLUTWidget
            self.colorbar = pg.HistogramLUTWidget()
            self.colorbar.setFixedWidth(80)
            self.colorbar.setMaximumWidth(100)
            self.colorbar.setMinimumHeight(200)

            # Crear HistogramLUTWidget (ahora horizontal)
            '''self.colorbar = pg.HistogramLUTWidget(orientation='horizontal')
            self.colorbar.setFixedHeight(80)  # Altura fija para horizontal
            self.colorbar.setMinimumWidth(300)'''
            
            # Conectar señales
            self.colorbar.item.sigLevelChangeFinished.connect(self._on_colorbar_levels_changed)
            self.colorbar.item.sigLookupTableChanged.connect(self._on_colorbar_colormap_changed)
            
            layout.addWidget(self.colorbar)
            
            # Aplicar colormap inicial
            self._apply_colormap_to_colorbar('viridis')
            
            self.logger.info("✅ Colorbar creado correctamente")
            
        except Exception as e:
            self.logger.error(f"❌ Error configurando colorbar: {e}")
            import traceback
            traceback.print_exc()
    
    def _clear_layout(self, layout):
        """Limpia un layout"""
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    # -----------------------------------------------------------------------
    # CONEXIONES DE SEÑALES
    # -----------------------------------------------------------------------
    def setup_connections(self):
        """Conecta señales"""
        self.comboBox_color_map.currentIndexChanged.connect(self.on_colormap_changed)
        self.horizontalSlider_persistence.valueChanged.connect(self.on_setting_changed)
        self.checkBox_plot_max.stateChanged.connect(self.on_setting_changed)
        self.checkBox_plot_min.stateChanged.connect(self.on_setting_changed)

         # ===== NUEVO: Conectar checkbox de Band Plan =====
        self.checkBox_show_bands.stateChanged.connect(self.on_show_bands_changed)
    
    # -----------------------------------------------------------------------
    # MÉTODOS DE COLORMAP
    # -----------------------------------------------------------------------
    def _apply_colormap_to_colorbar(self, cmap_name):
        """Aplica un colormap al colorbar usando loadPreset"""
        try:
            self.colorbar.item.gradient.loadPreset(cmap_name)
            self.logger.debug(f"🎨 Colorbar preset: {cmap_name}")
        except Exception as e:
            self.logger.error(f"Error aplicando preset {cmap_name}: {e}")
            # Fallback a viridis
            self.colorbar.item.gradient.loadPreset('viridis')
    
    def _apply_colormap_to_waterfall(self, cmap_name):
        """Aplica un colormap al waterfall usando el método correcto"""
        if not self.waterfall:
            return
        
        try:
            # Obtener el lookup table del gradient
            lookup_table = self.colorbar.item.gradient.getLookupTable(512)
            
            # Aplicar directamente al imageitem
            self.waterfall.imageitem.setLookupTable(lookup_table)
            
            self.logger.debug(f"🌊 Waterfall actualizado con lookup table")
        except Exception as e:
            self.logger.error(f"Error aplicando colormap a waterfall: {e}")
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS
    # -----------------------------------------------------------------------
    def set_waterfall(self, waterfall):
        """Conecta al waterfall"""
        self.waterfall = waterfall
        self.logger.info("🌊 Waterfall conectado")
        
        if waterfall is not None and hasattr(self, 'colorbar'):
            if hasattr(waterfall, 'imageitem'):
                self.imageitem = waterfall.imageitem
                self.colorbar.setImageItem(self.imageitem)
                self.logger.info("🔗 Colorbar conectado al imageitem")
                
                # Configuración inicial de niveles
                self.colorbar.setLevels(self.min_threshold, self.max_threshold)
                self.colorbar.setHistogramRange(self.min_threshold, self.max_threshold)
                self.colorbar.autoHistogramRange()
                
                # Aplicar colormap inicial
                self._apply_colormap_to_waterfall(self.current_colormap)
                
                # Conectar señal de actualización
                if hasattr(waterfall, 'updated'):
                    waterfall.updated.connect(self._on_waterfall_updated)
                
        # ===== NUEVO: Guardar referencia al controlador principal para acceder al espectro =====
        if hasattr(self, 'main_controller'):
            self.main_controller = None  # Se seteará después


    def on_hold_time_changed(self, index):
        """Cambia el modo de persistencia de max/min"""
        texts = ['Manual', '1 s', '2 s', '5 s', '10 s', '30 s', '60 s']
        seconds = [0, 1, 2, 5, 10, 30, 60]
        
        self.hold_mode = 'manual' if index == 0 else 'timed'
        self.hold_seconds = seconds[index]
        
        # Detener timer anterior
        self.hold_timer.stop()
        
        # Iniciar nuevo timer si es necesario
        if self.hold_mode == 'timed' and self.hold_seconds > 0:
            self.hold_timer.start(self.hold_seconds * 1000)
            self.logger.info(f"⏱️ Reinicio automático de max/min cada {self.hold_seconds} s")
        else:
            self.logger.info("⏱️ Reinicio manual de max/min")
        
        # Emitir cambio
        settings = self.get_settings()
        #settings['hold_mode'] = self.hold_mode
        #settings['hold_seconds'] = self.hold_seconds
        self.settings_changed.emit(settings)
    
    def on_hold_timeout(self):
        """Timer de reinicio de curvas max/min"""
        self.logger.info("⏱️ Reiniciando curvas max/min por tiempo")
        settings = {
            'clear_persistence': False,  # Limpia waterfall
            'reset_max_min': True       # NUEVO: reinicia max/min
        }
        self.settings_changed.emit(settings)
    
    def get_settings(self):
        """Obtiene configuración actual"""
        current_data = self.comboBox_color_map.currentData()
        colormap_key = current_data if current_data is not None else 'viridis'
        
        settings = {
            'color_map': colormap_key,
            'persistence': self.horizontalSlider_persistence.value(),
            'plot_max': self.checkBox_plot_max.isChecked(),
            'plot_min': self.checkBox_plot_min.isChecked(),
            'hold_mode': self.hold_mode,
            'hold_seconds': self.hold_seconds
        }
        
        if hasattr(self, 'min_spin'):
            settings['min_threshold'] = self.min_spin.value()
            settings['max_threshold'] = self.max_spin.value()
        
        return settings
    
    '''def auto_range(self):
        """Autoajusta rango de colores"""
        if hasattr(self, 'colorbar'):
            self.colorbar.autoHistogramRange()
            levels = self.colorbar.getLevels()
            if levels and len(levels) >= 2:
                self.min_spin.setValue(int(levels[0]))
                self.max_spin.setValue(int(levels[1]))
        
        settings = self.get_settings()
        settings['auto_range'] = True
        self.settings_changed.emit(settings)'''

    # widgets/visualization.py

    def auto_range(self):
        """
        Autoajusta el rango dinámico basado en el espectro actual.
        Encuentra el pico máximo y el piso de ruido, establece márgenes inteligentes.
        """
        try:
            # Obtener el espectro actual
            spectrum = self.get_current_spectrum()
            
            if spectrum is None or len(spectrum) == 0:
                self.logger.warning("⚠️ No hay datos de espectro disponibles para auto-rango")
                # Fallback: usar el colorbar existente
                if hasattr(self, 'colorbar'):
                    self.colorbar.autoHistogramRange()
                    levels = self.colorbar.getLevels()
                    if levels and len(levels) >= 2:
                        self.min_spin.setValue(int(levels[0]))
                        self.max_spin.setValue(int(levels[1]))
                return
            
            # ===== ANÁLISIS DEL ESPECTRO =====
            # Encontrar pico máximo (ignorando valores atípicos)
            spectrum_clean = spectrum[~np.isinf(spectrum)]
            spectrum_clean = spectrum_clean[~np.isnan(spectrum_clean)]
            
            if len(spectrum_clean) == 0:
                return
            
            # Percentiles para evitar outliers
            max_peak = np.percentile(spectrum_clean, 99.5)  # Pico máximo real
            noise_floor = np.percentile(spectrum_clean, 5)   # Piso de ruido (5% más bajo)
            
            # ===== CÁLCULO DE NUEVOS LÍMITES =====
            # Margen superior: pico + 5 dB (para ver clipping)
            new_max = max_peak + 5.0
            
            # Margen inferior: entre piso de ruido y -10 dB por debajo
            # Para que el ruido sea visible pero no domine
            new_min = min(noise_floor - 5.0, max_peak - 50.0)
            
            # Limitar rangos razonables
            new_min = max(-140.0, min(new_min, -50.0))  # Entre -140 y -50 dB
            new_max = min(20.0, max(new_max, -30.0))    # Entre -30 y 20 dB
            
            # Asegurar rango mínimo de 30 dB para visibilidad
            if new_max - new_min < 30:
                new_min = new_max - 30
            
            self.logger.info(
                f"📊 Auto-rango: pico={max_peak:.1f} dB, ruido={noise_floor:.1f} dB → "
                f"rango=[{new_min:.0f}, {new_max:.0f}] dB"
            )
            
            # ===== APLICAR NUEVOS LÍMITES =====
            self.min_spin.blockSignals(True)
            self.max_spin.blockSignals(True)
            
            self.min_threshold = new_min
            self.max_threshold = new_max
            
            self.min_spin.setValue(int(new_min))
            self.max_spin.setValue(int(new_max))
            
            self.min_spin.blockSignals(False)
            self.max_spin.blockSignals(False)
            
            # Actualizar colorbar
            if hasattr(self, 'colorbar'):
                self.colorbar.setLevels(new_min, new_max)
                self.colorbar.setHistogramRange(new_min, new_max)
            
            # Actualizar waterfall
            if self.waterfall:
                self.waterfall.set_display_range(new_min, new_max)
            
            # Actualizar colores de curvas basados en nuevo rango
            active_color, max_color, min_color = self.get_colors_from_levels(
                new_min, new_max
            )
            
            settings = self.get_settings()
            settings['curve_colors'] = {
                'active': active_color,
                'max': max_color,
                'min': min_color
            }
            settings['min_threshold'] = new_min
            settings['max_threshold'] = new_max
            settings['auto_range'] = True
            
            self.settings_changed.emit(settings)
            
            # Mensaje en barra de estado si está disponible
            if hasattr(self, 'main_controller') and self.main_controller:
                self.main_controller.statusbar.showMessage(
                    f"📊 Auto-rango: {new_min:.0f} dB a {new_max:.0f} dB (pico: {max_peak:.1f} dB)",
                    3000
                )
            
        except Exception as e:
            self.logger.error(f"Error en auto_range: {e}")
            import traceback
            traceback.print_exc()
    
    def clear_persistence(self):
        """Limpia la persistencia del waterfall"""
        settings = self.get_settings()
        settings['clear_persistence'] = True
        settings['reset_max_min'] = True
        self.settings_changed.emit(settings)

    def on_clear_persistence_clicked(self):
        """Botón LIMPIAR - limpia waterfall Y curvas"""
        self.logger.info("🗑️ Limpiando waterfall y curvas")
        settings = {
            'clear_persistence': True,   # Limpia waterfall
            'reset_max_min': True        # También reinicia curvas
        }
        self.settings_changed.emit(settings)
    
    def test_colors(self):
        """Prueba colores brillantes"""
        self.logger.info("🎨 Botón de prueba presionado")
        settings = {
            'curve_colors': {
                'active': '#FF00FF',  # Magenta
                'max': '#00FF00',      # Verde
                'min': '#FF0000'       # Rojo
            }
        }
        self.settings_changed.emit(settings)
    
    # -----------------------------------------------------------------------
    # MÉTODOS DE EXTRACCIÓN DE COLORES
    # -----------------------------------------------------------------------
    def get_colors_from_levels(self, min_level, max_level):
        """
        Obtiene los colores del colorbar correspondientes a los niveles.
        """
        try:
            if not hasattr(self, 'colorbar') or not self.colorbar:
                return '#00ff00', '#ff0000', '#0000ff'
            
            # Obtener lookup table del gradient
            gradient = self.colorbar.item.gradient
            lookup_table = gradient.getLookupTable(512)
            
            if lookup_table is None or len(lookup_table) == 0:
                return '#00ff00', '#ff0000', '#0000ff'
            
            # Calcular índices
            total_range = max_level - min_level
            if total_range <= 0:
                total_range = 120
            
            offset = -min_level
            
            def level_to_index(level):
                norm = (level + offset) / total_range
                norm = max(0, min(1, norm))
                return int(norm * (len(lookup_table) - 1))
            
            min_idx = level_to_index(min_level)
            max_idx = level_to_index(max_level)
            mid_idx = level_to_index((min_level + max_level) / 2)
            
            # Convertir a hex
            def rgb_to_hex(rgb):
                return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            
            min_hex = rgb_to_hex(lookup_table[min_idx])
            max_hex = rgb_to_hex(lookup_table[max_idx])
            mid_hex = rgb_to_hex(lookup_table[mid_idx])
            
            # Aclarar si es muy oscuro
            r, g, b = lookup_table[min_idx]
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            if luminance < 0.2:
                r = min(255, int(r * 2.0))
                g = min(255, int(g * 2.0))
                b = min(255, int(b * 2.0))
                min_hex = f"#{r:02x}{g:02x}{b:02x}"
            
            return mid_hex, max_hex, min_hex
            
        except Exception as e:
            self.logger.error(f"Error en get_colors_from_levels: {e}")
            return '#00ff00', '#ff0000', '#0000ff'
    
    # -----------------------------------------------------------------------
    # SLOTS DE SEÑALES
    # -----------------------------------------------------------------------
    def on_threshold_changed(self):
        """Maneja cambio de umbrales desde spinboxes"""
        self.min_threshold = self.min_spin.value()
        self.max_threshold = self.max_spin.value()
        
        # Actualizar colorbar
        if hasattr(self, 'colorbar'):
            self.colorbar.setLevels(self.min_threshold, self.max_threshold)
            self.colorbar.setHistogramRange(self.min_threshold, self.max_threshold)
        
        # Actualizar waterfall
        if self.waterfall:
            self.waterfall.set_display_range(self.min_threshold, self.max_threshold)
        
        # Actualizar colores de curvas
        try:
            active_color, max_color, min_color = self.get_colors_from_levels(
                self.min_threshold, self.max_threshold
            )
            
            settings = self.get_settings()
            settings['curve_colors'] = {
                'active': active_color,
                'max': max_color,
                'min': min_color
            }
            self.settings_changed.emit(settings)
            
        except Exception as e:
            self.logger.error(f"Error actualizando colores: {e}")
    
    def on_colormap_changed(self):
        """Maneja cambio de colormap"""
        # Obtener el colormap seleccionado
        cmap_key = self.comboBox_color_map.currentData()
        if cmap_key is None:
            return
        
        self.current_colormap = cmap_key
        cmap_info = COLORMAPS_VALIDOS.get(cmap_key, {'name': cmap_key, 'type': 'unknown'})
        
        self.logger.info(f"🎨 Cambiando a colormap: {cmap_info['name']} ({cmap_key})")
        
        # 1. Actualizar colorbar
        self._apply_colormap_to_colorbar(cmap_key)
        
        # 2. Actualizar waterfall
        self._apply_colormap_to_waterfall(cmap_key)
        
        # 3. Actualizar colores del espectro basados en niveles actuales
        if hasattr(self, 'min_spin') and hasattr(self, 'max_spin'):
            active_color, max_color, min_color = self.get_colors_from_levels(
                self.min_spin.value(), self.max_spin.value()
            )
            
            settings = self.get_settings()
            settings['curve_colors'] = {
                'active': active_color,
                'max': max_color,
                'min': min_color
            }
            self.settings_changed.emit(settings)
        
        self.logger.info(f"✅ Colormap aplicado consistentemente a todos los componentes")
    
    def on_setting_changed(self):
        """Se llama cuando cambia algún parámetro"""
        settings = self.get_settings()
        self.settings_changed.emit(settings)

    def on_show_bands_changed(self, state):
        """Manejador para mostrar/ocultar el Band Plan"""
        show_bands = state == Qt.Checked
        self.logger.info(f"📡 Band Plan: {'mostrar' if show_bands else 'ocultar'} - Usando bands.json")
        
        # Emitir señal con la configuración
        settings = self.get_settings()
        settings['show_band_plan'] = show_bands
        self.settings_changed.emit(settings)
    
    def _on_colorbar_levels_changed(self):
        """Manejador cuando cambian los niveles en el colorbar"""
        levels = self.colorbar.getLevels()
        if levels and len(levels) >= 2:
            min_level, max_level = levels[0], levels[1]
            
            # Actualizar spinboxes
            self.min_spin.blockSignals(True)
            self.max_spin.blockSignals(True)
            self.min_spin.setValue(int(min_level))
            self.max_spin.setValue(int(max_level))
            self.min_spin.blockSignals(False)
            self.max_spin.blockSignals(False)
            
            # Obtener colores y emitir
            active_color, max_color, min_color = self.get_colors_from_levels(
                min_level, max_level
            )
            
            settings = self.get_settings()
            settings['curve_colors'] = {
                'active': active_color,
                'max': max_color,
                'min': min_color
            }
            settings['min_threshold'] = min_level
            settings['max_threshold'] = max_level
            
            self.settings_changed.emit(settings)
    
    def _on_colorbar_colormap_changed(self):
        """Manejador cuando cambia el mapa de colores manualmente"""
        self.logger.debug("🎨 Colormap cambiado manualmente en colorbar")
    
    def _on_waterfall_updated(self):
        """Respuesta a actualización del waterfall"""
        if hasattr(self, 'colorbar'):
            self.colorbar.autoHistogramRange()

    # widgets/visualization.py

    def set_main_controller(self, controller):
        """Guarda referencia al controlador principal para acceder al espectro"""
        self.main_controller = controller
        self.logger.info("🔗 VisualizationWidget conectado al MainController")
    
    def get_current_spectrum(self):
        """Obtiene el espectro actual del controlador"""
        if self.main_controller and hasattr(self.main_controller, 'fft_ctrl'):
            # Acceder al último espectro procesado
            if hasattr(self.main_controller.fft_ctrl, '_prev_spectrum'):
                return self.main_controller.fft_ctrl._prev_spectrum
        return None

# widgets/spectrum_plot.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import pyqtgraph as pg
import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QColor


# =======================================================================
# MARCADOR DE FRECUENCIA INTERACTIVO
# =======================================================================
class FrequencyMarker(QObject):
    """Marcador interactivo para el espectro"""
    
    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    frequencyChanged = pyqtSignal(float)
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, frequency, logger=None):
        super().__init__()
        self.frequency = frequency
        self.logger = logger
        
        # Elementos gráficos
        self.line = None
        self.power_label = None
        self.marker_point = None
        self.ghost_line = None
        
        # Estado de interacción
        self.dragging = False
        self.drag_start_pos = None
        
        # Colores
        self.normal_color = '#FF0000'
        self.hover_color = '#FFA500'
        self.drag_color = '#FFFF00'
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS
    # -----------------------------------------------------------------------
    def add_to_plot(self, plot):
        """Agregar línea de marcador con punto interactivo"""
        # Línea principal
        self.line = pg.InfiniteLine(
            pos=self.frequency, 
            angle=90, 
            movable=True,
            pen=pg.mkPen(self.normal_color, width=2),
            hoverPen=pg.mkPen(self.hover_color, width=3),
            bounds=None
        )
        
        # Línea fantasma (inicialmente invisible)
        self.ghost_line = pg.InfiniteLine(
            pos=self.frequency, 
            angle=90, 
            movable=False,
            pen=pg.mkPen('#888888', width=1, style=Qt.DashLine),
            hoverPen=None
        )
        self.ghost_line.setVisible(False)
        
        # Punto interactivo
        self.marker_point = pg.ScatterPlotItem(
            pos=[(self.frequency, -5)],
            size=8,
            pen=pg.mkPen(self.normal_color, width=1),
            brush=pg.mkBrush(self.normal_color),
            hoverable=True,
            hoverPen=pg.mkPen(self.hover_color, width=2),
            hoverBrush=pg.mkBrush(self.hover_color),
            hoverSize=12
        )
        
        # Etiqueta de potencia
        self.power_label = pg.TextItem(
            text="", 
            color=(255, 255, 255), 
            anchor=(0.5, 1),
            border=pg.mkPen(0, 0, 0, 200),
            fill=pg.mkBrush(0, 0, 0, 180),
            html=None
        )
        
        # Agregar elementos
        plot.addItem(self.line)
        plot.addItem(self.ghost_line)
        plot.addItem(self.marker_point)
        plot.addItem(self.power_label)
        
        self._update_label_position()
    
    def set_frequency(self, frequency):
        """Actualizar posición de la frecuencia"""
        self.frequency = frequency
        if self.line and not self.dragging:
            self.line.setValue(frequency)
            self._update_marker_position()
            self._update_label_position()
    
    def set_power(self, power_dbm):
        """Actualizar la potencia mostrada en la etiqueta"""
        if self.power_label and power_dbm is not None:
            if power_dbm > -50:
                color = "#00FF00"
            elif power_dbm > -80:
                color = "#FFFF00"
            else:
                color = "#FF0000"
            
            self.power_label.setHtml(
                f'<span style="color: {color}; font-weight: bold;">'
                f'{power_dbm:.1f} dBm</span>'
            )
        elif self.power_label:
            self.power_label.setText("")
    
    def connect_signal(self, callback):
        """Conectar señal de cambio de posición"""
        if self.line:
            self.line.sigDragged.connect(self._on_drag_move)
            self.line.sigPositionChangeFinished.connect(
                lambda: self._on_drag_finished(callback)
            )
    
    def connect_point_click(self, callback):
        """Conectar clicks en el punto marcador"""
        if self.marker_point:
            self.marker_point.sigClicked.connect(callback)
    
    # -----------------------------------------------------------------------
    # MÉTODOS PRIVADOS
    # -----------------------------------------------------------------------
    def _update_marker_position(self):
        """Actualizar posición del punto marcador"""
        if self.marker_point:
            self.marker_point.setData(pos=[(self.frequency, -5)])
    
    def _update_label_position(self):
        """Actualizar posición de la etiqueta"""
        if self.power_label and self.line:
            self.power_label.setPos(self.frequency, -15)
    
    def _on_drag_move(self, line):
        """Durante el arrastre"""
        if not self.dragging:
            self.dragging = True
            self.drag_start_pos = line.value()
            
            if self.ghost_line:
                self.ghost_line.setValue(line.value())
                self.ghost_line.setVisible(True)
            
            if self.line:
                self.line.setPen(
                    pg.mkPen(self.drag_color, width=2, style=Qt.DashLine)
                )
        else:
            if self.ghost_line:
                self.ghost_line.setValue(line.value())
    
    def _on_drag_finished(self, callback):
        """Finalizar arrastre"""
        if not self.dragging:
            return
            
        self.dragging = False
        new_freq = self.line.value()
        
        if self.ghost_line:
            self.ghost_line.setVisible(False)
        
        if self.line:
            self.line.setPen(pg.mkPen(self.normal_color, width=2))
        
        self.frequency = new_freq
        self._update_marker_position()
        self._update_label_position()
        
        callback(new_freq)
        
        if self.logger:
            self.logger.info(f"🎯 Frecuencia cambiada a: {new_freq:.3f} MHz")
        
        self.drag_start_pos = None


# =======================================================================
# WIDGET DE ESPECTRO CON FONDO DINÁMICO
# =======================================================================
class SpectrumPlot(QObject):
    """Widget de espectro con curvas de hold y fondo adaptativo"""
    
    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    frequencyChanged = pyqtSignal(float)
    
    # -----------------------------------------------------------------------
    # CONSTANTES
    # -----------------------------------------------------------------------
    # Colores de fondo predefinidos
    BACKGROUND_DARK = QColor(25, 25, 25)      # Fondo oscuro original
    BACKGROUND_LIGHT = QColor(240, 240, 240)  # Fondo claro alternativo
    BACKGROUND_MEDIUM = QColor(53, 53, 53)    # Fondo medio (gris)
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, main_window, logger):
        super().__init__()
        self.main_window = main_window
        self.logger = logger
        
        # Elementos del plot
        self.plot_widget = None
        self.curve = None
        self.max_curve = None
        self.min_curve = None
        self.freq_marker = None
        self.info_text = None
        self.grid = None
        self.viewbox = None
        
        # Datos actuales
        self.current_spectrum = None
        self.current_frequencies = None
        
        # Estado
        self.updating_from_marker = False
        self.max_hold_enabled = False
        self.min_hold_enabled = False
        self.max_hold_data = None
        self.min_hold_data = None

        # ===== NUEVO: Líneas para detector =====
        self.threshold_line = None
        self.noise_line = None
        self.threshold_visible = True
        self.noise_visible = True
        
        # Color actual de fondo
        self.current_bg_color = self.BACKGROUND_DARK

        from utils.band_plan import BandPlan
        self.band_plan = BandPlan()
        self.show_band_plan = False
        self.band_regions = []  # Almacenar las regiones dibujadas
        
        self.logger.info(f"✅ BandPlan inicializado con {len(self.band_plan.get_all_bands())} bandas")
        
        # Configurar plot
        self.setup_plot()

        # ===== Crear líneas UNA SOLA VEZ =====
        self.setup_detector_lines()  # <-- SOLO AQUÍ
        
        self.logger.info("✅ SpectrumPlot inicializado")
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN
    # -----------------------------------------------------------------------
    def setup_plot(self):
        """Configurar el gráfico de espectro con marcador"""
        self.plot_widget = pg.PlotWidget(labels={
            'left': 'PSD [dB]', 
            'bottom': 'Frequency [MHz]'
        })
        
        # Configurar interacciones
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.hideButtons()
        
        # Configurar rango fijo en Y
        self.plot_widget.setYRange(-120, 20)
        
        # Configurar grid
        self.grid = self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Guardar referencia al ViewBox para cambiar fondo
        self.viewbox = self.plot_widget.getViewBox()
        
        # Curva principal
        self.curve = self.plot_widget.plot(
            [], 
            pen=pg.mkPen(color=(0, 255, 255), width=1)
        )
        
        # Curva de máximo
        self.max_curve = self.plot_widget.plot(
            [], 
            pen=pg.mkPen(color=(0, 255, 0), width=2, style=Qt.SolidLine),
            name="Max Hold"
        )
        self.max_curve.setVisible(False)
        
        # Curva de mínimo
        self.min_curve = self.plot_widget.plot(
            [], 
            pen=pg.mkPen(color=(0, 0, 255), width=2, style=Qt.SolidLine),
            name="Min Hold"
        )
        self.min_curve.setVisible(False)
        
        # Texto de información - CREADO CORRECTAMENTE con fill y border
        self.info_text = pg.TextItem(
            text="", 
            color=(255, 255, 255),
            anchor=(0, 0),
            border=pg.mkPen(0, 0, 0, 150),
            fill=pg.mkBrush(0, 0, 0, 180)
        )
        
        self.plot_widget.addItem(self.info_text)
        self.info_text.setPos(10, 10)
        
        # Obtener frecuencia inicial
        initial_freq = self._get_initial_frequency()
        self.logger.info(f"📊 Inicializando marcador en: {initial_freq:.3f} MHz")
        
        # Configurar marcador
        self.freq_marker = FrequencyMarker(initial_freq, self.logger)
        self.freq_marker.add_to_plot(self.plot_widget)
        
        # Conectar señales del marcador
        self.freq_marker.connect_signal(self._on_marker_released)
        self.freq_marker.connect_point_click(self._on_point_clicked)
        
        # Conectar eventos del mouse
        self.plot_widget.scene().sigMouseClicked.connect(self._on_spectrum_click)
        
        # Establecer fondo inicial
        self.set_background_color(self.BACKGROUND_DARK)

         # ===== NUEVO: Conectar señal de cambio de rango =====
        self.plot_widget.sigRangeChanged.connect(self._on_range_changed)

        #self._setup_detector_lines()
    
    # -----------------------------------------------------------------------
    # MÉTODOS DE FONDO DINÁMICO - VERSIÓN CORREGIDA (SIN SETFILL)
    # -----------------------------------------------------------------------
    def set_background_color(self, color):
        """
        Establece el color de fondo del gráfico.
        
        Args:
            color: QColor o string hex (#RRGGBB)
        """
        if isinstance(color, str):
            color = QColor(color)
        
        self.current_bg_color = color
        
        # Cambiar fondo del ViewBox
        self.viewbox.setBackgroundColor(color)
        
        # En lugar de modificar el info_text, lo recreamos con nuevos colores
        self._recreate_info_text(color)
        
        # Ajustar color de la cuadrícula según el fondo
        self._adjust_grid_color(color)
        
        self.logger.debug(f"🎨 Fondo cambiado a: {color.name()}")
    
    def _recreate_info_text(self, bg_color):
        """Recrea el texto de información con colores apropiados para el fondo."""
        # Calcular luminancia del fondo
        luminance = (0.299 * bg_color.red() + 
                     0.587 * bg_color.green() + 
                     0.114 * bg_color.blue()) / 255
        
        # Guardar posición actual
        current_pos = self.info_text.pos() if self.info_text else (10, 10)
        current_text = self.info_text.toPlainText() if self.info_text else ""
        
        # Eliminar el texto antiguo
        if self.info_text in self.plot_widget.items():
            self.plot_widget.removeItem(self.info_text)
        
        # Crear nuevo texto con colores apropiados
        if luminance > 0.5:  # Fondo claro
            # Texto oscuro con fondo claro semi-transparente
            self.info_text = pg.TextItem(
                text=current_text,
                color=(0, 0, 0),
                anchor=(0, 0),
                border=pg.mkPen(0, 0, 0, 150),
                fill=pg.mkBrush(255, 255, 255, 200)
            )
        else:  # Fondo oscuro
            # Texto claro con fondo oscuro semi-transparente
            self.info_text = pg.TextItem(
                text=current_text,
                color=(255, 255, 255),
                anchor=(0, 0),
                border=pg.mkPen(255, 255, 255, 150),
                fill=pg.mkBrush(0, 0, 0, 200)
            )
        
        # Añadir al plot y restaurar posición
        self.plot_widget.addItem(self.info_text)
        self.info_text.setPos(current_pos)
    
    def _adjust_grid_color(self, bg_color):
        """Ajusta el color de la cuadrícula según el fondo."""
        # Calcular luminancia
        luminance = (0.299 * bg_color.red() + 
                     0.587 * bg_color.green() + 
                     0.114 * bg_color.blue()) / 255
        
        # Grid más claro para fondos oscuros, más oscuro para fondos claros
        if luminance > 0.5:  # Fondo claro
            grid_alpha = 100  # Grid más visible
        else:  # Fondo oscuro
            grid_alpha = 70   # Grid más sutil
        
        # Reconfigurar grid
        self.plot_widget.showGrid(x=True, y=True, alpha=grid_alpha/255)
    
    def get_optimal_background(self, colors):
        """
        Determina el color de fondo óptimo basado en los colores de las curvas.
        
        Args:
            colors: Diccionario con colores 'active', 'max', 'min'
        
        Returns:
            QColor: Color de fondo recomendado
        """
        if not colors:
            return self.BACKGROUND_DARK
        
        # Recolectar todos los colores
        all_colors = []
        for color_name in ['active', 'max', 'min']:
            if color_name in colors and colors[color_name]:
                color_str = colors[color_name]
                if color_str.startswith('#'):
                    # Convertir hex a QColor
                    r = int(color_str[1:3], 16)
                    g = int(color_str[3:5], 16)
                    b = int(color_str[5:7], 16)
                    all_colors.append(QColor(r, g, b))
        
        if not all_colors:
            return self.BACKGROUND_DARK
        
        # Calcular luminancia promedio de las curvas
        total_luminance = 0
        for color in all_colors:
            luminance = (0.299 * color.red() + 
                         0.587 * color.green() + 
                         0.114 * color.blue()) / 255
            total_luminance += luminance
        
        avg_luminance = total_luminance / len(all_colors)
        
        # Log para depuración
        self.logger.debug(f"📊 Luminancia promedio de curvas: {avg_luminance:.2f}")
        
        # Decidir fondo basado en luminancia promedio
        if avg_luminance < 0.25:
            # Curvas muy oscuras, necesitan fondo claro
            self.logger.debug("   → Seleccionando fondo CLARO")
            return self.BACKGROUND_LIGHT
        elif avg_luminance > 0.75:
            # Curvas muy claras, pueden ir sobre fondo oscuro
            self.logger.debug("   → Seleccionando fondo OSCURO")
            return self.BACKGROUND_DARK
        else:
            # Luminancia media, usar fondo medio
            self.logger.debug("   → Seleccionando fondo MEDIO")
            return self.BACKGROUND_MEDIUM
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS
    # -----------------------------------------------------------------------
    # widgets/spectrum_plot.py - Modificar set_curve_colors

    def set_curve_colors(self, active_color=None, max_color=None, min_color=None):
        """Cambia los colores de las curvas y asegura visibilidad sobre fondo negro"""
        self.logger.info("=" * 70)
        self.logger.info("🎨 SET_CURVE_COLORS() INICIADO")
        self.logger.info(
            f"   Colores originales: active={active_color}, max={max_color}, min={min_color}"
        )
        
        # Fondo negro fijo
        bg_color = QColor(25, 25, 25)
        
        # Ajustar colores para visibilidad
        if active_color:
            active_color = self._get_contrasting_color(active_color, bg_color)
        if max_color:
            max_color = self._get_contrasting_color(max_color, bg_color)
        if min_color:
            min_color = self._get_contrasting_color(min_color, bg_color)
        
        # Valores por defecto si no se proporcionan
        active_to_use = active_color if active_color else '#00FFFF'
        max_to_use = max_color if max_color else '#FFFF00'
        min_to_use = min_color if min_color else '#FF8000'
        
        self.logger.info(f"   Colores ajustados: active={active_to_use}, max={max_to_use}, min={min_to_use}")
        
        # Aplicar colores a las curvas
        try:
            if self.curve:
                pen = pg.mkPen(color=active_to_use, width=1)
                self.curve.setPen(pen)
                self.logger.info(f"   Curva activa → {active_to_use}")
            
            if self.max_curve:
                pen = pg.mkPen(color=max_to_use, width=1)
                self.max_curve.setPen(pen)
                self.max_curve.setVisible(self.max_hold_enabled)
                self.logger.info(f"   Curva max → {max_to_use}")
            
            if self.min_curve:
                pen = pg.mkPen(color=min_to_use, width=1)
                self.min_curve.setPen(pen)
                self.min_curve.setVisible(self.min_hold_enabled)
                self.logger.info(f"   Curva min → {min_to_use}")
            
            # Fijar fondo negro
            self.viewbox.setBackgroundColor(bg_color)
            
        except Exception as e:
            self.logger.error(f"❌ Error aplicando colores: {e}")
            import traceback
            traceback.print_exc()
        
        # Forzar actualización
        if self.plot_widget:
            self.plot_widget.repaint()
            self.plot_widget.update()
        
        self.logger.info("=" * 70)

    def _adjust_plot_background(self, colors):
        """
        Ajusta el fondo del gráfico según los colores de las curvas.
        Esto NO afecta al tema de la UI, solo al área del plot.
        """
        if not colors:
            return
        
        # Recolectar colores de las curvas
        all_colors = []
        for color_name in ['active', 'max', 'min']:
            if color_name in colors and colors[color_name]:
                color_str = colors[color_name]
                if color_str.startswith('#'):
                    r = int(color_str[1:3], 16)
                    g = int(color_str[3:5], 16)
                    b = int(color_str[5:7], 16)
                    all_colors.append(QColor(r, g, b))
        
        if not all_colors:
            return
        
        # Calcular luminancia promedio
        total_luminance = 0
        for color in all_colors:
            luminance = (0.299 * color.red() + 
                        0.587 * color.green() + 
                        0.114 * color.blue()) / 255
            total_luminance += luminance
        
        avg_luminance = total_luminance / len(all_colors)
        
        # Elegir color de fondo basado en luminancia
        if avg_luminance < 0.3:
            # Curvas oscuras → fondo claro
            bg_color = QColor(240, 240, 240)
            grid_color = Qt.black
            grid_alpha = 100
        elif avg_luminance > 0.7:
            # Curvas claras → fondo oscuro
            bg_color = QColor(30, 30, 30)
            grid_color = Qt.white
            grid_alpha = 70
        else:
            # Luminancia media → fondo gris medio
            bg_color = QColor(60, 60, 60)
            grid_color = Qt.white
            grid_alpha = 50
        
        # Aplicar fondo al ViewBox (solo el área del gráfico)
        self.viewbox.setBackgroundColor(bg_color)
        
        # Ajustar grid
        self.plot_widget.showGrid(x=True, y=True, alpha=grid_alpha/255)
        
        self.logger.debug(f"📊 Fondo del gráfico ajustado a: {bg_color.name()}")
    
    def _get_initial_frequency(self):
        """Obtiene frecuencia inicial de forma segura"""
        if hasattr(self.main_window, 'doubleSpinBox_freq'):
            return self.main_window.doubleSpinBox_freq.value()
        elif hasattr(self.main_window, 'frequency_spinner'):
            return self.main_window.frequency_spinner.frequency_mhz
        return 100.0
    
    def update_plot(self, spectrum, frequencies, max_hold=None, min_hold=None):
        """Actualizar el gráfico con nuevos datos"""
        try:
            if spectrum is not None and frequencies is not None:
                self.current_spectrum = spectrum
                self.current_frequencies = frequencies
                
                # Actualizar curva principal
                self.curve.setData(frequencies, spectrum)
                
                # Actualizar curvas de hold
                if self.max_hold_enabled and max_hold is not None:
                    self.max_curve.setData(frequencies, max_hold)
                
                if self.min_hold_enabled and min_hold is not None:
                    self.min_curve.setData(frequencies, min_hold)
                
                # Actualizar marcador
                if not self.freq_marker.dragging:
                    center_freq = self._get_initial_frequency()
                    self.freq_marker.set_frequency(center_freq)
                    power = self._get_power_at_frequency(center_freq)
                    self.freq_marker.set_power(power)
                
        except Exception as e:
            self.logger.error(f"Error actualizando spectrum plot: {e}")
    
    def enable_max_hold(self, enabled):
        """Habilitar/deshabilitar hold máximo"""
        self.max_hold_enabled = enabled
        self.max_curve.setVisible(enabled)
        if not enabled:
            self.max_hold_data = None
    
    def enable_min_hold(self, enabled):
        """Habilitar/deshabilitar hold mínimo"""
        self.min_hold_enabled = enabled
        self.min_curve.setVisible(enabled)
        if not enabled:
            self.min_hold_data = None
    
    def clear_hold(self):
        """Limpiar datos de hold"""
        self.max_hold_data = None
        self.min_hold_data = None
        self.max_curve.setData([], [])
        self.min_curve.setData([], [])
        self.logger.info("Hold limpiado")
    
    def set_frequency(self, freq_mhz):
        """Establecer frecuencia desde controles externos"""
        try:
            if not self.freq_marker.dragging and not self.updating_from_marker:
                self.freq_marker.set_frequency(freq_mhz)
                power = self._get_power_at_frequency(freq_mhz)
                self.freq_marker.set_power(power)
        except Exception as e:
            self.logger.error(f"Error estableciendo frecuencia: {e}")
    
    def update_info_text(self, text):
        """Actualizar el texto de información"""
        try:
            if self.info_text:
                self.info_text.setText(text)
        except Exception as e:
            self.logger.error(f"Error actualizando info text: {e}")
    
    def set_marker_color(self, color):
        """Cambia el color del marcador de frecuencia"""
        if self.freq_marker and self.freq_marker.line:
            self.freq_marker.line.setPen(pg.mkPen(color, width=2))
            if hasattr(self.freq_marker, 'marker_point'):
                self.freq_marker.marker_point.setPen(pg.mkPen(color, width=1))
                self.freq_marker.marker_point.setBrush(pg.mkBrush(color))
    
    # -----------------------------------------------------------------------
    # MÉTODOS PRIVADOS
    # -----------------------------------------------------------------------
    def _get_power_at_frequency(self, freq_mhz):
        """Obtener la potencia en una frecuencia específica"""
        try:
            if self.current_spectrum is None or self.current_frequencies is None:
                return None
            
            idx = np.argmin(np.abs(self.current_frequencies - freq_mhz))
            if idx < len(self.current_spectrum):
                return self.current_spectrum[idx]
            return None
        except Exception:
            return None
    
    def _on_marker_released(self, new_freq):
        """Manejador cuando el marcador es soltado"""
        try:
            if self.updating_from_marker:
                return
                
            self.updating_from_marker = True
            self.logger.info(f"🎯 Marcador movido a: {new_freq:.3f} MHz")
            
            self.frequencyChanged.emit(new_freq)
            
            power = self._get_power_at_frequency(new_freq)
            if self.freq_marker:
                self.freq_marker.set_power(power)
            
            self.updating_from_marker = False
            
        except Exception as e:
            self.updating_from_marker = False
            self.logger.error(f"Error en marcador: {e}")
    
    def _on_point_clicked(self, plot, points, event):
        """Manejador para doble-click en el punto marcador"""
        if event.double():
            point = points[0]
            new_freq = point.pos().x()
            self.logger.info(f"🎯 Centrando en {new_freq:.3f} MHz")
            self.frequencyChanged.emit(new_freq)
            power = self._get_power_at_frequency(new_freq)
            self.freq_marker.set_power(power)
            event.accept()
    
    def _on_spectrum_click(self, event):
        """Manejar doble-click en el espectro"""
        if event.double():
            pos = self.plot_widget.plotItem.vb.mapSceneToView(event.scenePos())
            freq_mhz = pos.x()
            self.logger.info(f"🎯 Centrando en {freq_mhz:.3f} MHz")
            self.frequencyChanged.emit(freq_mhz)
            power = self._get_power_at_frequency(freq_mhz)
            self.freq_marker.set_power(power)

    def _adjust_color_for_background(self, color_hex, bg_color=QColor(25, 25, 25)):
        """
        Ajusta un color si es demasiado similar al fondo.
        
        Args:
            color_hex: Color en formato hex (#RRGGBB)
            bg_color: Color de fondo (QColor)
        
        Returns:
            Color ajustado en formato hex
        """
        if not color_hex or not color_hex.startswith('#'):
            return color_hex
        
        # Convertir hex a QColor
        r = int(color_hex[1:3], 16)
        g = int(color_hex[3:5], 16)
        b = int(color_hex[5:7], 16)
        color = QColor(r, g, b)
        
        # Calcular diferencia con el fondo
        bg_luminance = (0.299 * bg_color.red() + 
                        0.587 * bg_color.green() + 
                        0.114 * bg_color.blue()) / 255
        
        color_luminance = (0.299 * color.red() + 
                           0.587 * color.green() + 
                           0.114 * color.blue()) / 255
        
        # Diferencia de luminancia
        diff = abs(color_luminance - bg_luminance)
        
        self.logger.debug(f"   📊 Luminancia: fondo={bg_luminance:.2f}, color={color_luminance:.2f}, diff={diff:.2f}")
        
        # Si la diferencia es muy pequeña, el color no se verá
        if diff < 0.15:  # Umbral de visibilidad
            self.logger.debug(f"   ⚠️ Color {color_hex} demasiado oscuro, ajustando...")
            
            # Si el color es muy oscuro, aclararlo
            if color_luminance < 0.3:
                # Aclarar manteniendo el tono
                factor = 2.0
                r = min(255, int(r * factor))
                g = min(255, int(g * factor))
                b = min(255, int(b * factor))
                adjusted = QColor(r, g, b)
                self.logger.debug(f"      → Aclarado a: {adjusted.name()}")
                return adjusted.name()
            
            # Si el color es muy claro sobre fondo oscuro (raro)
            elif color_luminance > 0.7:
                # Oscurecer ligeramente
                factor = 0.7
                r = int(r * factor)
                g = int(g * factor)
                b = int(b * factor)
                adjusted = QColor(r, g, b)
                self.logger.debug(f"      → Oscurecido a: {adjusted.name()}")
                return adjusted.name()
        
        return color_hex
    
    def _is_color_too_dark(self, color_hex, threshold=0.15):
        """Verifica si un color es demasiado oscuro para verse sobre fondo negro."""
        if not color_hex or not color_hex.startswith('#'):
            return False
        
        r = int(color_hex[1:3], 16)
        g = int(color_hex[3:5], 16)
        b = int(color_hex[5:7], 16)
        
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        
        return luminance < threshold
    
    def _get_contrasting_color(self, color_hex, bg_color=QColor(25, 25, 25)):
        """
        Obtiene un color que contraste con el fondo.
        Para colores muy oscuros, devuelve una versión aclarada.
        Para colores específicos como negro puro, devuelve blanco.
        """
        if not color_hex or not color_hex.startswith('#'):
            return color_hex
        
        # Casos especiales
        if color_hex.lower() == '#000000':  # Negro puro
            self.logger.debug("   ⚠️ Negro puro detectado, cambiando a blanco")
            return '#FFFFFF'
        
        if color_hex.lower() == '#0d0887':  # Azul muy oscuro de viridis
            self.logger.debug("   ⚠️ Azul muy oscuro detectado, aclarando")
            return '#6040C0'  # Azul más claro
        
        # Verificar si es demasiado oscuro
        if self._is_color_too_dark(color_hex):
            r = int(color_hex[1:3], 16)
            g = int(color_hex[3:5], 16)
            b = int(color_hex[5:7], 16)
            
            # Aclarar significativamente
            r = min(255, int(r * 2.5))
            g = min(255, int(g * 2.5))
            b = min(255, int(b * 2.5))
            
            adjusted = QColor(r, g, b)
            self.logger.debug(f"   ⚠️ Color muy oscuro {color_hex} → aclarado a {adjusted.name()}")
            return adjusted.name()
        
        return color_hex
    
    def setup_detector_lines(self):
        """Crea las líneas de umbral y ruido (separado para claridad)"""
        try:
            # Línea de umbral (roja punteada)
            self.threshold_line = pg.InfiniteLine(
                angle=0,
                pen=pg.mkPen('#FF4444', width=1, style=Qt.DashLine),
                movable=False,
                label="Umbral",
                labelOpts={'color': '#FF4444', 'position': 0.05}
            )
            self.plot_widget.addItem(self.threshold_line)
            #self.threshold_line.setVisible(self.threshold_visible)
            self.threshold_line.setVisible(True)
            self.threshold_line.setValue(-80)  # Valor inicial
            
            # Línea de ruido (gris punteada)
            self.noise_line = pg.InfiniteLine(
                angle=0,
                pen=pg.mkPen('#888888', width=1, style=Qt.DotLine),
                movable=False,
                label="Piso ruido",
                labelOpts={'color': '#888888', 'position': 0.1}
            )
            self.plot_widget.addItem(self.noise_line)
            self.noise_line.setVisible(True)
            self.noise_line.setValue(-95)  # Valor inicial
            
            self.logger.info("📊 Líneas de detector creadas")
            
        except Exception as e:
            self.logger.error(f"Error creando líneas de detector: {e}")
    
    def set_threshold_visible(self, visible):
        """Muestra/oculta línea de umbral"""
        self.threshold_visible = visible
        if self.threshold_line:
            self.threshold_line.setVisible(visible)
    
    def set_noise_visible(self, visible):
        """Muestra/oculta línea de ruido"""
        self.noise_visible = visible
        if self.noise_line:
            self.noise_line.setVisible(visible)
    
    def update_threshold(self, threshold_db):
        """Actualiza valor de la línea de umbral"""
        if self.threshold_line:
            self.threshold_line.setValue(threshold_db)
            self.threshold_line.label.setText(f"Umbral: {threshold_db:.1f} dB")
    
    def update_noise(self, noise_db):
        """Actualiza valor de la línea de ruido"""
        if self.noise_line:
            self.noise_line.setValue(noise_db)
            self.noise_line.label.setText(f"Ruido: {noise_db:.1f} dB")


    def set_band_plan_visible(self, visible: bool):
        """Muestra u oculta las bandas de frecuencia"""
        self.show_band_plan = visible
        
        if visible:
            self._draw_band_regions()
        else:
            self._clear_band_regions()
    

    # widgets/spectrum_plot.py

    def _draw_band_regions(self):
        """
        Dibuja las bandas como barras en la PARTE INFERIOR del gráfico.
        Con detección inteligente de colisiones de etiquetas.
        """
        # Limpiar regiones existentes
        self._clear_band_regions()
        
        if not self.plot_widget:
            return
        
        try:
            # Obtener el rango visible actual
            x_range = self.plot_widget.getViewBox().viewRange()[0]
            start_mhz = x_range[0]
            end_mhz = x_range[1]
            
            # Obtener bandas en el rango visible
            bands = self.band_plan.get_bands_in_range(start_mhz, end_mhz)
            
            if not bands:
                return
            
            # Obtener el rango Y del gráfico
            y_range = self.plot_widget.getViewBox().viewRange()[1]
            y_min = y_range[0]
            y_max = y_range[1]
            
            # Calcular altura de la barra (3-4% de la altura total)
            bar_height = (y_max - y_min) * 0.035
            bar_y_top = y_min + 2  # Pequeño margen desde el borde inferior
            bar_y_bottom = bar_y_top + bar_height
            
            from PyQt5.QtWidgets import QGraphicsRectItem
            from PyQt5.QtCore import QRectF
            
            # ===== PASO 1: Dibujar todas las barras primero =====
            for band in bands:
                band_start = max(band['start_mhz'], start_mhz)
                band_end = min(band['end_mhz'], end_mhz)
                
                if band_start >= band_end:
                    continue
                
                # Obtener color de la banda
                color = self.band_plan.get_band_color(band, alpha=220)
                border_color = self.band_plan.get_band_color(band, alpha=255)
                
                # Crear rectángulo para la barra inferior
                bar_rect = QGraphicsRectItem()
                bar_rect.setRect(QRectF(band_start, bar_y_top, 
                                        band_end - band_start, bar_height))
                bar_rect.setBrush(color)
                bar_rect.setPen(pg.mkPen(color=border_color, width=1))
                bar_rect.setZValue(-5)
                
                self.plot_widget.addItem(bar_rect)
                self.band_regions.append(bar_rect)
                
                # Guardar información de la banda para las etiquetas
                band['_rect'] = (band_start, band_end, bar_y_top, bar_height)
            
            # ===== PASO 2: Calcular posiciones de etiquetas evitando colisiones =====
            # Lista para almacenar las posiciones ya ocupadas
            used_positions = []
            
            # Ordenar bandas por ancho (más anchas primero, para dar prioridad)
            bands_sorted = sorted(bands, key=lambda b: (b['end_mhz'] - b['start_mhz']), reverse=True)
            
            for band in bands_sorted:
                band_start = max(band['start_mhz'], start_mhz)
                band_end = min(band['end_mhz'], end_mhz)
                band_width = band_end - band_start
                
                # Solo mostrar etiqueta si la banda es suficientemente ancha
                if band_width < 1.5:
                    continue
                
                # Obtener nombre para mostrar
                display_name = band.get('display', band.get('name', ''))
                
                # Acortar nombres muy largos según el ancho disponible
                max_chars = max(4, int(band_width / 2.5))  # Aprox 2.5 MHz por carácter
                if len(display_name) > max_chars:
                    display_name = display_name[:max_chars-2] + ".."
                
                # Posición candidata (centro de la banda)
                candidate_pos = (band_start + band_end) / 2
                
                # Verificar si esta posición colisiona con etiquetas existentes
                collision = False
                for used_pos, used_width in used_positions:
                    # Si la distancia entre centros es menor que el promedio de los anchos
                    distance = abs(candidate_pos - used_pos)
                    min_distance = (band_width + used_width) / 2.5  # Factor de separación
                    
                    if distance < min_distance:
                        collision = True
                        break
                
                # Si hay colisión, intentar desplazar la etiqueta
                if collision:
                    # Intentar poner a la izquierda
                    left_pos = band_start + band_width * 0.25
                    left_collision = False
                    for used_pos, used_width in used_positions:
                        if abs(left_pos - used_pos) < (band_width + used_width) / 3:
                            left_collision = True
                            break
                    
                    if not left_collision and left_pos > band_start + 0.5:
                        final_pos = left_pos
                    else:
                        # Intentar poner a la derecha
                        right_pos = band_end - band_width * 0.25
                        right_collision = False
                        for used_pos, used_width in used_positions:
                            if abs(right_pos - used_pos) < (band_width + used_width) / 3:
                                right_collision = True
                                break
                        
                        if not right_collision and right_pos < band_end - 0.5:
                            final_pos = right_pos
                        else:
                            # Si todo falla, no mostrar etiqueta
                            continue
                else:
                    final_pos = candidate_pos
                
                # Registrar esta posición para futuras colisiones
                used_positions.append((final_pos, band_width))
                
                # Crear etiqueta de texto
                label = pg.TextItem(
                    text=display_name,
                    color=(255, 255, 255, 255),
                    anchor=(0.5, 0.5)
                )
                
                # Posicionar en la posición calculada
                label.setPos(final_pos, bar_y_top + bar_height / 2)
                label.setZValue(-4)
                
                # Añadir tooltip con información detallada
                tooltip = f"<b>{band.get('display', band.get('name', ''))}</b><br>"
                tooltip += f"{band['start_mhz']:.1f} - {band['end_mhz']:.1f} MHz<br>"
                if band.get('description'):
                    tooltip += f"{band['description']}<br>"
                if band.get('type'):
                    tooltip += f"Tipo: {band.get('type')}"
                
                label.setToolTip(tooltip)
                
                self.plot_widget.addItem(label)
                self.band_regions.append(label)
            
            # Añadir línea divisoria superior de la barra (opcional)
            if bands:
                divider_line = pg.InfiniteLine(
                    pos=bar_y_top + bar_height,
                    angle=0,
                    pen=pg.mkPen('#666666', width=1, style=Qt.DashLine),
                    movable=False
                )
                divider_line.setZValue(-3)
                self.plot_widget.addItem(divider_line)
                self.band_regions.append(divider_line)
            
            # Log
            self.logger.debug(f"📡 {len(bands)} bandas dibujadas, {len(used_positions)} etiquetas colocadas")
            
        except Exception as e:
            self.logger.error(f"Error dibujando bandas: {e}")
            import traceback
            traceback.print_exc()


    '''def _draw_band_regions(self):
        """
        Dibuja las bandas como barras en la PARTE INFERIOR del gráfico.
        Estilo profesional: barras coloreadas con etiquetas en la parte baja.
        No interfiere con la visualización del espectro.
        """
        # Limpiar regiones existentes
        self._clear_band_regions()
        
        if not self.plot_widget:
            return
        
        try:
            # Obtener el rango visible actual
            x_range = self.plot_widget.getViewBox().viewRange()[0]
            start_mhz = x_range[0]
            end_mhz = x_range[1]
            
            # Obtener bandas en el rango visible
            bands = self.band_plan.get_bands_in_range(start_mhz, end_mhz)
            
            # Obtener el rango Y del gráfico
            y_range = self.plot_widget.getViewBox().viewRange()[1]
            y_min = y_range[0]
            y_max = y_range[1]
            
            # Calcular altura de la barra (3-4% de la altura total)
            bar_height = (y_max - y_min) * 0.035  # 3.5% de la altura
            
            # Posición Y de la barra (parte inferior)
            bar_y_bottom = y_min  # Base del gráfico
            bar_y_top = y_min + bar_height  # Parte superior de la barra
            
            from PyQt5.QtWidgets import QGraphicsRectItem
            from PyQt5.QtCore import QRectF
            
            for band in bands:
                # Calcular los límites de la banda dentro del rango visible
                band_start = max(band['start_mhz'], start_mhz)
                band_end = min(band['end_mhz'], end_mhz)
                
                if band_start >= band_end:
                    continue
                
                # Obtener color de la banda (más opaco para las barras)
                color = self.band_plan.get_band_color(band, alpha=220)
                border_color = self.band_plan.get_band_color(band, alpha=255)
                
                # Crear rectángulo para la barra inferior
                bar_rect = QGraphicsRectItem()
                bar_rect.setRect(QRectF(band_start, bar_y_top, 
                                        band_end - band_start, bar_height))
                bar_rect.setBrush(color)
                bar_rect.setPen(pg.mkPen(color=border_color, width=1))
                bar_rect.setZValue(-5)  # Detrás de las curvas pero visible
                
                self.plot_widget.addItem(bar_rect)
                self.band_regions.append(bar_rect)
                
                # Añadir etiqueta si la banda es suficientemente ancha
                band_width_mhz = band_end - band_start
                if band_width_mhz > 1.5:
                    # Obtener nombre para mostrar
                    display_name = band.get('display', band.get('name', ''))
                    
                    # Acortar nombres muy largos
                    if len(display_name) > 14:
                        display_name = display_name[:12] + "..."
                    
                    # Crear etiqueta de texto
                    label = pg.TextItem(
                        text=display_name,
                        color=(255, 255, 255, 255),
                        anchor=(0.5, 0.5)
                    )
                    
                    # Posicionar en el centro de la banda, dentro de la barra
                    label.setPos((band_start + band_end) / 2, bar_y_top + bar_height / 2)
                    label.setZValue(-4)
                    
                    # Añadir tooltip con información detallada
                    tooltip = f"<b>{band.get('display', band.get('name', ''))}</b><br>"
                    tooltip += f"{band['start_mhz']:.1f} - {band['end_mhz']:.1f} MHz<br>"
                    if band.get('description'):
                        tooltip += f"{band['description']}<br>"
                    if band.get('type'):
                        tooltip += f"Tipo: {band.get('type')}"
                    
                    label.setToolTip(tooltip)
                    bar_rect.setToolTip(tooltip)
                    
                    self.plot_widget.addItem(label)
                    self.band_regions.append(label)
            
            # Añadir línea divisoria superior de la barra (opcional)
            if bands:
                divider_line = pg.InfiniteLine(
                    pos=bar_y_top + bar_height,
                    angle=0,
                    pen=pg.mkPen('#666666', width=1, style=Qt.DashLine),
                    movable=False
                )
                divider_line.setZValue(-3)
                self.plot_widget.addItem(divider_line)
                self.band_regions.append(divider_line)
            
            # Log si se dibujaron bandas
            if bands:
                self.logger.debug(f"📡 {len(bands)} bandas dibujadas como barras inferiores")
            
        except Exception as e:
            self.logger.error(f"Error dibujando bandas: {e}")
            import traceback
            traceback.print_exc()'''
    
    def _clear_band_regions(self):
        """Elimina todas las regiones de bandas dibujadas"""
        for item in self.band_regions:
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self.band_regions.clear()

    
    def update_band_regions(self):
        """Actualiza las regiones de bandas (llamar cuando cambia el rango)"""
        if self.show_band_plan:
            self._draw_band_regions()


    def _update_plot_range(self, center_freq: float, sample_rate: float):
        """Actualiza el rango del plot y refresca las bandas"""
        try:
            min_freq = center_freq - sample_rate / 2
            max_freq = center_freq + sample_rate / 2
            
            self.plot_widget.setXRange(min_freq, max_freq)
            
            # ===== NUEVO: Actualizar regiones de bandas =====
            if self.show_band_plan:
                # Pequeño retraso para asegurar que el rango se actualizó
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(50, self.update_band_regions)
                
        except Exception as e:
            self.logger.error(f"Error actualizando rango del plot: {e}")


    def _on_range_changed(self, viewbox, range):
        """Manejador cuando cambia el rango (zoom/pan)"""
        if self.show_band_plan:
            self.update_band_regions()
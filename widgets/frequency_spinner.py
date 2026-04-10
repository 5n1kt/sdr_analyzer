# widgets/frequency_spinner.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import numpy as np
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal
import logging


# =======================================================================
# SPINNER DE FRECUENCIA CON SELECCIÓN DE DÍGITOS - VERSIÓN GRANDE
# =======================================================================
class FrequencySpinner(QWidget):
    """
    Widget para entrada de frecuencia con selección de dígitos individuales.
    Versión con dígitos más grandes para mejor visualización.
    """
    
    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    frequencyChanged = pyqtSignal(float)
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, initial_freq_mhz=100.0, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.frequency_mhz = initial_freq_mhz
        self.selected_digit = 8
        self.digit_labels = []
        
        # Inicializar _theme_manager
        self._theme_manager = None
        
        # Colores por defecto
        self.normal_bg = "#181818"
        self.normal_fg = "#DCDCDC"
        self.normal_border = "#404040"
        self.selected_bg = "#0080ff"
        self.selected_fg = "#FFFFFF"
        self.selected_border = "#0080ff"
        self.hover_bg = "#2A2A2A"
        self.hover_border = "#0080ff"
        self.unit_color = "#DCDCDC"
        
        # Buscar theme_manager
        self._find_theme_manager(parent)
        
        if self._theme_manager:
            self._theme_manager.theme_changed.connect(self.on_theme_changed)
            current_theme = self._theme_manager.current_theme
            self.on_theme_changed(current_theme)
        else:
            self.logger.warning("⚠️ No se encontró theme_manager")
        
        # Configurar UI con tamaño aumentado
        self._setup_ui()
    
    def _find_theme_manager(self, widget):
        """Busca recursivamente el theme_manager en la jerarquía de padres."""
        current = widget
        while current:
            if hasattr(current, 'theme_manager'):
                self._theme_manager = current.theme_manager
                return True
            current = current.parent()
        return False
    
    def on_theme_changed(self, theme_key):
        """Actualiza los colores cuando cambia el tema."""
        if self._theme_manager is None:
            return
        
        try:
            theme = self._theme_manager.get_theme_colors(theme_key)
            
            # Actualizar colores según el tema
            self.normal_bg = theme['spinner_bg'].name()
            self.normal_fg = theme['spinner_fg'].name()
            self.normal_border = theme['spinner_border'].name()
            self.selected_bg = theme['accent'].name()
            self.selected_fg = "#FFFFFF"
            self.selected_border = theme['accent'].name()
            self.hover_bg = theme['button_hover'].name()
            self.hover_border = theme['border_focus'].name()
            self.unit_color = theme['spinner_fg'].name()
            
            # Actualizar la visualización
            self._update_display()
            
        except Exception as e:
            self.logger.error(f"❌ Error actualizando colores: {e}")
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN DE UI - TAMAÑOS AUMENTADOS
    # -----------------------------------------------------------------------
    def _setup_ui(self):
        """Configura la interfaz del spinner con dígitos más grandes."""
        layout = QHBoxLayout()
        layout.setSpacing(2)  # Espacio entre dígitos
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Aumentar altura total del widget
        self.setFixedHeight(48)  # Antes era 30
        
        freq_str = self._format_frequency(self.frequency_mhz)
        
        for i, char in enumerate(freq_str):
            if char == ' ':
                # Espaciador entre grupos de dígitos
                space_label = QLabel(" ")
                space_label.setFixedSize(8, 40)  # Más ancho y alto
                space_label.setStyleSheet("background: transparent;")
                layout.addWidget(space_label)
                continue
            
            # Crear label para cada dígito con tamaño aumentado
            digit_label = QLabel(char)
            digit_label.setAlignment(Qt.AlignCenter)
            digit_label.setFixedSize(32, 40)  # Antes era 18x24
            digit_label.setCursor(Qt.PointingHandCursor)
            digit_label.mousePressEvent = lambda event, idx=len(self.digit_labels): self._digit_clicked(event, idx)
            
            # Asignar object name para estilos CSS
            digit_label.setObjectName("digitLabel")
            
            layout.addWidget(digit_label)
            self.digit_labels.append(digit_label)
        
        # Etiqueta de unidad (Hz) con tamaño aumentado
        unit_label = QLabel("Hz")
        unit_label.setObjectName("unitLabel")
        unit_label.setFixedHeight(40)
        unit_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        unit_label.setStyleSheet(f"""
            color: {self.unit_color};
            font-weight: bold;
            font-size: 12pt;  /* Aumentado */
            background-color: transparent;
            margin-left: 4px;
        """)
        layout.addWidget(unit_label)
        
        layout.addStretch()
        self.setLayout(layout)
        
        self._update_display()
        self.setFocusPolicy(Qt.StrongFocus)
    
    def _get_digit_style(self, selected):
        """Obtiene el estilo para un dígito con fuente más grande."""
        base_style = f"""
            border: 1px solid {self.normal_border};
            background-color: {self.normal_bg};
            color: {self.normal_fg};
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 16pt;  /* Antes era 10pt/9pt */
            border-radius: 2px;
        """
        
        hover_style = f"""
            border: 1px solid {self.hover_border};
            background-color: {self.hover_bg};
        """
        
        selected_style = f"""
            border: 2px solid {self.selected_border};
            background-color: {self.selected_bg};
            color: {self.selected_fg};
        """
        
        if selected:
            return f"QLabel {{{selected_style}}}"
        else:
            return f"""
                QLabel {{{base_style}}}
                QLabel:hover {{{hover_style}}}
            """
    
    # -----------------------------------------------------------------------
    # MÉTODOS DE FORMATEO
    # -----------------------------------------------------------------------
    def _format_frequency(self, freq_mhz: float) -> str:
        """Formatea frecuencia como "00 000 000 000" (GHz MHz kHz Hz)"""
        try:
            freq_hz = int(freq_mhz * 1e6)
            freq_str = f"{freq_hz:011d}"
            
            if len(freq_str) == 11:
                formatted = f"{freq_str[0:2]} {freq_str[2:5]} {freq_str[5:8]} {freq_str[8:11]}"
                return formatted
            else:
                return "00 000 000 000"
        except Exception as e:
            print(f"Error formateando frecuencia: {e}")
            return "00 000 000 000"
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS
    # -----------------------------------------------------------------------
    def setFrequency(self, freq_mhz: float):
        """Establece la frecuencia y actualiza la visualización."""
        old_freq_rounded = round(self.frequency_mhz * 1e6)
        new_freq_rounded = round(freq_mhz * 1e6)
        
        if old_freq_rounded != new_freq_rounded:
            self.frequency_mhz = freq_mhz
            self._update_display()
            self.frequencyChanged.emit(self.frequency_mhz)
    
    # -----------------------------------------------------------------------
    # MANEJO DE EVENTOS
    # -----------------------------------------------------------------------
    def _digit_clicked(self, event, digit_index: int):
        """Manejador para clicks en dígitos."""
        self.selected_digit = digit_index
        self.setFocus()
        self._update_display()
    
    def _update_display(self):
        """Actualiza la visualización de todos los dígitos."""
        freq_str = self._format_frequency(self.frequency_mhz).replace(' ', '')
        
        if len(freq_str) != 11:
            freq_str = freq_str.zfill(11)
        
        for i, char in enumerate(freq_str):
            if i < len(self.digit_labels):
                self.digit_labels[i].setText(char)
                self.digit_labels[i].setStyleSheet(self._get_digit_style(i == self.selected_digit))
        
        # Actualizar color de la unidad
        if hasattr(self, 'unit_label'):
            self.unit_label.setStyleSheet(f"""
                color: {self.unit_color};
                font-weight: bold;
                font-size: 12pt;
                background-color: transparent;
            """)
    
    def wheelEvent(self, event):
        """Maneja la rueda del ratón para cambiar el dígito seleccionado."""
        if 0 <= self.selected_digit < len(self.digit_labels):
            digit_weights_hz = [
                10_000_000_000, 1_000_000_000, 100_000_000, 10_000_000,
                1_000_000, 100_000, 10_000, 1_000, 100, 10, 1
            ]
            
            if self.selected_digit < len(digit_weights_hz):
                increment_hz = digit_weights_hz[self.selected_digit]
                increment_mhz = increment_hz / 1e6
                
                if event.angleDelta().y() > 0:
                    new_freq_mhz = self.frequency_mhz + increment_mhz
                else:
                    new_freq_mhz = self.frequency_mhz - increment_mhz
                
                new_freq_mhz = max(1.0, min(6000.0, new_freq_mhz))
                
                if abs(new_freq_mhz - self.frequency_mhz) > 0.0000001:
                    self.frequency_mhz = new_freq_mhz
                    self._update_display()
                    self.frequencyChanged.emit(self.frequency_mhz)
    
    def keyPressEvent(self, event):
        """Maneja teclas para navegación."""
        if event.key() == Qt.Key_Left:
            self.selected_digit = max(0, self.selected_digit - 1)
            self._update_display()
        elif event.key() == Qt.Key_Right:
            self.selected_digit = min(len(self.digit_labels) - 1, self.selected_digit + 1)
            self._update_display()
        elif event.key() == Qt.Key_Up:
            fake_event = type('Event', (), {'angleDelta': lambda: type('Delta', (), {'y': 120})()})()
            self.wheelEvent(fake_event)
        elif event.key() == Qt.Key_Down:
            fake_event = type('Event', (), {'angleDelta': lambda: type('Delta', (), {'y': -120})()})()
            self.wheelEvent(fake_event)
        else:
            super().keyPressEvent(event)
    
    def mousePressEvent(self, event):
        """Asegura que el widget obtenga el foco al hacer click."""
        self.setFocus()
        super().mousePressEvent(event)
# -*- coding: utf-8 -*-

"""
Frequency Spinner Widget
========================
Widget for entering frequency with individual digit selection.

Features:
    - Large digits (48px height) for better visibility
    - Mouse wheel support for digit increment/decrement
    - Keyboard navigation (left/right arrows, up/down)
    - Digit selection by click
    - Theme-aware colors (connects to ThemeManager)
    - Format: "GG GGG GGG GGG" (GHz MHz kHz Hz groups)
"""

import logging
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QApplication
from PyQt5.QtCore import Qt, pyqtSignal


# ============================================================================
# FREQUENCY SPINNER
# ============================================================================

class FrequencySpinner(QWidget):
    """
    Widget for frequency entry with individual digit selection.
    
    The frequency is displayed as groups of digits:
        GG GGG GGG GGG Hz
        (GHz) (MHz) (kHz) (Hz)
    
    Signals:
        frequencyChanged: Emitted when frequency changes (MHz)
    """
    
    frequencyChanged = pyqtSignal(float)
    
    # Digit weights in Hz for each position
    DIGIT_WEIGHTS_HZ = [
        10_000_000_000,  # 10 GHz (position 0)
        1_000_000_000,   # 1 GHz (position 1)
        100_000_000,     # 100 MHz (position 2)
        10_000_000,      # 10 MHz (position 3)
        1_000_000,       # 1 MHz (position 4)
        100_000,         # 100 kHz (position 5)
        10_000,          # 10 kHz (position 6)
        1_000,           # 1 kHz (position 7)
        100,             # 100 Hz (position 8)
        10,              # 10 Hz (position 9)
        1                # 1 Hz (position 10)
    ]
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, initial_freq_mhz: float = 100.0, parent=None):
        """
        Initialize frequency spinner.
        
        Args:
            initial_freq_mhz: Initial frequency in MHz
            parent: Parent widget
        """
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.frequency_mhz = initial_freq_mhz
        self.selected_digit = 8  # Start with MHz digit (position 8 = 100 Hz weight)
        self.digit_labels = []
        
        # Theme colors (will be updated by ThemeManager)
        self._theme_manager = None
        self._init_default_colors()
        
        # Find ThemeManager in parent hierarchy
        self._find_theme_manager(parent)
        
        if self._theme_manager:
            self._theme_manager.theme_changed.connect(self.on_theme_changed)
            current_theme = self._theme_manager.current_theme
            self.on_theme_changed(current_theme)
        
        # Setup UI
        self._setup_ui()
    
    def _init_default_colors(self) -> None:
        """Initialize default colors (dark theme fallback)."""
        self.normal_bg = "#181818"
        self.normal_fg = "#DCDCDC"
        self.normal_border = "#404040"
        self.selected_bg = "#0080ff"
        self.selected_fg = "#FFFFFF"
        self.selected_border = "#0080ff"
        self.hover_bg = "#2A2A2A"
        self.hover_border = "#0080ff"
        self.unit_color = "#DCDCDC"
    
    def _find_theme_manager(self, widget) -> bool:
        """Find ThemeManager in parent hierarchy."""
        current = widget
        while current:
            if hasattr(current, 'theme_manager'):
                self._theme_manager = current.theme_manager
                return True
            current = current.parent()
        return False
    
    def on_theme_changed(self, theme_key: str) -> None:
        """Update colors when theme changes."""
        if self._theme_manager is None:
            return
        
        try:
            theme = self._theme_manager.get_theme_colors(theme_key)
            self.normal_bg = theme['spinner_bg'].name()
            self.normal_fg = theme['spinner_fg'].name()
            self.normal_border = theme['spinner_border'].name()
            self.selected_bg = theme['accent'].name()
            self.selected_fg = "#FFFFFF"
            self.selected_border = theme['accent'].name()
            self.hover_bg = theme['button_hover'].name()
            self.hover_border = theme['border_focus'].name()
            self.unit_color = theme['spinner_fg'].name()
            self._update_display()
        except Exception as e:
            self.logger.error(f"Error updating colors: {e}")
    
    # ------------------------------------------------------------------------
    # UI SETUP
    # ------------------------------------------------------------------------
    
    def _setup_ui(self) -> None:
        """Create and arrange digit labels."""
        layout = QHBoxLayout()
        layout.setSpacing(2)
        layout.setContentsMargins(4, 4, 4, 4)
        self.setFixedHeight(48)
        
        # Format frequency as "GG GGG GGG GGG"
        freq_str = self._format_frequency(self.frequency_mhz)
        
        for i, char in enumerate(freq_str):
            if char == ' ':
                # Spacer between digit groups
                space_label = QLabel(" ")
                space_label.setFixedSize(8, 40)
                space_label.setStyleSheet("background: transparent;")
                layout.addWidget(space_label)
                continue
            
            # Digit label
            digit_label = QLabel(char)
            digit_label.setAlignment(Qt.AlignCenter)
            digit_label.setFixedSize(32, 40)
            digit_label.setCursor(Qt.PointingHandCursor)
            digit_label.mousePressEvent = lambda event, idx=len(self.digit_labels): self._digit_clicked(event, idx)
            digit_label.setObjectName("digitLabel")
            
            layout.addWidget(digit_label)
            self.digit_labels.append(digit_label)
        
        # Unit label
        unit_label = QLabel("Hz")
        unit_label.setObjectName("unitLabel")
        unit_label.setFixedHeight(40)
        unit_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        unit_label.setStyleSheet(
            f"color: {self.unit_color}; font-weight: bold; "
            f"font-size: 12pt; background: transparent; margin-left: 4px;"
        )
        layout.addWidget(unit_label)
        
        layout.addStretch()
        self.setLayout(layout)
        
        self._update_display()
        self.setFocusPolicy(Qt.StrongFocus)
    
    def _get_digit_style(self, selected: bool) -> str:
        """Get stylesheet for a digit label."""
        base_style = f"""
            border: 1px solid {self.normal_border};
            background-color: {self.normal_bg};
            color: {self.normal_fg};
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 16pt;
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
    
    def _format_frequency(self, freq_mhz: float) -> str:
        """
        Format frequency as "GG GGG GGG GGG".
        
        Example: 2410.5 MHz -> "00 002 410 500 000" Hz
        """
        try:
            freq_hz = int(freq_mhz * 1e6)
            freq_str = f"{freq_hz:011d}"
            if len(freq_str) == 11:
                return f"{freq_str[0:2]} {freq_str[2:5]} {freq_str[5:8]} {freq_str[8:11]}"
            return "00 000 000 000"
        except Exception:
            return "00 000 000 000"
    
    # ------------------------------------------------------------------------
    # PUBLIC METHODS
    # ------------------------------------------------------------------------
    
    def setFrequency(self, freq_mhz: float) -> None:
        """
        Set frequency and update display.
        
        Args:
            freq_mhz: New frequency in MHz
        """
        old_freq_rounded = round(self.frequency_mhz * 1e6)
        new_freq_rounded = round(freq_mhz * 1e6)
        
        if old_freq_rounded != new_freq_rounded:
            self.frequency_mhz = freq_mhz
            self._update_display()
            self.frequencyChanged.emit(self.frequency_mhz)
    
    def getFrequency(self) -> float:
        """Get current frequency in MHz."""
        return self.frequency_mhz
    
    # ------------------------------------------------------------------------
    # CORE LOGIC - INCREMENT/DECREMENT
    # ------------------------------------------------------------------------
    
    def _increment_selected_digit(self, direction: int) -> None:
        """
        Increment or decrement the selected digit.
        
        Args:
            direction: 1 for increment, -1 for decrement
        """
        if not (0 <= self.selected_digit < len(self.DIGIT_WEIGHTS_HZ)):
            return
        
        increment_hz = self.DIGIT_WEIGHTS_HZ[self.selected_digit] * direction
        increment_mhz = increment_hz / 1e6
        
        new_freq_mhz = self.frequency_mhz + increment_mhz
        new_freq_mhz = max(1.0, min(6000.0, new_freq_mhz))
        
        if abs(new_freq_mhz - self.frequency_mhz) > 0.0000001:
            self.frequency_mhz = new_freq_mhz
            self._update_display()
            self.frequencyChanged.emit(self.frequency_mhz)
    
    # ------------------------------------------------------------------------
    # EVENT HANDLERS
    # ------------------------------------------------------------------------
    
    def _digit_clicked(self, event, digit_index: int) -> None:
        """Handle digit click - select digit for editing."""
        self.selected_digit = digit_index
        self.setFocus()
        self._update_display()
    
    def _update_display(self) -> None:
        """Update all digit labels."""
        freq_str = self._format_frequency(self.frequency_mhz).replace(' ', '')
        
        if len(freq_str) != 11:
            freq_str = freq_str.zfill(11)
        
        for i, char in enumerate(freq_str):
            if i < len(self.digit_labels):
                self.digit_labels[i].setText(char)
                self.digit_labels[i].setStyleSheet(
                    self._get_digit_style(i == self.selected_digit)
                )
    
    def wheelEvent(self, event) -> None:
        """
        Handle mouse wheel for digit increment/decrement.
        """
        delta = event.angleDelta().y()
        if delta > 0:
            self._increment_selected_digit(1)
        elif delta < 0:
            self._increment_selected_digit(-1)
    
    def keyPressEvent(self, event) -> None:
        """
        Handle keyboard navigation.
        
        Keys:
            Left/Right: Move between digits
            Up/Down: Increment/decrement selected digit
        """
        if event.key() == Qt.Key_Left:
            self.selected_digit = max(0, self.selected_digit - 1)
            self._update_display()
        elif event.key() == Qt.Key_Right:
            self.selected_digit = min(len(self.digit_labels) - 1, self.selected_digit + 1)
            self._update_display()
        elif event.key() == Qt.Key_Up:
            self._increment_selected_digit(1)
        elif event.key() == Qt.Key_Down:
            self._increment_selected_digit(-1)
        else:
            super().keyPressEvent(event)
    
    def mousePressEvent(self, event) -> None:
        """Ensure widget gets focus on click."""
        self.setFocus()
        super().mousePressEvent(event)
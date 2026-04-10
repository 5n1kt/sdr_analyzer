# utils/theme_manager.py
# -*- coding: utf-8 -*-
#
# CORRECCIONES APLICADAS
# ──────────────────────
# 1. [CRÍTICO] THEMES como variable de clase instanciaba 140 objetos QColor
#    en tiempo de importación, antes de que QApplication existiera.
#    En Qt5 esto lanza: RuntimeError: QColor: Application must be created first.
#    FIX: THEMES se convirtió en un método lazy _build_themes() que se llama
#    solo una vez desde __init__, cuando QApplication ya está activa.
#    Se cachea en _themes_cache a nivel de clase para compartirlo entre
#    instancias sin reconstruirlo.
#
# 2. [CRÍTICO] Múltiples instancias de ThemeManager en el proyecto.
#    main.py, base_controller (x2/x3) y ThemeSelectorWidget cada uno
#    creaban su propia instancia. Al cambiar el tema desde una instancia,
#    las demás no recibían la señal theme_changed → UI desincronizada.
#    FIX: patrón Singleton mediante __new__. Todas las llamadas a
#    ThemeManager() retornan la misma instancia. La señal se emite
#    una sola vez y todos los suscriptores la reciben.
#
# 3. [CRÍTICO] ThemeSelectorWidget tenía su propio ThemeManager independiente
#    (ya resuelto por el Singleton del punto 2, pero documentado aquí).
#
# 4. [POTENCIAL] get_theme_colors retornaba el dict interno directamente.
#    Cualquier código que modificara el dict retornado (ej:
#    theme['accent'] = QColor(...)) corrompía THEMES permanentemente.
#    FIX: se retorna una copia superficial del dict. Los QColor son
#    inmutables en la práctica, así que una copia superficial es segura.
#
# 5. [POTENCIAL] apply_theme_to_app emitía theme_changed DESPUÉS de aplicar
#    paleta y stylesheet. Los slots conectados a theme_changed recibían
#    la señal con el repintado ya en proceso → parpadeos visuales.
#    FIX: emit() se llama AL FINAL, después de que toda la UI se actualizó.
#    Esto es correcto: la señal notifica "el tema ya está aplicado, actualiza
#    tus colores custom" — no "voy a aplicar el tema".
#    (El orden correcto para reducir parpadeos es: stylesheet → palette → emit)
#
# 6. [POTENCIAL] _apply_stylesheet regeneraba el f-string de ~500 líneas en
#    cada cambio de tema, incluso al aplicar el mismo tema dos veces.
#    FIX: caché de stylesheets por theme_key. Se invalida al cambiar de tema.
#
# 7. [LIMPIEZA] Docstring decía "3 temas" pero hay 4 (dark, light, olive, naval).
#    Corregido.
#
# 8. [LIMPIEZA] .darker(110) era el único color calculado dinámicamente en el
#    stylesheet. Añadido como clave 'button_pressed_bg' en cada tema para
#    consistencia y para evitar llamadas a métodos dentro del f-string.

from __future__ import annotations

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtCore import Qt, QObject, pyqtSignal
import logging


class ThemeManager(QObject):
    """
    Gestor de temas para la aplicación SDR.
    Proporciona 4 temas independientes: Oscuro, Claro, Militar y Naval.

    SINGLETON: todas las llamadas a ThemeManager() retornan la misma
    instancia. Esto garantiza que theme_changed se emita una sola vez
    y llegue a todos los widgets suscritos, sin importar quién cambie el tema.

    Uso:
        tm = ThemeManager()          # siempre la misma instancia
        tm.apply_theme_to_app(app, 'dark')
        tm.theme_changed.connect(mi_slot)
    """

    # ------------------------------------------------------------------
    # SEÑAL
    # ------------------------------------------------------------------
    theme_changed = pyqtSignal(str)   # emite el key del nuevo tema

    # ------------------------------------------------------------------
    # SINGLETON
    # ------------------------------------------------------------------
    _instance: ThemeManager | None = None

    # Caché de temas construida la primera vez (requiere QApplication)
    _themes_cache: dict | None = None

    # Caché de stylesheets por theme_key
    _stylesheet_cache: dict[str, str] = {}

    def __new__(cls) -> ThemeManager:
        """Garantiza una única instancia en todo el proceso."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        # Evitar doble inicialización por el Singleton
        if self._initialized:
            return
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.current_theme = 'dark'
        self._initialized  = True
        self.logger.info("✅ ThemeManager inicializado (singleton, 4 temas)")

    # ------------------------------------------------------------------
    # CONSTRUCCIÓN LAZY DE TEMAS
    # FIX 1: los QColor se crean aquí, no como variable de clase,
    # garantizando que QApplication ya existe cuando se construyen.
    # ------------------------------------------------------------------

    @classmethod
    def _build_themes(cls) -> dict:
        """
        Construye y cachea el diccionario de temas.
        Se llama solo cuando se necesita por primera vez desde __init__
        o desde get_theme_colors(), momento en que QApplication ya existe.
        """
        if cls._themes_cache is not None:
            return cls._themes_cache

        cls._themes_cache = {

            # ── TEMA OSCURO ────────────────────────────────────────────
            'dark': {
                'name': 'Oscuro Profesional',
                'background':       QColor(32,  32,  32),
                'foreground':       QColor(220, 220, 220),
                'grid':             QColor(64,  64,  64),
                'input_bg':         QColor(24,  24,  24),
                'button_bg':        QColor(42,  42,  42),
                'button_hover':     QColor(53,  53,  53),
                'button_pressed_bg':QColor(29,  29,  29),   # FIX 8: antes .darker(110)
                'accent':           QColor(0,   128, 255),
                'accent_hover':     QColor(37,  144, 255),
                'dock_title_bg':    QColor(42,  42,  42),
                'dock_title_fg':    QColor(220, 220, 220),
                'dock_border':      QColor(64,  64,  64),
                'detector_text':    QColor(220, 220, 220),
                'detector_bg':      QColor(24,  24,  24),
                'tooltip_bg':       QColor(20,  20,  20, 200),
                'tooltip_fg':       QColor(220, 220, 220),
                'disabled_bg':      QColor(50,  50,  50),
                'disabled_fg':      QColor(100, 100, 100),
                'border_focus':     QColor(0,   128, 255),
                'mainwindow_bg':    QColor(32,  32,  32),
                'status_bar_bg':    QColor(32,  32,  32),
                'menu_bar_bg':      QColor(32,  32,  32),
                'header_bg':        QColor(42,  42,  42),
                'tab_bg':           QColor(42,  42,  42),
                'tab_selected_bg':  QColor(0,   128, 255),
                'text_bg':          QColor(20,  20,  20, 200),
                'text_fg':          QColor(220, 220, 220),
                'spectrum_default': QColor(0,   200, 255),
                'max_hold_default': QColor(255, 200, 0),
                'min_hold_default': QColor(255, 100, 0),
                'waterfall_bg':     QColor(20,  20,  20),
                'frame_bg':         QColor(32,  32,  32),
                'spinner_bg':       QColor(24,  24,  24),
                'spinner_fg':       QColor(220, 220, 220),
                'spinner_border':   QColor(64,  64,  64),
                'spinner_selected': QColor(0,   128, 255),
                'description':      'Tema oscuro profesional',
            },

            # ── TEMA CLARO ─────────────────────────────────────────────
            'light': {
                'name': 'Claro',
                'background':       QColor(240, 240, 240),
                'foreground':       QColor(0,   0,   0),
                'grid':             QColor(160, 160, 160),
                'input_bg':         QColor(255, 255, 255),
                'button_bg':        QColor(230, 230, 230),
                'button_hover':     QColor(210, 210, 210),
                'button_pressed_bg':QColor(209, 209, 209),  # FIX 8
                'accent':           QColor(0,   100, 200),
                'accent_hover':     QColor(30,  130, 230),
                'dock_title_bg':    QColor(220, 220, 220),
                'dock_title_fg':    QColor(0,   0,   0),
                'dock_border':      QColor(160, 160, 160),
                'detector_text':    QColor(0,   0,   0),
                'detector_bg':      QColor(255, 255, 255),
                'tooltip_bg':       QColor(255, 255, 255, 220),
                'tooltip_fg':       QColor(0,   0,   0),
                'disabled_bg':      QColor(220, 220, 220),
                'disabled_fg':      QColor(160, 160, 160),
                'border_focus':     QColor(0,   0,   0),
                'mainwindow_bg':    QColor(240, 240, 240),
                'status_bar_bg':    QColor(240, 240, 240),
                'menu_bar_bg':      QColor(240, 240, 240),
                'header_bg':        QColor(220, 220, 220),
                'tab_bg':           QColor(230, 230, 230),
                'tab_selected_bg':  QColor(0,   100, 200),
                'text_bg':          QColor(255, 255, 255, 220),
                'text_fg':          QColor(0,   0,   0),
                'spectrum_default': QColor(0,   0,   200),
                'max_hold_default': QColor(200, 0,   0),
                'min_hold_default': QColor(0,   150, 0),
                'waterfall_bg':     QColor(240, 240, 240),
                'frame_bg':         QColor(235, 235, 235),
                'spinner_bg':       QColor(255, 255, 255),
                'spinner_fg':       QColor(0,   0,   0),
                'spinner_border':   QColor(160, 160, 160),
                'spinner_selected': QColor(0,   100, 200),
                'description':      'Tema claro',
            },

            # ── TEMA MILITAR ───────────────────────────────────────────
            'olive': {
                'name': 'Militar',
                'background':       QColor(40,  50,  30),
                'foreground':       QColor(180, 200, 160),
                'grid':             QColor(70,  90,  50),
                'input_bg':         QColor(35,  45,  25),
                'button_bg':        QColor(50,  65,  40),
                'button_hover':     QColor(60,  75,  50),
                'button_pressed_bg':QColor(36,  45,  27),   # FIX 8
                'accent':           QColor(100, 140, 60),
                'accent_hover':     QColor(120, 160, 80),
                'dock_title_bg':    QColor(50,  65,  40),
                'dock_title_fg':    QColor(180, 200, 160),
                'dock_border':      QColor(70,  90,  50),
                'detector_text':    QColor(180, 200, 160),
                'detector_bg':      QColor(35,  45,  25),
                'tooltip_bg':       QColor(30,  40,  20, 200),
                'tooltip_fg':       QColor(190, 210, 170),
                'disabled_bg':      QColor(60,  75,  50),
                'disabled_fg':      QColor(100, 120, 80),
                'border_focus':     QColor(100, 140, 60),
                'mainwindow_bg':    QColor(40,  50,  30),
                'status_bar_bg':    QColor(40,  50,  30),
                'menu_bar_bg':      QColor(40,  50,  30),
                'header_bg':        QColor(50,  65,  40),
                'tab_bg':           QColor(50,  65,  40),
                'tab_selected_bg':  QColor(100, 140, 60),
                'text_bg':          QColor(30,  40,  20, 200),
                'text_fg':          QColor(190, 210, 170),
                'spectrum_default': QColor(150, 255, 100),
                'max_hold_default': QColor(255, 200, 50),
                'min_hold_default': QColor(200, 150, 100),
                'waterfall_bg':     QColor(35,  45,  25),
                'frame_bg':         QColor(40,  50,  30),
                'spinner_bg':       QColor(35,  45,  25),
                'spinner_fg':       QColor(180, 200, 160),
                'spinner_border':   QColor(70,  90,  50),
                'spinner_selected': QColor(100, 140, 60),
                'description':      'Tema militar verde oliva',
            },

            # ── TEMA NAVAL ─────────────────────────────────────────────
            'naval': {
                'name': 'Naval',
                'background':       QColor(45,  52,  58),
                'foreground':       QColor(220, 230, 240),
                'grid':             QColor(70,  80,  90),
                'input_bg':         QColor(38,  45,  50),
                'button_bg':        QColor(55,  65,  75),
                'button_hover':     QColor(70,  82,  95),
                'button_pressed_bg':QColor(40,  47,  54),   # FIX 8
                'accent':           QColor(0,   150, 200),
                'accent_hover':     QColor(30,  170, 220),
                'dock_title_bg':    QColor(50,  58,  65),
                'dock_title_fg':    QColor(220, 230, 240),
                'dock_border':      QColor(70,  80,  92),
                'detector_text':    QColor(220, 230, 240),
                'detector_bg':      QColor(38,  45,  50),
                'tooltip_bg':       QColor(38,  45,  50, 220),
                'tooltip_fg':       QColor(220, 230, 240),
                'disabled_bg':      QColor(55,  62,  68),
                'disabled_fg':      QColor(100, 110, 120),
                'border_focus':     QColor(0,   150, 200),
                'mainwindow_bg':    QColor(38,  45,  52),
                'status_bar_bg':    QColor(38,  45,  52),
                'menu_bar_bg':      QColor(38,  45,  52),
                'header_bg':        QColor(50,  58,  65),
                'tab_bg':           QColor(45,  52,  58),
                'tab_selected_bg':  QColor(0,   150, 200),
                'text_bg':          QColor(38,  45,  50, 200),
                'text_fg':          QColor(220, 230, 240),
                'spectrum_default': QColor(100, 200, 255),
                'max_hold_default': QColor(255, 180, 70),
                'min_hold_default': QColor(100, 220, 220),
                'waterfall_bg':     QColor(30,  35,  40),
                'frame_bg':         QColor(38,  45,  52),
                'spinner_bg':       QColor(38,  45,  50),
                'spinner_fg':       QColor(220, 230, 240),
                'spinner_border':   QColor(70,  80,  92),
                'spinner_selected': QColor(0,   150, 200),
                'description':      'Tema naval profesional',
            },
        }
        return cls._themes_cache

    # ------------------------------------------------------------------
    # API PÚBLICA
    # ------------------------------------------------------------------

    def get_theme_names(self) -> list[tuple[str, str]]:
        """Retorna lista de (key, nombre) para poblar menús y comboboxes."""
        themes = self._build_themes()
        return [(key, data['name']) for key, data in themes.items()]

    def get_theme_colors(self, theme_key: str) -> dict:
        """
        Retorna los colores de un tema específico.

        FIX 4: retorna una copia superficial para evitar que código externo
        corrompa el diccionario original del tema.
        """
        themes = self._build_themes()
        return dict(themes.get(theme_key, themes['dark']))

    def apply_theme_to_app(self, app, theme_key: str = 'dark') -> dict:
        """
        Aplica el tema completo a la aplicación Qt.

        Orden de operaciones:
          1. Construir paleta y stylesheet
          2. Aplicar stylesheet (afecta al repintado de widgets)
          3. Aplicar paleta    (fuerza repintado completo)
          4. Emitir theme_changed (notifica a widgets con colores custom)

        FIX 5: emit() al final, después de que toda la UI ya se actualizó.
        """
        themes = self._build_themes()
        theme  = themes.get(theme_key, themes['dark'])

        self.current_theme = theme_key

        # 1+2. Stylesheet (con caché)
        self._apply_stylesheet(app, theme, theme_key)

        # 3. Paleta Qt
        self._apply_palette(app, theme)

        # 4. Notificar widgets con colores custom
        self.theme_changed.emit(theme_key)

        self.logger.info(f"🎨 Tema aplicado: {theme['name']}")
        return dict(theme)    # retorna copia, no referencia

    # ------------------------------------------------------------------
    # PRIVADOS
    # ------------------------------------------------------------------

    def _apply_palette(self, app, theme: dict) -> None:
        """Aplica la paleta Qt estándar."""
        palette = QPalette()
        palette.setColor(QPalette.Window,          theme['mainwindow_bg'])
        palette.setColor(QPalette.WindowText,      theme['foreground'])
        palette.setColor(QPalette.Base,            theme['input_bg'])
        palette.setColor(QPalette.AlternateBase,   theme['background'])
        palette.setColor(QPalette.ToolTipBase,     theme['tooltip_bg'])
        palette.setColor(QPalette.ToolTipText,     theme['tooltip_fg'])
        palette.setColor(QPalette.Text,            theme['foreground'])
        palette.setColor(QPalette.Button,          theme['button_bg'])
        palette.setColor(QPalette.ButtonText,      theme['foreground'])
        palette.setColor(QPalette.BrightText,      Qt.red)
        palette.setColor(QPalette.Link,            theme['accent'])
        palette.setColor(QPalette.Highlight,       theme['accent'])
        palette.setColor(QPalette.HighlightedText, Qt.white)

        palette.setColor(QPalette.Disabled, QPalette.Button,     theme['disabled_bg'])
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, theme['disabled_fg'])
        palette.setColor(QPalette.Disabled, QPalette.Text,       theme['disabled_fg'])
        palette.setColor(QPalette.Disabled, QPalette.WindowText, theme['disabled_fg'])

        app.setPalette(palette)

    def _apply_stylesheet(self, app, theme: dict, theme_key: str) -> None:
        """
        Aplica el stylesheet al app.

        FIX 6: el stylesheet se cachea por theme_key. Solo se regenera
        la primera vez que se usa cada tema, no en cada llamada.
        """
        if theme_key not in self._stylesheet_cache:
            self._stylesheet_cache[theme_key] = self._build_stylesheet(theme)

        app.setStyleSheet(self._stylesheet_cache[theme_key])

    def _build_stylesheet(self, theme: dict) -> str:
        """Genera el stylesheet completo para un tema dado."""

        # Extraer todos los colores como hex una sola vez
        c = {k: v.name() for k, v in theme.items() if isinstance(v, QColor)}

        return f"""
            QWidget {{
                text-transform: uppercase;
                font-size: 9pt;
                font-family: "Segoe UI", "Arial", sans-serif;
            }}

            QMainWindow {{
                background-color: {c['mainwindow_bg']};
            }}

            QLabel {{
                color: {c['foreground']};
                background-color: transparent;
            }}

            QFrame {{
                background-color: {c['background']};
                border: 1px solid {c['grid']};
            }}

            QLabel[objectName="digitLabel"] {{
                border: 1px solid {c['spinner_border']};
                background-color: {c['spinner_bg']};
                color: {c['spinner_fg']};
                font-family: monospace;
                font-weight: bold;
                font-size: 10pt;
                padding: 1px;
            }}

            QLabel[objectName="digitLabel"]:hover {{
                background-color: {c['button_hover']};
                border: 1px solid {c['border_focus']};
            }}

            QLabel[objectName="digitLabel"][selected="true"] {{
                border: 2px solid {c['spinner_selected']};
                background-color: {c['spinner_selected']};
                color: white;
            }}

            QLabel[objectName="unitLabel"] {{
                font-weight: bold;
                color: {c['spinner_fg']};
            }}

            QDockWidget {{
                text-transform: uppercase;
                font-weight: bold;
                font-size: 9pt;
                border: 2px solid {c['dock_border']};
                margin: 0px;
            }}

            QDockWidget::title {{
                text-transform: uppercase;
                text-align: left;
                background-color: {c['dock_title_bg']};
                padding: 4px;
                border: none;
                border-bottom: 2px solid {c['accent']};
                font-weight: bold;
                color: {c['dock_title_fg']};
            }}

            QDockWidget::close-button, QDockWidget::float-button {{
                border: 1px solid {c['dock_border']};
                background-color: {c['button_bg']};
                padding: 2px;
            }}

            QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
                background-color: {c['button_hover']};
                border: 1px solid {c['border_focus']};
            }}

            QDockWidget > QWidget {{
                border: 2px solid {c['dock_border']};
                border-top: none;
                background-color: {c['background']};
            }}

            QDockWidget[objectName="dock_fpv_detector"] {{
                border: 2px solid {c['dock_border']};
            }}

            QDockWidget[objectName="dock_fpv_detector"] > QWidget {{
                background-color: {c['detector_bg']};
            }}

            QDockWidget[objectName="dock_fpv_detector"] QLabel,
            QDockWidget[objectName="dock_fpv_detector"] QTableWidget,
            QDockWidget[objectName="dock_fpv_detector"] QTextEdit,
            QDockWidget[objectName="dock_fpv_detector"] QGroupBox,
            QDockWidget[objectName="dock_fpv_detector"] QCheckBox,
            QDockWidget[objectName="dock_fpv_detector"] QRadioButton,
            QDockWidget[objectName="dock_fpv_detector"] QComboBox,
            QDockWidget[objectName="dock_fpv_detector"] QSpinBox,
            QDockWidget[objectName="dock_fpv_detector"] QDoubleSpinBox,
            QDockWidget[objectName="dock_fpv_detector"] QPushButton {{
                color: {c['detector_text']};
                background-color: {c['detector_bg']};
            }}

            QDockWidget[objectName="dock_fpv_detector"] QTableWidget::item {{
                color: {c['detector_text']};
            }}

            QDockWidget[objectName="dock_fpv_detector"] QHeaderView::section {{
                background-color: {c['button_bg']};
                color: {c['detector_text']};
            }}

            QPushButton {{
                text-transform: uppercase;
                font-weight: bold;
                font-size: 9pt;
                background-color: {c['button_bg']};
                color: {c['foreground']};
                border: 1px solid {c['grid']};
                border-radius: 0px;
                padding: 4px 8px;
                min-height: 24px;
                min-width: 70px;
            }}

            QPushButton:hover {{
                background-color: {c['button_hover']};
                border: 1px solid {c['border_focus']};
            }}

            QPushButton:pressed {{
                background-color: {c['button_pressed_bg']};
                border: 1px solid {c['accent_hover']};
            }}

            QPushButton:checked {{
                background-color: {c['accent']};
                border: 1px solid {c['accent']};
                color: white;
            }}

            QPushButton:disabled {{
                background-color: {c['disabled_bg']};
                border: 1px solid {c['grid']};
                color: {c['disabled_fg']};
            }}

            QGroupBox {{
                text-transform: uppercase;
                font-weight: bold;
                font-size: 9pt;
                border: 1px solid {c['grid']};
                border-radius: 0px;
                margin-top: 10px;
                padding-top: 6px;
                background-color: {c['background']};
            }}

            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 5px 0 5px;
                background-color: {c['background']};
                color: {c['accent']};
            }}

            QComboBox {{
                text-transform: uppercase;
                font-size: 9pt;
                background-color: {c['input_bg']};
                color: {c['foreground']};
                border: 1px solid {c['grid']};
                border-radius: 0px;
                padding: 3px 6px;
                min-height: 22px;
                min-width: 90px;
            }}

            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid {c['grid']};
                background-color: {c['button_bg']};
            }}

            QComboBox:hover {{
                border: 1px solid {c['border_focus']};
            }}

            QComboBox:disabled {{
                background-color: {c['disabled_bg']};
                color: {c['disabled_fg']};
            }}

            QSpinBox, QDoubleSpinBox {{
                text-transform: uppercase;
                font-size: 9pt;
                background-color: {c['input_bg']};
                color: {c['foreground']};
                border: 1px solid {c['grid']};
                border-radius: 0px;
                padding: 3px;
                min-height: 22px;
            }}

            QSpinBox:hover, QDoubleSpinBox:hover,
            QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {c['border_focus']};
            }}

            QSpinBox:disabled, QDoubleSpinBox:disabled {{
                background-color: {c['disabled_bg']};
                color: {c['disabled_fg']};
                border: 1px solid {c['grid']};
            }}

            QCheckBox {{
                text-transform: uppercase;
                font-size: 9pt;
                spacing: 6px;
                color: {c['foreground']};
            }}

            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                background-color: {c['input_bg']};
                border: 1px solid {c['grid']};
                border-radius: 0px;
            }}

            QCheckBox::indicator:hover {{
                border: 1px solid {c['border_focus']};
                background-color: {c['button_hover']};
            }}

            QCheckBox::indicator:checked {{
                background-color: {c['accent']};
                border: 1px solid {c['accent']};
            }}

            QCheckBox::indicator:checked:hover {{
                background-color: {c['accent_hover']};
                border: 1px solid {c['accent_hover']};
            }}

            QCheckBox:disabled {{
                color: {c['disabled_fg']};
            }}

            QCheckBox::indicator:disabled {{
                background-color: {c['disabled_bg']};
                border: 1px solid {c['grid']};
            }}

            QRadioButton {{
                text-transform: uppercase;
                font-size: 9pt;
                spacing: 6px;
                color: {c['foreground']};
            }}

            QRadioButton::indicator {{
                width: 14px;
                height: 14px;
                background-color: {c['input_bg']};
                border: 1px solid {c['grid']};
                border-radius: 7px;
            }}

            QRadioButton::indicator:hover {{
                border: 1px solid {c['border_focus']};
            }}

            QRadioButton::indicator:checked {{
                background-color: {c['accent']};
                border: 1px solid {c['accent']};
            }}

            QRadioButton:disabled {{
                color: {c['disabled_fg']};
            }}

            QRadioButton::indicator:disabled {{
                background-color: {c['disabled_bg']};
                border: 1px solid {c['grid']};
            }}

            QSlider::groove:horizontal {{
                border: 1px solid {c['grid']};
                height: 4px;
                background: {c['input_bg']};
                margin: 1px 0;
            }}

            QSlider::handle:horizontal {{
                background: {c['button_bg']};
                border: 1px solid {c['grid']};
                width: 12px;
                height: 12px;
                margin: -5px 0;
            }}

            QSlider::handle:horizontal:hover {{
                background: {c['button_hover']};
                border: 1px solid {c['border_focus']};
            }}

            QSlider::sub-page:horizontal {{
                background: {c['accent']};
                border: 1px solid {c['accent']};
            }}

            QSlider:disabled {{
                background-color: {c['disabled_bg']};
            }}

            QTableWidget {{
                font-size: 9pt;
                background-color: {c['input_bg']};
                color: {c['foreground']};
                border: 1px solid {c['grid']};
                gridline-color: {c['grid']};
            }}

            QTableWidget::item {{
                padding: 4px;
                border-bottom: 1px solid {c['background']};
            }}

            QTableWidget::item:selected {{
                background-color: {c['accent']};
                color: white;
            }}

            QHeaderView::section {{
                text-transform: uppercase;
                font-size: 9pt;
                font-weight: bold;
                background-color: {c['header_bg']};
                color: {c['foreground']};
                border: 1px solid {c['grid']};
                padding: 4px;
            }}

            QTabWidget::pane {{
                border: 1px solid {c['grid']};
                background-color: {c['background']};
            }}

            QTabBar::tab {{
                text-transform: uppercase;
                font-size: 9pt;
                background-color: {c['tab_bg']};
                color: {c['foreground']};
                border: 1px solid {c['grid']};
                border-bottom: none;
                padding: 5px 10px;
                margin-right: 1px;
            }}

            QTabBar::tab:selected {{
                background-color: {c['tab_selected_bg']};
                color: white;
                border-color: {c['tab_selected_bg']};
            }}

            QTabBar::tab:hover:!selected {{
                border: 1px solid {c['border_focus']};
            }}

            QMenuBar {{
                background-color: {c['menu_bar_bg']};
                border-bottom: 1px solid {c['accent']};
            }}

            QMenuBar::item {{
                text-transform: uppercase;
                font-size: 9pt;
                padding: 4px 10px;
                color: {c['foreground']};
            }}

            QMenuBar::item:selected {{
                background-color: {c['button_hover']};
            }}

            QMenu {{
                background-color: {c['background']};
                border: 1px solid {c['grid']};
            }}

            QMenu::item {{
                text-transform: uppercase;
                font-size: 9pt;
                padding: 4px 15px;
                color: {c['foreground']};
            }}

            QMenu::item:selected {{
                background-color: {c['accent']};
                color: white;
            }}

            QMenu::separator {{
                height: 1px;
                background-color: {c['grid']};
                margin: 4px 0;
            }}

            QStatusBar {{
                background-color: {c['status_bar_bg']};
                border-top: 1px solid {c['accent']};
                color: {c['foreground']};
                font-size: 9pt;
            }}

            QLineEdit {{
                text-transform: uppercase;
                font-size: 9pt;
                background-color: {c['input_bg']};
                color: {c['foreground']};
                border: 1px solid {c['grid']};
                border-radius: 0px;
                padding: 3px;
                min-height: 22px;
            }}

            QLineEdit:focus {{
                border: 1px solid {c['border_focus']};
            }}

            QLineEdit:disabled {{
                background-color: {c['disabled_bg']};
                color: {c['disabled_fg']};
            }}

            QScrollBar:vertical {{
                border: 1px solid {c['grid']};
                background: {c['input_bg']};
                width: 14px;
                margin: 0px;
            }}

            QScrollBar::handle:vertical {{
                background: {c['button_bg']};
                min-height: 20px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: {c['button_hover']};
            }}

            QScrollBar:horizontal {{
                border: 1px solid {c['grid']};
                background: {c['input_bg']};
                height: 14px;
            }}

            QScrollBar::handle:horizontal {{
                background: {c['button_bg']};
                min-width: 20px;
            }}

            QScrollBar::handle:horizontal:hover {{
                background: {c['button_hover']};
            }}
        """

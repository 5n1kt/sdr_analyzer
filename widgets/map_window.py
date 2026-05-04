# -*- coding: utf-8 -*-

"""
Map Window - Ventana de Mapa Táctico Desacoplable
==================================================
"""

import logging
from datetime import datetime
from PyQt5.QtWidgets import QDesktopWidget, QMainWindow
from PyQt5.QtCore import QTimer
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.uic import loadUi


class MapWindow(QMainWindow):
    
    def __init__(self, parent=None, station_id="EST-001"):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.station_id = station_id
        self.gps_data = None
        self.map_view = None
        
        # Cargar UI
        loadUi('ui/map_window.ui', self)

        # ===== APLICAR TEMA =====
        if parent and hasattr(parent, 'theme_manager'):
            # Heredar tema del dock padre
            theme = parent.theme_manager.get_theme_colors(parent.theme_manager.current_theme)
            self._apply_theme(theme)
        # ========================
        
        # Configurar UI
        self._setup_ui()
        self._setup_map()
        self._setup_clock()
        self._setup_connections()
        
        # Posicionar en segundo monitor si existe
        self._position_on_second_screen()
        
        self.logger.info(f"🗺️ MapWindow creada para {station_id}")
    
    def _setup_ui(self):
        """Configura elementos de la UI."""
        self.label_station_id.setText(self.station_id)
        self.setWindowTitle(f"🗺️ MAPA TÁCTICO - {self.station_id}")
    
    def _setup_map(self):
        """Inicializa el QWebEngineView en el frame del mapa."""
        self.map_view = QWebEngineView()
        self.verticalLayout_map.addWidget(self.map_view)
    
    def _setup_clock(self):
        """Timer para actualizar hora."""
        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)
    
    def _setup_connections(self):
        """Conecta señales de la barra de herramientas."""
        self.pushButton_center.clicked.connect(self._on_center)
        self.pushButton_zoom_in.clicked.connect(self._on_zoom_in)
        self.pushButton_zoom_out.clicked.connect(self._on_zoom_out)
        self.pushButton_measure.toggled.connect(self._on_measure)
        self.pushButton_add_marker.clicked.connect(self._on_add_marker)
        self.comboBox_map_layer.currentIndexChanged.connect(self._on_layer_changed)
    
    def _update_clock(self):
        self.label_time.setText(datetime.now().strftime("%H:%M:%S"))
    
    def _position_on_second_screen(self):
        """Posiciona en segundo monitor si existe."""
        desktop = QDesktopWidget()
        if desktop.screenCount() > 1:
            screen_geo = desktop.screenGeometry(1)
            self.move(screen_geo.x() + 100, screen_geo.y() + 100)
    
    # ------------------------------------------------------------------------
    # MAPA
    # ------------------------------------------------------------------------
    
    def load_map(self, lat=19.4326, lon=-99.1332, zoom=15):
        """Carga el mapa Leaflet."""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8"/>
        <style>
          body {{ margin: 0; background: #0d1218; }}
          #map {{ width: 100%; height: 100vh; cursor: crosshair; }}
        </style>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        </head>
        <body>
        <div id="map"></div>
        <script>
          var map = L.map('map', {{zoomControl: false}}).setView([{lat}, {lon}], {zoom});
          L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{maxZoom: 19}}).addTo(map);
          var marker = L.marker([{lat}, {lon}]).addTo(map);
          marker.bindTooltip("{self.station_id}", {{permanent: true, direction: 'top'}});
          
          map.on('mousemove', function(e) {{
              window.py_cursor_pos(e.latlng.lat.toFixed(6), e.latlng.lng.toFixed(6));
          }});
          
          function updatePosition(lat, lon, z) {{
              map.setView([lat, lon], z || {zoom});
              marker.setLatLng([lat, lon]);
          }}
          function zoomIn() {{ map.zoomIn(); }}
          function zoomOut() {{ map.zoomOut(); }}
        </script>
        </body>
        </html>
        """
        self.map_view.setHtml(html)
    
    # ------------------------------------------------------------------------
    # SLOTS DE HERRAMIENTAS
    # ------------------------------------------------------------------------
    
    def _on_center(self):
        if self.gps_data:
            self.update_position(self.gps_data['lat'], self.gps_data['lon'])
    
    def _on_zoom_in(self):
        self.map_view.page().runJavaScript("zoomIn();")
    
    def _on_zoom_out(self):
        self.map_view.page().runJavaScript("zoomOut();")
    
    def _on_measure(self, checked):
        if checked:
            self.logger.info("📏 Modo medición activado")
            # TODO: Implementar medición de distancia
        else:
            self.logger.info("📏 Modo medición desactivado")
    
    def _on_add_marker(self):
        self.logger.info("📍 Añadiendo marcador")
        # TODO: Implementar añadir marcador
    
    def _on_layer_changed(self, index):
        self.logger.info(f"🗺️ Capa cambiada: {self.comboBox_map_layer.currentText()}")
        # TODO: Cambiar capa del mapa
    
    # ------------------------------------------------------------------------
    # ACTUALIZACIÓN DESDE EL DOCK
    # ------------------------------------------------------------------------
    
    def update_cursor_position(self, lat_str: str, lon_str: str):
        try:
            lat = float(lat_str)
            lon = float(lon_str)
            self.label_cursor.setText(f"🖱️ {lat:.6f}, {lon:.6f}")
        except (ValueError, TypeError):
            pass
    
    def update_gps_info(self, gps_data: dict):
        self.gps_data = gps_data
        fix = gps_data.get('fix', 0)
        fix_emoji = {0: '🔴', 1: '🟡', 2: '🟢', 3: '🟢'}
        fix_text = {0: 'NO', 1: '1D', 2: '2D', 3: '3D'}
        self.label_fix.setText(f"{fix_emoji.get(fix, '⚪')} {fix_text.get(fix, '?')}")
        self.label_sats.setText(f"{gps_data.get('sats', 0)} sat")
        self.label_prec.setText(f"{gps_data.get('precision', 0):.1f} m")
        self.label_alt.setText(f"{gps_data.get('alt', 0):.1f} m")
    
    def update_position(self, lat: float, lon: float, zoom: int = 15):
        js = f"updatePosition({lat}, {lon}, {zoom});"
        self.map_view.page().runJavaScript(js)
    
    def closeEvent(self, event):
        self.clock_timer.stop()
        self.logger.info("🗺️ MapWindow cerrada")
        event.accept()


    def _apply_theme(self, theme: dict):
        """Aplica colores del tema a los elementos personalizados."""
        # Toolbar
        self.widget_map_toolbar.setStyleSheet(
            f"background: {theme['background'].name()}; "
            f"border-bottom: 1px solid {theme['accent'].name()};"
        )
        
        # Label estación
        self.label_station_id.setStyleSheet(
            f"font-weight: bold; color: {theme['accent'].name()}; font-size: 10pt;"
        )
        
        # Separadores
        sep_style = f"background: {theme['grid'].name()};"
        self.frame_toolbar_sep_1.setStyleSheet(sep_style)
        self.frame_toolbar_sep_2.setStyleSheet(sep_style)
        
        # Barra de estado
        self.frame_status_bar.setStyleSheet(
            f"background: {theme['background'].name()}; "
            f"border-top: 1px solid {theme['dock_border'].name()};"
        )
        
        # Cursor
        self.label_cursor.setStyleSheet(
            f"color: {theme['accent'].name()}; font-family: monospace; font-size: 9pt;"
        )
        
        # Labels de estado
        label_style = f"color: {theme['foreground'].name()}; font-size: 9pt;"
        for label in [self.label_fix, self.label_sats, self.label_prec, 
                      self.label_time, self.label_alt]:
            label.setStyleSheet(label_style)
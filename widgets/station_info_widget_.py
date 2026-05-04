# -*- coding: utf-8 -*-

"""
Station Info Widget con Mapa Integrado
========================================
Panel plegable con ID, hora, posición GPS y mapa cuadrado.
"""

import logging
from datetime import datetime, timezone
from PyQt5.QtWidgets import QDockWidget, QVBoxLayout, QPushButton, QWidget, QHBoxLayout, QLabel
from PyQt5.QtCore import QTimer, Qt, QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.uic import loadUi


class StationInfoWidget(QDockWidget):
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        loadUi('ui/station_info_widget.ui', self)
        
        # Estado
        self.station_id = "EST-001"
        self.expanded = False
        self.gps_data = None
        
        # Mapa
        self.map_view = None
        self._setup_map()
        
        # Timer para actualizar hora
        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)
        
        # Configurar UI
        self._setup_ui()
        self._update_clock()

        # Botón de toggle en el título
        self.toggle_btn = QPushButton("▼")
        self.toggle_btn.setFixedSize(24, 24)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #aaa;
                font-weight: bold;
                font-size: 10pt;
            }
            QPushButton:hover {
                color: #fff;
                background: #333;
            }
        """)
        self.toggle_btn.clicked.connect(self.toggle_details)
        
        # Añadir al title bar widget
        # Accedemos al title bar del QDockWidget
        title_bar = self.findChild(QWidget, 'qt_dockwidget_title')
        if title_bar and title_bar.layout():
            title_bar.layout().addWidget(self.toggle_btn)
        else:
            # Alternativa: usar setTitleBarWidget
            self._setup_custom_title()
        
        self.logger.info("✅ StationInfoWidget con mapa inicializado")
    
    def _setup_ui(self):
        self.widget_details.setVisible(False)
        self.label_id.setText(self.station_id)


    def _setup_custom_title(self):
        """Crea una barra de título personalizada con botón de toggle."""
        #from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
        
        title_widget = QWidget()
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(8, 2, 4, 2)
        title_layout.setSpacing(4)
        
        label = QLabel("ESTACIÓN")
        label.setStyleSheet("font-weight: bold; color: #aaa;")
        title_layout.addWidget(label)
        title_layout.addStretch()
        title_layout.addWidget(self.toggle_btn)
        
        self.setTitleBarWidget(title_widget)
    
    def _setup_map(self):
        """Inicializa el mapa (Leaflet offline o OpenStreetMap)."""
        self.map_view = QWebEngineView()
        self.map_view.setMinimumSize(200, 200)
        
        # HTML simple con Leaflet
        html = """
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
          body { margin: 0; background: #0d1218; }
          #map { width: 100%; height: 100vh; }
        </style>
        </head>
        <body>
        <div id="map"></div>
        <script>
          var map = L.map('map', {zoomControl: true, attributionControl: false}).setView([0, 0], 2);
          L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
              maxZoom: 19
          }).addTo(map);
          var marker = L.marker([0, 0]).addTo(map);
          
          function updatePosition(lat, lon, zoom) {
              map.setView([lat, lon], zoom || 15);
              marker.setLatLng([lat, lon]);
          }
        </script>
        </body>
        </html>
        """
        
        self.map_view.setHtml(html)
        
        # Añadir al frame del mapa
        layout = self.frame_map.layout()
        if layout is None:
            layout = QVBoxLayout(self.frame_map)
            layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.map_view)
    
    # ------------------------------------------------------------------------
    # RELOJ
    # ------------------------------------------------------------------------
    
    def _update_clock(self):
        now = datetime.now()
        utc = datetime.now(timezone.utc)
        
        if self.gps_data:
            lat_str = f"{self.gps_data.get('lat', 0):.4f}"
            lon_str = f"{self.gps_data.get('lon', 0):.4f}"
        else:
            lat_str = "--"
            lon_str = "--"
        
        self.label_header_info.setText(f"{now.strftime('%H:%M')} | {lat_str}, {lon_str}")
        self.label_local_time.setText(now.strftime("%H:%M:%S"))
        self.label_utc_time.setText(utc.strftime("%H:%M:%S"))
        self.label_date.setText(now.strftime("%Y-%m-%d"))
    
    # ------------------------------------------------------------------------
    # GPS + MAPA
    # ------------------------------------------------------------------------
    
    def update_gps(self, data: dict):
        """Actualiza datos GPS y mueve el marcador del mapa."""
        self.gps_data = data
        
        lat = data.get('lat', 0)
        lon = data.get('lon', 0)
        
        self.label_lat.setText(f"{lat:.6f}°")
        self.label_lon.setText(f"{lon:.6f}°")
        self.label_alt.setText(f"{data.get('alt', 0):.1f} m")
        
        # GPS status
        fix = data.get('fix', 0)
        fix_emoji = {0: '🔴', 1: '🟡', 2: '🟢', 3: '🟢'}
        self.label_gps_status.setText(
            f"{fix_emoji.get(fix, '⚪')} Fix: {fix}D | "
            f"Sats: {data.get('sats', 0)} | Prec: {data.get('precision', 0):.1f} m"
        )
        
        # Actualizar mapa
        if lat != 0 or lon != 0:
            self._update_map_position(lat, lon)
        
        self._update_clock()
    
    def _update_map_position(self, lat: float, lon: float):
        """Actualiza la posición del marcador en el mapa."""
        if self.map_view:
            js = f"updatePosition({lat}, {lon}, 15);"
            self.map_view.page().runJavaScript(js)
    
    # ------------------------------------------------------------------------
    # ID ESTACIÓN
    # ------------------------------------------------------------------------
    
    def set_station_id(self, station_id: str):
        self.station_id = station_id
        self.label_id.setText(station_id)
    
    def get_station_id(self) -> str:
        return self.station_id
    
    # ------------------------------------------------------------------------
    # EXPANDIR/COLAPSAR
    # ------------------------------------------------------------------------
    
    def toggle_details(self):
        self.expanded = not self.expanded
        self.widget_details.setVisible(self.expanded)
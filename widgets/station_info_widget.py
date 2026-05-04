# -*- coding: utf-8 -*-

"""
Station Info Widget - Información de Estación con Mapa Desacoplable
====================================================================
Panel plegable con ID, hora, posición GPS y mapa.
Soporta expansión en el mismo dock y desacople a ventana independiente.
"""

import logging
from datetime import datetime, timezone
from PyQt5.QtWidgets import (QDockWidget, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QFrame, QDesktopWidget,
                             QSizePolicy)
from PyQt5.QtCore import QTimer, Qt, QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.uic import loadUi


class MapWindow(QMainWindow):
    """Ventana independiente para el mapa táctico."""
    
    def __init__(self, parent=None, station_id="EST-001"):
        super().__init__(parent)
        self.station_id = station_id
        self.setWindowTitle(f"🗺️ MAPA TÁCTICO - {station_id}")
        self.setMinimumSize(800, 600)
        
        # Widget central
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Mapa grande
        self.map_view = QWebEngineView()
        self.map_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.map_view, stretch=1)
        
        # Barra inferior
        self.status_bar = QFrame()
        self.status_bar.setMaximumHeight(28)
        self.status_bar.setStyleSheet(
            "QFrame { background: #1a1e24; border-top: 1px solid #2a3a4a; }"
        )
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(10, 2, 10, 2)
        status_layout.setSpacing(12)
        
        self.label_cursor = QLabel("🖱️ ---, ---")
        self.label_cursor.setStyleSheet("color: #00aaff; font-family: monospace; font-size: 9pt;")
        self.label_cursor.setMinimumWidth(220)
        status_layout.addWidget(self.label_cursor)
        
        status_layout.addStretch()
        
        self.label_fix = QLabel("---")
        self.label_fix.setStyleSheet("color: #aaa; font-size: 9pt;")
        status_layout.addWidget(self.label_fix)
        
        self.label_sats = QLabel("0 sat")
        self.label_sats.setStyleSheet("color: #aaa; font-size: 9pt;")
        status_layout.addWidget(self.label_sats)
        
        self.label_prec = QLabel("---")
        self.label_prec.setStyleSheet("color: #aaa; font-size: 9pt;")
        status_layout.addWidget(self.label_prec)
        
        self.label_time = QLabel("--:--:--")
        self.label_time.setStyleSheet("color: #aaa; font-size: 9pt;")
        status_layout.addWidget(self.label_time)
        
        self.label_alt = QLabel("---")
        self.label_alt.setStyleSheet("color: #aaa; font-size: 9pt;")
        status_layout.addWidget(self.label_alt)
        
        layout.addWidget(self.status_bar)
        
        # Timer para hora
        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)
    
    def _update_clock(self):
        self.label_time.setText(datetime.now().strftime("%H:%M:%S"))
    
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
          var map = L.map('map', {{zoomControl: true, attributionControl: false}}).setView([{lat}, {lon}], {zoom});
          L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom: 19}}).addTo(map);
          var marker = L.marker([{lat}, {lon}]).addTo(map);
          marker.bindTooltip("EST-001", {{permanent: true, direction: 'top'}});
          
          map.on('mousemove', function(e) {{
              window.py_cursor_pos(e.latlng.lat.toFixed(6), e.latlng.lng.toFixed(6));
          }});
          
          function updatePosition(lat, lon, z) {{
              map.setView([lat, lon], z || {zoom});
              marker.setLatLng([lat, lon]);
          }}
        </script>
        </body>
        </html>
        """
        self.map_view.setHtml(html)
        self.map_view.loadFinished.connect(self._on_map_loaded)
    
    def _on_map_loaded(self):
        """Conecta el evento de movimiento del mouse."""
        self.map_view.page().runJavaScript("""
            map.on('mousemove', function(e) {
                window.py_cursor_pos(e.latlng.lat.toFixed(6), e.latlng.lng.toFixed(6));
            });
        """)
    
    def update_cursor_position(self, lat_str: str, lon_str: str):
        """Actualiza la etiqueta de posición del cursor."""
        try:
            lat = float(lat_str)
            lon = float(lon_str)
            self.label_cursor.setText(f"🖱️ {lat:.6f}, {lon:.6f}")
        except ValueError:
            pass
    
    def update_gps_info(self, gps_data: dict):
        """Actualiza barra inferior con datos GPS."""
        fix = gps_data.get('fix', 0)
        fix_emoji = {0: '🔴', 1: '🟡', 2: '🟢', 3: '🟢'}
        fix_text = {0: 'NO', 1: '1D', 2: '2D', 3: '3D'}
        
        self.label_fix.setText(f"{fix_emoji.get(fix, '⚪')} {fix_text.get(fix, '?')}")
        self.label_sats.setText(f"{gps_data.get('sats', 0)} sat")
        self.label_prec.setText(f"{gps_data.get('precision', 0):.1f} m")
        self.label_alt.setText(f"{gps_data.get('alt', 0):.1f} m")
    
    def update_position(self, lat: float, lon: float, zoom: int = 15):
        """Mueve el marcador del mapa."""
        js = f"updatePosition({lat}, {lon}, {zoom});"
        self.map_view.page().runJavaScript(js)
    
    def closeEvent(self, event):
        self.clock_timer.stop()
        event.accept()


# ============================================================================
# WIDGET PRINCIPAL
# ============================================================================

class StationInfoWidget(QDockWidget):
    """Widget de información de estación con mapa desacoplable."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        loadUi('ui/station_info_widget.ui', self)
        
        # Estado
        self.station_id = "EST-001"
        self.expanded = False
        self.gps_data = None
        self.map_window = None
        self.compact_map_view = None
        self.expanded_size = None      
        self.collapsed_size = None    

        # Timer para hora
        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)
        
        # Configurar UI
        self._setup_ui()
        self._setup_maps()
        self._update_clock()
        
        # GPS demo al iniciar
        self._set_demo_gps()
        
        self.logger.info("✅ StationInfoWidget inicializado")
    
    def _setup_ui(self):
        """Configura el estado inicial."""
        self.widget_details.setVisible(False)
        self.label_id.setText(self.station_id)
        
        # Conectar botones
        self.pushButton_toggle.clicked.connect(self.toggle_details)
        self.pushButton_detach.clicked.connect(self.toggle_map_window)
        self.pushButton_gps_update.clicked.connect(self._on_gps_update)
        self.pushButton_manual_pos.clicked.connect(self._on_manual_pos)
    
    def _setup_maps(self):
        """Inicializa ambos mapas (compacto y desacoplado)."""
        # Placeholder para mapa compacto
        placeholder = QLabel("🗺️\nMapa no disponible")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #555; font-size: 12pt;")
        self.verticalLayout_map_compact.addWidget(placeholder)
        
        # El mapa compacto se carga la primera vez que se expande
        self.compact_map_loaded = False
    
    def _load_compact_map(self):
        """Carga el mapa compacto en el dock."""
        if self.compact_map_loaded:
            return
        
        # Limpiar placeholder
        layout = self.frame_map_compact.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Crear mapa compacto
        self.compact_map_view = QWebEngineView()
        layout.addWidget(self.compact_map_view)
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8"/>
        <style>
          body {{ margin: 0; background: #0d1218; }}
          #map {{ width: 100%; height: 100vh; }}
        </style>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        </head>
        <body>
        <div id="map"></div>
        <script>
          var map = L.map('map', {{zoomControl: false, attributionControl: false}}).setView([19.4326, -99.1332], 14);
          L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom: 19}}).addTo(map);
          var marker = L.marker([19.4326, -99.1332]).addTo(map);
          
          function updatePosition(lat, lon, z) {{
              map.setView([lat, lon], z || 14);
              marker.setLatLng([lat, lon]);
          }}
        </script>
        </body>
        </html>
        """
        self.compact_map_view.setHtml(html)
        self.compact_map_loaded = True
        self.logger.info("🗺️ Mapa compacto cargado")
    
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
    # GPS
    # ------------------------------------------------------------------------
    
    def _set_demo_gps(self):
        """GPS de demostración."""
        demo = {
            'lat': 19.432600, 'lon': -99.133200, 'alt': 2240.5,
            'fix': 3, 'sats': 12, 'precision': 2.5
        }
        self.update_gps(demo)
    
    def update_gps(self, data: dict):
        """Actualiza datos GPS."""
        self.gps_data = data
        lat = data.get('lat', 0)
        lon = data.get('lon', 0)
        
        self.label_lat.setText(f"{lat:.6f}°")
        self.label_lon.setText(f"{lon:.6f}°")
        self.label_alt.setText(f"{data.get('alt', 0):.1f} m")
        
        fix = data.get('fix', 0)
        fix_emoji = {0: '🔴', 1: '🟡', 2: '🟢', 3: '🟢'}
        self.label_gps_status.setText(
            f"{fix_emoji.get(fix, '⚪')} Fix: {fix}D | "
            f"Sats: {data.get('sats', 0)} | Prec: {data.get('precision', 0):.1f} m"
        )
        
        # Actualizar mapas si existen
        if lat != 0 or lon != 0:
            self._update_map_positions(lat, lon)
        
        # Ventana desacoplada
        if self.map_window and self.map_window.isVisible():
            self.map_window.update_gps_info(data)
            self.map_window.update_position(lat, lon)
        
        self._update_clock()
    
    def _update_map_positions(self, lat: float, lon: float):
        """Actualiza posición en mapas."""
        js = f"updatePosition({lat}, {lon});"
        if self.compact_map_view:
            self.compact_map_view.page().runJavaScript(js)
    
    def _on_gps_update(self):
        """Fuerza actualización GPS."""
        self.logger.info("📍 Actualización GPS solicitada")
        self._set_demo_gps()
    
    def _on_manual_pos(self):
        """Abre diálogo para ingresar posición manual."""
        self.logger.info("✏️ Posición manual solicitada")
        # TODO: Implementar diálogo de entrada manual
    
    # ------------------------------------------------------------------------
    # EXPANDIR/COLAPSAR
    # ------------------------------------------------------------------------
    
    '''def toggle_details(self):
        """Expande/colapsa los detalles."""
        self.expanded = not self.expanded
        self.widget_details.setVisible(self.expanded)
        self.pushButton_toggle.setText("▲" if self.expanded else "▼")
        
        # Cargar mapa compacto al expandir por primera vez
        if self.expanded and not self.compact_map_loaded:
            self._load_compact_map()'''


    def toggle_details(self):
        """Expande/colapsa los detalles con restauración de tamaño."""
        self.expanded = not self.expanded
        
        if self.expanded:
            # Guardar tamaño actual antes de expandir
            self.collapsed_size = self.size()
            
            # Mostrar detalles
            self.widget_details.setVisible(True)
            self.pushButton_toggle.setText("▲")
            
            # Restaurar tamaño expandido guardado o usar default
            if self.expanded_size:
                self.resize(self.expanded_size)
            else:
                self.resize(self.width(), 650)
            
            # Cargar mapa compacto al expandir por primera vez
            if not self.compact_map_loaded:
                self._load_compact_map()
        else:
            # Guardar tamaño expandido para restaurar después
            self.expanded_size = self.size()
            
            # Ocultar detalles
            self.widget_details.setVisible(False)
            self.pushButton_toggle.setText("▼")
            
            # Volver al tamaño compacto
            if hasattr(self, 'collapsed_size'):
                self.resize(self.collapsed_size)
            else:
                self.resize(self.width(), 70)
        
        # Forzar actualización del layout
        self.updateGeometry()
    
    # ------------------------------------------------------------------------
    # VENTANA DESACOPLADA
    # ------------------------------------------------------------------------
    
    def toggle_map_window(self):
        """Abre/cierra la ventana de mapa desacoplado."""
        if self.map_window and self.map_window.isVisible():
            self.map_window.close()
            self.map_window = None
            self.logger.info("🗺️ Mapa desacoplado cerrado")
        else:
            self._open_map_window()
    
    def _open_map_window(self):
        """Abre el mapa en ventana independiente."""
        self.map_window = MapWindow(self, self.station_id)
        
        # Cargar mapa
        lat = self.gps_data.get('lat', 19.4326) if self.gps_data else 19.4326
        lon = self.gps_data.get('lon', -99.1332) if self.gps_data else -99.1332
        self.map_window.load_map(lat, lon)
        
        # Conectar señal de posición del cursor
        self.map_window.map_view.page().loadFinished.connect(
            lambda: self._connect_cursor_signal()
        )
        
        # Actualizar datos GPS
        if self.gps_data:
            self.map_window.update_gps_info(self.gps_data)
        
        self.map_window.show()
        self.logger.info("🗺️ Mapa desacoplado abierto")
    
    def _connect_cursor_signal(self):
        """Conecta la señal de posición del cursor."""
        if self.map_window:
            self.map_window.map_view.page().runJavaScript("""
                map.on('mousemove', function(e) {
                    window.py_cursor_pos(e.latlng.lat.toFixed(6), e.latlng.lng.toFixed(6));
                });
            """)
    
    # ------------------------------------------------------------------------
    # ID ESTACIÓN
    # ------------------------------------------------------------------------
    
    def set_station_id(self, station_id: str):
        self.station_id = station_id
        self.label_id.setText(station_id)
    
    def get_station_id(self) -> str:
        return self.lineEdit_name.text() or self.station_id
    
    # ------------------------------------------------------------------------
    # CIERRE
    # ------------------------------------------------------------------------
    
    def closeEvent(self, event):
        self.clock_timer.stop()
        if self.map_window:
            self.map_window.close()
        event.accept()
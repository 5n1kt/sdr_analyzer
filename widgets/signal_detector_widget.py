# widgets/signal_detector_widget.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
from PyQt5.QtWidgets import (QDockWidget, QFileDialog, QTableWidgetItem, 
                             QHeaderView, QDialog, QVBoxLayout, QHBoxLayout,
                             QCheckBox, QDialogButtonBox, QGroupBox, QLabel,
                             QMenu, QAction, QApplication)
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QColor  # <-- AÑADIR ESTA LÍNEA
from PyQt5.uic import loadUi
import logging
import csv
import time
from datetime import datetime

from utils.band_manager import BandManager

# =======================================================================
# DIÁLOGO DE FILTRO
# =======================================================================
class FilterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filtrar Detecciones")
        self.setModal(True)
        self.setMinimumWidth(300)
        
        layout = QVBoxLayout(self)
        
        group = QGroupBox("Mostrar tipos de señal:")
        group_layout = QVBoxLayout(group)
        
        self.check_narrow = QCheckBox("📻 Narrow (10-200 kHz)")
        self.check_narrow.setChecked(True)
        self.check_medium = QCheckBox("📺 Medium (200-2000 kHz)")
        self.check_medium.setChecked(True)
        self.check_wide = QCheckBox("📡 Wide (2-10 MHz)")
        self.check_wide.setChecked(True)
        self.check_unknown = QCheckBox("❓ Desconocido")
        self.check_unknown.setChecked(True)
        
        group_layout.addWidget(self.check_narrow)
        group_layout.addWidget(self.check_medium)
        group_layout.addWidget(self.check_wide)
        group_layout.addWidget(self.check_unknown)
        
        layout.addWidget(group)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # ===== NUEVO: Conectar nuevos controles =====
        self.checkBox_show_threshold.toggled.connect(self.on_show_threshold_toggled)
        self.checkBox_show_noise.toggled.connect(self.on_show_noise_toggled)
        self.pushButton_sync_values.clicked.connect(self.on_sync_values)
        
        # ===== NUEVO: Estado de visualización =====
        self.show_threshold = True
        self.show_noise = True
        self.current_threshold = -80.0
        self.current_noise = -95.0
        
        # ===== NUEVO: Timer para actualizar valores =====
        self.value_update_timer = QTimer()
        self.value_update_timer.timeout.connect(self.request_values_update)
        self.value_update_timer.start(1000)  # Cada segundo
    
    def get_filters(self):
        return {
            'narrow': self.check_narrow.isChecked(),
            'medium': self.check_medium.isChecked(),
            'wide': self.check_wide.isChecked(),
            'unknown': self.check_unknown.isChecked()
        }


# =======================================================================
# WIDGET DE DETECTOR DE SEÑALES
# =======================================================================
class SignalDetectorWidget(QDockWidget):
    """
    Widget para detector de señales multi-banda.
    Soporta bandas desde 70 MHz hasta 6 GHz (rango del BladeRF).
    """
    
    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    scan_started = pyqtSignal(dict)
    scan_stopped = pyqtSignal()
    scan_paused = pyqtSignal()
    scan_resumed = pyqtSignal()
    frequency_selected = pyqtSignal(float)

    scan_config_updated = pyqtSignal(dict)  # Para actualizaciones de configuración
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # Cargar UI
        loadUi('ui/signal_detector_widget.ui', self)
        
        # ===== INICIALIZAR GESTOR DE BANDAS =====
        self.band_manager = BandManager()
        
        # ===== ESTADO =====
        self.is_scanning = False
        self.is_paused = False
        self.detections = []
        self.current_filters = {
            'narrow': True,
            'medium': True,
            'wide': True,
            'unknown': True
        }
        self.current_band = None  # Banda actual (objeto completo)
        self.current_band_frequencies = []  # Frecuencias de la banda actual
        self._theme_manager = None

        # ===== NUEVO: Estado de visualización =====
        self.show_threshold = True
        self.show_noise = True
        self.current_threshold = -80.0
        self.current_noise = -95.0
        
        # ===== NUEVO: Timer para actualizar valores =====
        self.value_update_timer = QTimer()
        self.value_update_timer.timeout.connect(self.request_values_update)
        self.value_update_timer.start(1000)  # Cada segundo
        
        # ===== CONECTAR AL THEME MANAGER =====
        self._find_theme_manager(parent)
        if self._theme_manager:
            self.logger.info("🔗 SignalDetectorWidget conectado al theme_manager")
            self._theme_manager.theme_changed.connect(self.on_theme_changed)
            
            # Aplicar colores iniciales
            current_theme = self._theme_manager.current_theme
            self.on_theme_changed(current_theme)
        else:
            self.logger.warning("⚠️ No se encontró theme_manager")
        
        # ===== CONFIGURAR UI =====
        self.setup_ui()
        self.setup_connections()
        self.setup_band_selector()
        self.setup_detection_selection()
        
        self.logger.info("✅ SignalDetectorWidget creado")
    
    def _find_theme_manager(self, widget):
        """Busca recursivamente el theme_manager en la jerarquía de padres."""
        current = widget
        while current:
            if hasattr(current, 'theme_manager'):
                self._theme_manager = current.theme_manager
                self.logger.info(f"✅ ThemeManager encontrado en {current.__class__.__name__}")
                return True
            current = current.parent()
        return False
    
    def on_theme_changed(self, theme_key):
        """Actualiza los colores cuando cambia el tema."""
        if not self._theme_manager:
            return
        
        theme = self._theme_manager.get_theme_colors(theme_key)
        
        # Actualizar color del modo
        mode_colors = {
            'dark': '#00ff00',
            'light': '#000000',
            'olive': '#B4C8A0',
            'naval': '#0096C8'
        }
        color = mode_colors.get(theme_key, '#00ff00')
        self.label_mode.setStyleSheet(f"color: {color}; font-weight: bold;")
        
        # Actualizar color del rango (usa acento del tema)
        accent_color = theme['accent'].name()
        self.label_range.setStyleSheet(f"font-weight: bold; color: {accent_color};")
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN DE UI
    # -----------------------------------------------------------------------
    def setup_ui(self):
        """Configura elementos adicionales de la UI."""
        # Configurar tablas
        self._setup_table(self.tableWidget_live)
        self._setup_table(self.tableWidget_results)
        
        # Estado inicial
        self.label_inspector_icon.setText("⚪")
        self.label_inspector_status.setText("Verificando detector...")
        self.label_mode.setText("Modo: WIDE")
        
        # Configurar spinboxes
        self.spinBox_min_bw.setSuffix(" kHz")
        self.spinBox_max_bw.setSuffix(" kHz")
        self.spinBox_min_bw.setRange(10, 10000)
        self.spinBox_max_bw.setRange(20, 20000)
        
        # Configurar modo inicial
        self.on_mode_changed(2)  # Wide por defecto
    
    def _setup_table(self, table):
        """Configura propiedades comunes de las tablas."""
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(table.SelectRows)
    
    def setup_connections(self):
        """Conecta las señales de la UI."""
        self.pushButton_start.clicked.connect(self.on_start_clicked)
        self.pushButton_pause.clicked.connect(self.on_pause_clicked)
        self.pushButton_stop.clicked.connect(self.on_stop_clicked)
        self.pushButton_clear.clicked.connect(self.clear_results)
        self.pushButton_export.clicked.connect(self.export_results)
        self.pushButton_filter.clicked.connect(self.show_filter_dialog)
        
        self.comboBox_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.checkBox_auto_threshold.toggled.connect(
            lambda checked: self.doubleSpinBox_threshold.setEnabled(not checked)
        )

        # ===== NUEVO: Conectar nuevos controles =====
        self.checkBox_show_threshold.toggled.connect(self.on_show_threshold_toggled)
        self.checkBox_show_noise.toggled.connect(self.on_show_noise_toggled)
        self.pushButton_sync_values.clicked.connect(self.on_sync_values)
    
    # -----------------------------------------------------------------------
    # MÉTODOS DE SELECCIÓN DE BANDA
    # -----------------------------------------------------------------------
    def setup_band_selector(self):
        """Configura el selector de bandas usando BandManager."""
        self.comboBox_band.clear()
        
        # Cargar bandas desde el gestor
        for index, display in self.band_manager.get_display_names():
            self.comboBox_band.addItem(display, index)
        
        self.comboBox_band.currentIndexChanged.connect(self.on_band_changed)
        
        # Seleccionar FM Broadcast por defecto (índice 1)
        self.comboBox_band.setCurrentIndex(1)
    
    def on_band_changed(self, index):
        """Cambia la banda de frecuencias a escanear."""
        # Obtener el índice real almacenado en el item
        band_index = self.comboBox_band.currentData()
        
        # Obtener la banda del gestor
        self.current_band = self.band_manager.get_band(band_index)
        
        if not self.current_band:
            self.logger.error(f"❌ Banda no encontrada para índice {band_index}")
            return
        
        band = self.current_band
        
        # Verificar si la banda está disponible
        if band.get('unavailable', False):
            self.label_range.setText(f"⚠️ {band['range']}")
            self.label_range.setStyleSheet("font-weight: bold; color: #ff8800;")
            self.label_range.setToolTip(band.get('note', 'Banda no disponible'))
            self.current_band_frequencies = []
        else:
            self.label_range.setText(band['range'])
            self.label_range.setToolTip(band.get('description', ''))
            
            # Generar frecuencias según la configuración
            self.current_band_frequencies = self.band_manager.generate_frequencies(band)
            
            # Aplicar color del tema
            if self._theme_manager:
                theme = self._theme_manager.get_theme_colors(self._theme_manager.current_theme)
                accent_color = theme['accent'].name()
                self.label_range.setStyleSheet(f"font-weight: bold; color: {accent_color};")
        
        # Auto-seleccionar modo según la banda
        mode_map = {
            'NARROW': 0,
            'MEDIUM': 1,
            'WIDE': 2,
            'CUSTOM': 3
        }
        suggested_mode = band.get('mode', 'WIDE')
        self.comboBox_mode.setCurrentIndex(mode_map.get(suggested_mode, 2))
        
        status = "✅ disponible" if not band.get('unavailable', False) else "❌ NO disponible"
        desc = band.get('description', '')
        self._add_log(f"📡 Banda: {band['name']} | Rango: {band['range']} | {status}")
        if desc:
            self._add_log(f"   📝 {desc}")
    
    # ===== GENERADORES DE FRECUENCIAS =====
    def _generate_freq_list(self, start, end, step):
        """Genera lista de frecuencias con el paso dado."""
        import numpy as np
        return [round(f, 3) for f in np.arange(start, end + step/2, step)]
    
    def _generate_drone_24ghz(self):
        """Genera frecuencias para la banda de 2.4 GHz."""
        frequencies = []
        frequencies.extend([2400 + i*20 for i in range(5)])  # DJI
        frequencies.extend([2410, 2430, 2450, 2470])        # Autel
        frequencies.extend([2412, 2437, 2462])              # WiFi
        return sorted(list(set(frequencies)))
    
    def _generate_drone_58ghz(self):
        """Genera frecuencias para la banda de 5.8 GHz."""
        frequencies = []
        frequencies.extend([5735, 5755, 5775, 5795, 5815, 5835, 5855])  # DJI
        frequencies.extend([5740, 5760, 5780, 5800, 5820, 5840, 5860])  # Autel
        frequencies.extend([5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917])  # Raceband
        frequencies.extend([5705, 5745, 5785, 5825, 5865])  # Bandas A/B
        frequencies.extend([5645, 5665, 5685, 5885, 5905, 5925, 5945])  # Bandas E/F
        return sorted(list(set(frequencies)))
    
    def _generate_radar_s_band(self):
        """Genera frecuencias de radar meteorológico banda S."""
        return [2700 + i*5 for i in range(41)]  # 2700-2900 MHz cada 5 MHz
    
    def _generate_radar_l_band(self):
        """Genera frecuencias de radar vigilancia aérea banda L."""
        return [1200 + i*2 for i in range(101)]  # 1200-1400 MHz cada 2 MHz
    
    # -----------------------------------------------------------------------
    # MÉTODOS DE SELECCIÓN DE DETECCIONES
    # -----------------------------------------------------------------------
    def setup_detection_selection(self):
        """Configura la selección de detecciones para sintonizar frecuencia."""
        self.tableWidget_live.cellDoubleClicked.connect(self.on_detection_double_clicked)
        self.tableWidget_results.cellDoubleClicked.connect(self.on_detection_double_clicked)
        
        self.tableWidget_live.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableWidget_live.customContextMenuRequested.connect(self.show_context_menu)
        
        self.tableWidget_results.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableWidget_results.customContextMenuRequested.connect(self.show_context_menu)
    
    def on_detection_double_clicked(self, row, column):
        """Doble-click sintoniza la frecuencia."""
        sender = self.sender()
        if sender == self.tableWidget_live:
            freq_item = self.tableWidget_live.item(row, 0)
        else:
            freq_item = self.tableWidget_results.item(row, 0)
        
        if freq_item:
            try:
                freq_mhz = float(freq_item.text())
                self._add_log(f"🎯 Sintonizando a {freq_mhz:.3f} MHz")
                self.frequency_selected.emit(freq_mhz)
            except ValueError as e:
                self.logger.error(f"Error al parsear frecuencia: {e}")
    
    def show_context_menu(self, pos):
        """Muestra menú contextual para las detecciones."""
        sender = self.sender()
        if sender == self.tableWidget_live:
            table = self.tableWidget_live
        else:
            table = self.tableWidget_results
        
        row = table.currentRow()
        if row < 0:
            return
        
        freq_item = table.item(row, 0)
        type_item = table.item(row, 4)
        
        if not freq_item:
            return
        
        freq_mhz = float(freq_item.text())
        signal_type = type_item.text() if type_item else "Desconocido"
        
        menu = QMenu(self)
        
        action_tune = QAction(f"🎯 Sintonizar {freq_mhz:.3f} MHz", self)
        action_tune.triggered.connect(lambda: self.frequency_selected.emit(freq_mhz))
        
        action_copy = QAction(f"📋 Copiar frecuencia", self)
        action_copy.triggered.connect(lambda: self._copy_to_clipboard(str(freq_mhz)))
        
        action_mark = QAction(f"⭐ Marcar como interés", self)
        action_mark.triggered.connect(lambda: self._mark_detection(freq_mhz, signal_type))
        
        menu.addAction(action_tune)
        menu.addAction(action_copy)
        menu.addSeparator()
        menu.addAction(action_mark)
        
        menu.exec_(sender.mapToGlobal(pos))
    
    def _copy_to_clipboard(self, text):
        """Copia texto al portapapeles."""
        QApplication.clipboard().setText(text)
        self._add_log(f"📋 Frecuencia copiada: {text} MHz")
    
    def _mark_detection(self, freq_mhz, signal_type):
        """Marca una detección como de interés."""
        self._add_log(f"⭐ Marcada {freq_mhz:.3f} MHz ({signal_type})")
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS
    # -----------------------------------------------------------------------
    def on_mode_changed(self, index):
        """Cambia los rangos de BW según el modo."""
        modes = {
            0: (25, 200),      # Narrow: 25-200 kHz
            1: (200, 2000),    # Medium: 200-2000 kHz
            2: (2000, 10000),  # Wide: 2-10 MHz
            3: (self.spinBox_min_bw.value(), self.spinBox_max_bw.value())
        }
        
        min_bw, max_bw = modes.get(index, (25, 200))
        
        if index == 3:  # Custom mode
            self.spinBox_min_bw.setEnabled(True)
            self.spinBox_max_bw.setEnabled(True)
        else:
            self.spinBox_min_bw.setValue(min_bw)
            self.spinBox_max_bw.setValue(max_bw)
            self.spinBox_min_bw.setEnabled(False)
            self.spinBox_max_bw.setEnabled(False)
        
        mode_names = ['NARROW', 'MEDIUM', 'WIDE', 'CUSTOM']
        current_mode = mode_names[index]
        self.label_mode.setText(f"Modo: {current_mode}")
        
        # Aplicar color según el tema actual
        if self._theme_manager:
            theme_key = self._theme_manager.current_theme
            mode_colors = {
                'dark': '#00ff00',
                'light': '#000000',
                'olive': '#B4C8A0',
                'naval': '#0096C8'
            }
            color = mode_colors.get(theme_key, '#00ff00')
            self.label_mode.setStyleSheet(f"color: {color}; font-weight: bold;")
    
    def show_filter_dialog(self):
        """Muestra el diálogo de filtrado."""
        dialog = FilterDialog(self)
        
        dialog.check_narrow.setChecked(self.current_filters['narrow'])
        dialog.check_medium.setChecked(self.current_filters['medium'])
        dialog.check_wide.setChecked(self.current_filters['wide'])
        dialog.check_unknown.setChecked(self.current_filters['unknown'])
        
        if dialog.exec_() == QDialog.Accepted:
            self.current_filters = dialog.get_filters()
            self._apply_filters()
            self._add_log(f"🔍 Filtros aplicados")
    
    def _apply_filters(self):
        """Aplica los filtros a la tabla de resultados."""
        for row in range(self.tableWidget_results.rowCount()):
            item = self.tableWidget_results.item(row, 4)
            if item:
                signal_type = item.text()
                show = False
                
                if 'Narrow' in signal_type and self.current_filters['narrow']:
                    show = True
                elif 'Medium' in signal_type and self.current_filters['medium']:
                    show = True
                elif 'Wide' in signal_type and self.current_filters['wide']:
                    show = True
                elif 'Desconocido' in signal_type and self.current_filters['unknown']:
                    show = True
                
                self.tableWidget_results.setRowHidden(row, not show)
    
    def _add_log(self, message):
        """Añade mensaje al log."""
        self.logger.info(message)
    
    def get_config(self):
        """Obtiene configuración actual."""
        config = {
            'min_bw_hz': self.spinBox_min_bw.value() * 1000,
            'max_bw_hz': self.spinBox_max_bw.value() * 1000,
            'threshold_db': self.doubleSpinBox_threshold.value(),
            'auto_threshold': self.checkBox_auto_threshold.isChecked(),
            'mode': self.comboBox_mode.currentIndex(),
            'band_frequencies': self.get_band_frequencies(),
        }
        
        # Añadir información de la banda si existe
        if hasattr(self, 'current_band') and self.current_band:
            config['band_name'] = self.current_band.get('name', 'Desconocida')
            config['band_display'] = self.current_band.get('display', '')
            config['band_type'] = self.current_band.get('type', 'unknown')
        else:
            config['band_name'] = 'FM Broadcast'  # Valor por defecto
            config['band_display'] = '📻 FM Broadcast'
            config['band_type'] = 'broadcast'
        
        return config
    
    def get_band_frequencies(self):
        """Retorna la lista de frecuencias de la banda actual."""
        if self.current_band_frequencies:
            return self.current_band_frequencies
        return [88, 88.1, 88.2]  # Fallback a FM
    
    def update_inspector_status(self, available: bool):
        """Actualiza el estado del adaptador."""
        if available:
            self.label_inspector_icon.setText("🟢")
            self.label_inspector_status.setText("gr-inspector disponible (modo REAL)")
        else:
            self.label_inspector_icon.setText("🟡")
            self.label_inspector_status.setText("gr-inspector NO disponible (usando CFAR)")
    
    def update_scan_state(self, scanning: bool, paused: bool = False):
        """Actualiza el estado de los botones."""
        self.is_scanning = scanning
        self.is_paused = paused
        
        self.pushButton_start.setEnabled(not scanning)
        self.pushButton_pause.setEnabled(scanning)
        self.pushButton_stop.setEnabled(scanning)
        
        if paused:
            self.pushButton_pause.setText("▶ REANUDAR")
            self.label_status.setText("🟡 PAUSADO")
            self.label_status.setStyleSheet("color: #ffaa00; font-weight: bold;")
        elif scanning:
            self.pushButton_pause.setText("⏸ PAUSAR")
            self.label_status.setText("🟢 ESCANEANDO")
            self.label_status.setStyleSheet("color: #00ff00; font-weight: bold;")
        else:
            self.label_status.setText("⚪ DETENIDO")
            self.label_status.setStyleSheet("color: #888888; font-weight: bold;")
            self.progressBar.setValue(0)
            self.label_samples.setText("0")
            self.label_detections.setText("0")
    
    def update_progress(self, samples_processed: int, detections_found: int):
        """Actualiza las estadísticas."""
        self.label_samples.setText(f"{samples_processed:,}")
        self.label_detections.setText(f"{detections_found}")
        self.progressBar.setValue(min(100, detections_found * 5))
    
    '''def add_detection(self, detection: dict):
        """Añade una detección a las tablas."""
        freq = detection.get('center_freq_mhz', 0)
        bw_khz = detection.get('bandwidth_khz', detection.get('bandwidth_hz', 0) / 1000)
        power = detection.get('power_db', 0)
        snr = detection.get('snr_db', 0)
        signal_type = detection.get('type_name', '❓ Desconocido')
        confidence = detection.get('confidence', 0) * 100
        detector = detection.get('detector', 'desconocido')
        type_color = detection.get('type_color', '#888888')
        
        # Tabla en vivo
        self.tableWidget_live.insertRow(0)
        self.tableWidget_live.setItem(0, 0, QTableWidgetItem(f"{freq:.3f}"))
        self.tableWidget_live.setItem(0, 1, QTableWidgetItem(f"{bw_khz:.0f}"))
        
        power_item = QTableWidgetItem(f"{power:.1f}")
        power_item.setForeground(QColor(type_color))
        self.tableWidget_live.setItem(0, 2, power_item)
        
        self.tableWidget_live.setItem(0, 3, QTableWidgetItem(f"{snr:.1f}"))
        
        type_item = QTableWidgetItem(signal_type)
        type_item.setForeground(QColor(type_color))
        self.tableWidget_live.setItem(0, 4, type_item)
        
        # Tooltip según detector
        tooltip = f"Detección por: {detector}"
        self.tableWidget_live.item(0, 0).setToolTip(tooltip)
        
        # Limitar a 10 filas
        while self.tableWidget_live.rowCount() > 10:
            self.tableWidget_live.removeRow(10)
        
        # Tabla de resultados
        timestamp = datetime.fromtimestamp(
            detection.get('timestamp', time.time())
        ).strftime("%H:%M:%S")
        
        row = self.tableWidget_results.rowCount()
        self.tableWidget_results.insertRow(row)
        
        self.tableWidget_results.setItem(row, 0, QTableWidgetItem(f"{freq:.3f}"))
        self.tableWidget_results.setItem(row, 1, QTableWidgetItem(f"{bw_khz:.0f}"))
        self.tableWidget_results.setItem(row, 2, QTableWidgetItem(f"{power:.1f}"))
        self.tableWidget_results.setItem(row, 3, QTableWidgetItem(f"{snr:.1f}"))
        self.tableWidget_results.setItem(row, 4, QTableWidgetItem(signal_type))
        self.tableWidget_results.setItem(row, 5, QTableWidgetItem(f"{confidence:.0f}%"))
        self.tableWidget_results.setItem(row, 6, QTableWidgetItem(timestamp))
        
        self.tableWidget_results.item(row, 4).setForeground(QColor(type_color))
        self.tableWidget_results.item(row, 0).setToolTip(tooltip)
        
        self.label_count.setText(f"{self.tableWidget_results.rowCount()} detecciones")
        self.label_last.setText(f"{freq:.3f} MHz @ {power:.1f} dB")
        
        self._apply_filters()'''
    
    # widgets/signal_detector_widget.py - Modificar add_detection()

    def add_detection(self, detection: dict):
        """Añade una detección a las tablas usando colores del tema"""
        freq = detection.get('center_freq_mhz', 0)
        bw_khz = detection.get('bandwidth_khz', detection.get('bandwidth_hz', 0) / 1000)
        power = detection.get('power_db', 0)
        snr = detection.get('snr_db', 0)
        signal_type = detection.get('type_name', '❓ Desconocido')
        confidence = detection.get('confidence', 0) * 100
        detector = detection.get('detector', 'desconocido')
        
        # ===== USAR COLORES DEL TEMA =====
        # Obtener colores del tema actual
        if self._theme_manager:
            theme = self._theme_manager.get_theme_colors(self._theme_manager.current_theme)
            accent_color = theme['accent'].name()
            foreground = theme['foreground'].name()
            grid_color = theme['grid'].name()
            
            # Colores por tipo de señal basados en el tema
            type_colors = {
                'NARROW': theme.get('spectrum_default', QColor(0, 255, 0)).name(),
                'MEDIUM': theme.get('max_hold_default', QColor(255, 255, 0)).name(),
                'WIDE': theme.get('min_hold_default', QColor(255, 100, 0)).name(),
                'UNKNOWN': grid_color
            }
            type_color = type_colors.get(detection.get('signal_type', 'UNKNOWN'), foreground)
        else:
            # Fallback si no hay theme_manager
            accent_color = "#0080ff"
            foreground = "#DCDCDC"
            grid_color = "#404040"
            type_color = {
                'NARROW': "#00ff00",
                'MEDIUM': "#ffff00",
                'WIDE': "#ff8800",
                'UNKNOWN': "#888888"
            }.get(detection.get('signal_type', 'UNKNOWN'), "#00ff00")
        
        # ===== TABLA EN VIVO =====
        self.tableWidget_live.insertRow(0)
        
        # Frecuencia
        freq_item = QTableWidgetItem(f"{freq:.3f}")
        freq_item.setForeground(QColor(accent_color))
        self.tableWidget_live.setItem(0, 0, freq_item)
        
        # Ancho de banda
        self.tableWidget_live.setItem(0, 1, QTableWidgetItem(f"{bw_khz:.0f}"))
        
        # Potencia
        power_item = QTableWidgetItem(f"{power:.1f}")
        power_item.setForeground(QColor(type_color))
        self.tableWidget_live.setItem(0, 2, power_item)
        
        # SNR
        self.tableWidget_live.setItem(0, 3, QTableWidgetItem(f"{snr:.1f}"))
        
        # Tipo
        type_item = QTableWidgetItem(signal_type)
        type_item.setForeground(QColor(type_color))
        type_item.setBackground(QColor(theme['input_bg'].name()) if self._theme_manager else QColor(30,30,30))
        self.tableWidget_live.setItem(0, 4, type_item)
        
        # Tooltip
        tooltip = f"Detección por: {detector}"
        freq_item.setToolTip(tooltip)
        type_item.setToolTip(tooltip)
        
        # Limitar a 20 filas
        while self.tableWidget_live.rowCount() > 20:
            self.tableWidget_live.removeRow(20)
        
        # ===== TABLA DE RESULTADOS =====
        from datetime import datetime
        timestamp = datetime.fromtimestamp(
            detection.get('timestamp', time.time())
        ).strftime("%H:%M:%S")
        
        row = self.tableWidget_results.rowCount()
        self.tableWidget_results.insertRow(row)
        
        # Configurar items con colores del tema
        items = [
            (f"{freq:.3f}", foreground),
            (f"{bw_khz:.0f}", foreground),
            (f"{power:.1f}", type_color),
            (f"{snr:.1f}", foreground),
            (signal_type, type_color),
            (f"{confidence:.0f}%", foreground),
            (timestamp, grid_color)
        ]
        
        for col, (text, color) in enumerate(items):
            item = QTableWidgetItem(text)
            item.setForeground(QColor(color))
            if col == 0:  # Frecuencia
                item.setToolTip(tooltip)
            self.tableWidget_results.setItem(row, col, item)
        
        # Actualizar contadores
        self.label_count.setText(f"{self.tableWidget_results.rowCount()} detecciones")
        self.label_last.setText(f"{freq:.3f} MHz @ {power:.1f} dB")
        
        # Aplicar filtros
        self._apply_filters()
    
    def clear_results(self):
        """Limpia las tablas."""
        self.tableWidget_live.setRowCount(0)
        self.tableWidget_results.setRowCount(0)
        self.label_count.setText("0 detecciones")
        self.label_last.setText("---")
        self.label_samples.setText("0")
        self.label_detections.setText("0")
        self._add_log("🗑️ Tablas limpiadas")
    
    def export_results(self):
        """Exporta a CSV."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Exportar Resultados", "detecciones.csv",
                "CSV Files (*.csv);;All Files (*)"
            )
            
            if filename:
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'Frecuencia (MHz)', 'BW (kHz)', 'Potencia (dB)',
                        'SNR (dB)', 'Tipo', 'Confianza (%)', 'Timestamp', 'Detector'
                    ])
                    
                    for row in range(self.tableWidget_results.rowCount()):
                        if not self.tableWidget_results.isRowHidden(row):
                            row_data = []
                            for col in range(7):
                                item = self.tableWidget_results.item(row, col)
                                row_data.append(item.text() if item else '')
                            # Añadir detector
                            tooltip = self.tableWidget_results.item(row, 0).toolTip()
                            detector = tooltip.replace("Detección por: ", "") if tooltip else "desconocido"
                            row_data.append(detector)
                            writer.writerow(row_data)
                
                self._add_log(f"📤 Exportado a {filename}")
                
        except Exception as e:
            self.logger.error(f"Error exportando: {e}")
    
    # -----------------------------------------------------------------------
    # SLOTS
    # -----------------------------------------------------------------------
    def on_start_clicked(self):
        """Inicia el escaneo."""
        config = self.get_config()
        self.clear_results()
        self._add_log("▶ Iniciando escaneo...")
        self.scan_started.emit(config)
    
    def on_pause_clicked(self):
        """Pausa o reanuda."""
        if self.is_paused:
            self.scan_resumed.emit()
        else:
            self.scan_paused.emit()
    
    def on_stop_clicked(self):
        """Detiene el escaneo."""
        self._add_log("⏹ Deteniendo escaneo...")
        self.scan_stopped.emit()

    def on_show_threshold_toggled(self, checked):
        """Muestra/oculta línea de umbral en el espectro"""
        self.show_threshold = checked
        self.logger.info(f"📊 Mostrar umbral: {checked}")
        
        # Emitir señal al controller
        self.scan_config_updated.emit({
            'show_threshold': checked,
            'threshold_value': self.current_threshold
        })

    def on_show_noise_toggled(self, checked):
        """Muestra/oculta línea de ruido en el espectro"""
        self.show_noise = checked
        self.logger.info(f"📊 Mostrar ruido: {checked}")
        
        self.scan_config_updated.emit({
            'show_noise': checked,
            'noise_value': self.current_noise
        })

    def on_sync_values(self):
        """Solicita valores actuales al detector - VERSIÓN MEJORADA"""
        self.logger.info("🔄 Solicitando sincronización de valores")
        
        # Mostrar feedback visual
        original_text = self.pushButton_sync_values.text()
        self.pushButton_sync_values.setText("⏳")
        self.pushButton_sync_values.setEnabled(False)
        
        # Emitir señal
        self.scan_config_updated.emit({'sync_detector_values': True})
        
        # Restaurar botón después de un momento
        QTimer.singleShot(500, lambda: self._restore_sync_button(original_text))

    def request_values_update(self):
        """Timer para actualizar valores periódicamente"""
        if self.is_scanning:
            self.scan_config_updated.emit({'request_values': True})

    def _restore_sync_button(self, original_text):
        """Restaura el botón de sincronización"""
        self.pushButton_sync_values.setText(original_text)
        self.pushButton_sync_values.setEnabled(True)

    def update_detector_values(self, threshold_db, noise_db):
        """Actualiza los valores mostrados en la UI - VERSIÓN MEJORADA"""
        self.current_threshold = threshold_db
        self.current_noise = noise_db
        
        # Actualizar labels
        self.label_threshold_value.setText(f"{threshold_db:.1f} dB") #--umbral
        self.label_noise_value.setText(f"{noise_db:.1f} dB") #--ruido
        
        # Actualizar color según relación
        if threshold_db > noise_db + 10:
            self.label_threshold_value.setStyleSheet("color: #ff8888; font-size: 8pt; font-weight: bold;")
        else:
            self.label_threshold_value.setStyleSheet("color: #ffaa00; font-size: 8pt;")
        
        # Log para debug (solo cada cierto tiempo)
        if not hasattr(self, '_last_value_log'):
            self._last_value_log = 0
        
        now = time.time()
        if now - self._last_value_log > 5:  # Cada 5 segundos
            self.logger.info(f"📊 Valores detector - Umbral: {threshold_db:.1f} dB, Ruido: {noise_db:.1f} dB")
            self._last_value_log = now
        
        # Si estamos en modo automático, actualizar también el spinbox
        if self.checkBox_auto_threshold.isChecked():
            self.doubleSpinBox_threshold.blockSignals(True)
            self.doubleSpinBox_threshold.setValue(threshold_db)
            self.doubleSpinBox_threshold.blockSignals(False)
            
    def get_config(self):
        """Obtiene configuración actual (modificado)"""
        config = {
            'min_bw_hz': self.spinBox_min_bw.value() * 1000,
            'max_bw_hz': self.spinBox_max_bw.value() * 1000,
            'threshold_db': self.doubleSpinBox_threshold.value(),
            'auto_threshold': self.checkBox_auto_threshold.isChecked(),
            'mode': self.comboBox_mode.currentIndex(),
            'band_frequencies': self.get_band_frequencies(),
            'show_threshold': self.show_threshold,
            'show_noise': self.show_noise,
        }
        
        if hasattr(self, 'current_band') and self.current_band:
            config['band_name'] = self.current_band.get('name', 'Desconocida')
            config['band_display'] = self.current_band.get('display', '')
            config['band_type'] = self.current_band.get('type', 'unknown')
        
        return config


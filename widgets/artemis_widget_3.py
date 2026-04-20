# -*- coding: utf-8 -*-

"""
Artemis Database Widget for SIMANEEM
=====================================
Widget de base de datos de señales Artemis con filtros avanzados.
Versión CORREGIDA para UI con filtros en layout directo.
"""

import os
import json
import re
import logging
from typing import List, Dict, Optional, Set

from PyQt5.QtWidgets import (
    QDockWidget, QMessageBox, QFileDialog, QApplication,
    QListWidgetItem, QMenu, QAction
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QColor, QPixmap, QTextCursor
from PyQt5.uic import loadUi


# ============================================================================
# CONSTANTES Y CONFIGURACIÓN
# ============================================================================

DEFAULT_MODES = ["Voice", "Data", "CW", "Digital", "Pulse", "Burst"]
DEFAULT_MODULATIONS = ["AM", "FM", "USB", "LSB", "CW", "FSK", "PSK", "QAM", "OFDM"]
DEFAULT_CATEGORIES = ["Broadcast", "Military", "Aviation", "Maritime", "Amateur", "Satellite", "Drone", "Radar"]
DEFAULT_LOCATIONS = ["Global", "Europe", "North America", "Asia", "South America", "Africa", "Oceania"]


# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def parse_frequency_from_line(line: str) -> float:
    """Extrae el valor numérico en MHz de una línea de frecuencia."""
    line = line.strip()
    if line.startswith('•'):
        line = line[1:].strip()
    
    match = re.search(r'(\d+(?:\.\d+)?)\s*(GHz|MHz|kHz|Hz)', line, re.IGNORECASE)
    if match:
        value = float(match.group(1))
        unit = match.group(2).lower()
        if unit == 'ghz':
            return value * 1000
        elif unit == 'khz':
            return value / 1000
        elif unit == 'hz':
            return value / 1_000_000
        return value
    
    match = re.search(r'(\d+(?:\.\d+)?)', line)
    if match:
        return float(match.group(1))
    
    return 0.0


def format_frequency_line(value: float, desc: str = "") -> str:
    """Formatea una frecuencia en Hz a una línea legible."""
    if value >= 1_000_000_000:
        freq_str = f"{value/1_000_000_000:.3f} GHz"
    elif value >= 1_000_000:
        freq_str = f"{value/1_000_000:.3f} MHz"
    elif value >= 1_000:
        freq_str = f"{value/1_000:.3f} kHz"
    else:
        freq_str = f"{value:.0f} Hz"
    
    if desc:
        return f"   {freq_str}  →  {desc}"
    return f"   {freq_str}"


def format_bandwidth_line(value: float, desc: str = "") -> str:
    """Formatea un ancho de banda en Hz a una línea legible."""
    if value >= 1_000_000:
        bw_str = f"{value/1_000_000:.2f} MHz"
    else:
        bw_str = f"{value/1_000:.2f} kHz"
    
    if desc:
        return f"   {bw_str}  →  {desc}"
    return f"   {bw_str}"


# ============================================================================
# HILO DE CARGA ASÍNCRONA
# ============================================================================

class ArtemisLoaderThread(QThread):
    """Hilo de carga asíncrona para no bloquear la UI."""
    
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list, set, set, set, set, set)
    error = pyqtSignal(str)
    
    def __init__(self, base_path: str):
        super().__init__()
        self.base_path = base_path
    
    def run(self):
        try:
            signals = []
            all_categories: Set[str] = set()
            all_modes: Set[str] = set()
            all_modulations: Set[str] = set()
            all_locations: Set[str] = set()
            all_frequencies: Set[float] = set()
            
            static_path = os.path.join(self.base_path, "static")
            
            if not os.path.exists(static_path):
                self.error.emit("No se encontró la carpeta 'static'")
                return
            
            folders = [d for d in os.listdir(static_path) 
                      if os.path.isdir(os.path.join(static_path, d)) and d.isdigit()]
            folders.sort(key=lambda x: int(x))
            
            total = len(folders)
            
            for idx, folder in enumerate(folders):
                folder_path = os.path.join(static_path, folder)
                signal = self._load_signal(folder_path, folder)
                if signal:
                    signals.append(signal)
                    
                    for cat in signal.get('categories', []):
                        all_categories.add(cat)
                    for mode in signal.get('modes', []):
                        all_modes.add(mode)
                    for mod in signal.get('modulations', []):
                        all_modulations.add(mod)
                    for loc in signal.get('locations', []):
                        all_locations.add(loc)
                    for freq in signal.get('frequencies', []):
                        all_frequencies.add(freq.get('value', 0))
                
                if idx % 10 == 0:
                    self.progress.emit(idx, total)
            
            self.progress.emit(total, total)
            self.finished.emit(
                signals,
                all_categories,
                all_modes,
                all_modulations,
                all_locations,
                all_frequencies
            )
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _load_signal(self, folder_path: str, folder_id: str) -> Optional[dict]:
        """Carga una señal desde su carpeta."""
        try:
            signal = {
                'id': folder_id,
                'name': '',
                'categories': [],
                'frequencies': [],
                'bandwidths': [],
                'modulations': [],
                'modes': [],
                'locations': [],
                'description': '',
                'waterfall_path': '',
            }
            
            json_path = os.path.join(folder_path, "signal.json")
            if os.path.exists(json_path):
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'signal' in data:
                        signal['name'] = data['signal'].get('name', '').strip("'")
                    signal['categories'] = data.get('category', [])
                    
                    for freq in data.get('frequency', []):
                        signal['frequencies'].append({
                            'value': freq.get('value', 0),
                            'description': freq.get('description', '')
                        })
                    
                    for bw in data.get('bandwidth', []):
                        signal['bandwidths'].append({
                            'value': bw.get('value', 0),
                            'description': bw.get('description', '')
                        })
                    
                    signal['modulations'] = [m.get('value', '') for m in data.get('modulation', [])]
                    signal['modes'] = [m.get('value', '') for m in data.get('mode', [])]
                    signal['locations'] = [l.get('value', '') for l in data.get('location', [])]
            
            desc_path = os.path.join(folder_path, "description.md")
            if os.path.exists(desc_path):
                with open(desc_path, 'r', encoding='utf-8') as f:
                    signal['description'] = f.read()
            
            media_path = os.path.join(folder_path, "media.json")
            if os.path.exists(media_path):
                with open(media_path, 'r', encoding='utf-8') as f:
                    for m in json.load(f):
                        if m.get('type') == 'Image':
                            media_file = f"{m.get('file_name')}.{m.get('extension')}"
                            media_full = os.path.join(folder_path, "media", media_file)
                            if os.path.exists(media_full):
                                signal['waterfall_path'] = media_full
                                break
            
            if not signal['name']:
                signal['name'] = f"Señal {folder_id}"
            
            return signal
            
        except Exception as e:
            print(f"Error cargando señal {folder_id}: {e}")
            return None


# ============================================================================
# WIDGET PRINCIPAL
# ============================================================================

class ArtemisWidget(QDockWidget):
    """
    Widget de base de datos Artemis con filtros avanzados.
    """
    
    signal_selected = pyqtSignal(float)
    database_loaded = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # Cargar UI
        loadUi('ui/artemis_widget.ui', self)
        
        # Datos
        self.signals: List[dict] = []
        self.filtered_signals: List[dict] = []
        self.current_signal: Optional[dict] = None
        self.tuned_signal_id: Optional[str] = None
        self.loader: Optional[ArtemisLoaderThread] = None
        self.base_path: str = ""
        self._loading_in_progress: bool = False
        
        # Valores únicos para filtros
        self.all_categories: Set[str] = set(DEFAULT_CATEGORIES)
        self.all_modes: Set[str] = set(DEFAULT_MODES)
        self.all_modulations: Set[str] = set(DEFAULT_MODULATIONS)
        self.all_locations: Set[str] = set(DEFAULT_LOCATIONS)
        
        # Estado de filtros
        self.filters_active: bool = False
        
        # Referencia al layout de filtros (para mostrar/ocultar)
        # En esta UI, los filtros están en un QVBoxLayout llamado verticalLayout_filters
        self.filter_layout = None
        self.filter_widgets_visible = True
        
        # Configurar UI
        self.setup_ui()
        self.setup_connections()
        
        # Estado inicial
        self.set_controls_enabled(False)
        self.pushButton_load.setEnabled(True)
        self.show_initial_message()
        
        self.logger.info("✅ ArtemisWidget inicializado")
    
    # ------------------------------------------------------------------------
    # CONFIGURACIÓN DE UI
    # ------------------------------------------------------------------------
    
    def setup_ui(self):
        """Configura elementos adicionales de la UI."""
        self.splitter_main.setSizes([250, 400])
        
        # Configurar comboBox_category (búsqueda rápida)
        self.comboBox_category.clear()
        self.comboBox_category.addItem("📋 TODAS LAS CATEGORÍAS", None)
        
        # Configurar text edits
        self.textEdit_frequencies.setLineWrapMode(0)
        self.textEdit_bandwidths.setLineWrapMode(0)
        self.textEdit_frequencies.mousePressEvent = self.on_frequencies_click
        self.textEdit_bandwidths.mousePressEvent = self.on_bandwidths_click
        self.textEdit_frequencies.setCursor(Qt.PointingHandCursor)
        
        # Ocultar filtros inicialmente
        self._set_filters_visible(False)
        self.pushButton_toggle_filters.setChecked(False)
        
        # Ocultar badge de filtros
        self.label_filter_badge.setVisible(False)
        
        # Ocultar indicador de sintonizada
        self.label_tuned_status.setVisible(False)
        
        # Poblar comboboxes de filtros
        self._populate_filter_comboboxs()
        
        # Inicializar rangos
        self.doubleSpinBox_freq_min.setValue(0.0)
        self.doubleSpinBox_freq_max.setValue(6000.0)
        self.doubleSpinBox_bw_min.setValue(0.0)
        self.doubleSpinBox_bw_max.setValue(100000.0)
    
    def _set_filters_visible(self, visible: bool):
        """Muestra u oculta todos los widgets del panel de filtros."""
        self.filter_widgets_visible = visible
        
        # Ocultar/mostrar todos los widgets en el layout de filtros
        # Lista de widgets a controlar
        filter_widgets = [
            'label_filters_title',
            'pushButton_clear_filters_quick',
            'label_filter_freq', 'doubleSpinBox_freq_min', 'label_freq_to', 
            'doubleSpinBox_freq_max', 'pushButton_clear_freq',
            'label_filter_bw', 'doubleSpinBox_bw_min', 'label_bw_to',
            'doubleSpinBox_bw_max', 'pushButton_clear_bw',
            'label_filter_category', 'comboBox_filter_category',
            'label_filter_mode', 'comboBox_filter_mode',
            'label_filter_modulation', 'comboBox_filter_modulation',
            'label_filter_location', 'comboBox_filter_location',
            'pushButton_apply_filters', 'pushButton_reset_filters'
        ]
        
        for widget_name in filter_widgets:
            if hasattr(self, widget_name):
                widget = getattr(self, widget_name)
                widget.setVisible(visible)
    
    def _populate_filter_comboboxs(self):
        """Pobla los comboboxes de filtros."""
        self._populate_combo(self.comboBox_filter_category, "TODAS", list(self.all_categories))
        self._populate_combo(self.comboBox_filter_mode, "TODOS", list(self.all_modes))
        self._populate_combo(self.comboBox_filter_modulation, "TODAS", list(self.all_modulations))
        self._populate_combo(self.comboBox_filter_location, "TODAS", list(self.all_locations))
    
    def _populate_combo(self, combo, default_text: str, items: List[str]):
        """Pobla un combobox con opciones."""
        combo.clear()
        combo.addItem(f"📋 {default_text}", None)
        for item in sorted(items):
            if item and item.strip():
                combo.addItem(item, item)
    
    def setup_connections(self):
        """Conecta las señales de los widgets de la UI."""
        # Control principal
        self.pushButton_load.clicked.connect(self.load_database)
        self.pushButton_refresh.clicked.connect(self.refresh_database)
        self.pushButton_tune.clicked.connect(self.on_tune_clicked)
        
        # Toggle de filtros
        self.pushButton_toggle_filters.toggled.connect(self._set_filters_visible)
        
        # Búsqueda
        self.lineEdit_search.textChanged.connect(self.on_search_changed)
        self.comboBox_category.currentIndexChanged.connect(self.on_search_changed)
        self.pushButton_clear_search.clicked.connect(self.clear_search)
        
        # Lista de señales
        self.listWidget_signals.itemSelectionChanged.connect(self.on_signal_selected)
        self.listWidget_signals.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listWidget_signals.customContextMenuRequested.connect(self.show_context_menu)
        
        # Filtros avanzados
        self.pushButton_apply_filters.clicked.connect(self.apply_filters)
        self.pushButton_reset_filters.clicked.connect(self.reset_all_filters)
        self.pushButton_clear_filters_quick.clicked.connect(self.reset_all_filters)
        self.pushButton_clear_freq.clicked.connect(self.clear_freq_filter)
        self.pushButton_clear_bw.clicked.connect(self.clear_bw_filter)
    
    # ------------------------------------------------------------------------
    # MÉTODOS DE ESTADO INICIAL
    # ------------------------------------------------------------------------
    
    def show_initial_message(self):
        """Muestra el mensaje inicial cuando no hay datos."""
        self.label_signal_name.setText("🔒 Selecciona una base de datos")
        self.label_count.setText("Carga una base de datos para comenzar")
        self.textEdit_frequencies.setPlainText("   No hay datos cargados")
        self.textEdit_bandwidths.setPlainText("   No hay datos cargados")
        self.label_mod_value.setText("-")
        self.label_mode_value.setText("-")
        self.label_category_value.setText("-")
        self.label_location_value.setText("-")
        self.textEdit_description.setPlainText("Presiona 'CARGAR DB' y selecciona la carpeta de Artemis-DB")
        self.listWidget_signals.clear()
        self.label_waterfall.setText("📡 No hay imagen disponible\n\nCarga una base de datos primero")
        self.label_tuned_status.setVisible(False)
    
    def set_controls_enabled(self, enabled: bool):
        """Habilita o deshabilita todos los controles excepto el botón de carga."""
        self.pushButton_refresh.setEnabled(enabled)
        self.pushButton_tune.setEnabled(enabled)
        self.pushButton_toggle_filters.setEnabled(enabled)
        
        self.lineEdit_search.setEnabled(enabled)
        self.comboBox_category.setEnabled(enabled)
        self.pushButton_clear_search.setEnabled(enabled)
        self.listWidget_signals.setEnabled(enabled)
        self.textEdit_frequencies.setEnabled(enabled)
        self.textEdit_bandwidths.setEnabled(enabled)
        self.textEdit_description.setEnabled(enabled)
        self.tabWidget.setEnabled(enabled)
        
        # Filtros
        self.pushButton_apply_filters.setEnabled(enabled)
        self.pushButton_reset_filters.setEnabled(enabled)
        self.pushButton_clear_filters_quick.setEnabled(enabled)
        self.pushButton_clear_freq.setEnabled(enabled)
        self.pushButton_clear_bw.setEnabled(enabled)
        self.doubleSpinBox_freq_min.setEnabled(enabled)
        self.doubleSpinBox_freq_max.setEnabled(enabled)
        self.doubleSpinBox_bw_min.setEnabled(enabled)
        self.doubleSpinBox_bw_max.setEnabled(enabled)
        self.comboBox_filter_category.setEnabled(enabled)
        self.comboBox_filter_mode.setEnabled(enabled)
        self.comboBox_filter_modulation.setEnabled(enabled)
        self.comboBox_filter_location.setEnabled(enabled)
    
    # ------------------------------------------------------------------------
    # CARGA DE BASE DE DATOS
    # ------------------------------------------------------------------------
    
    def load_database(self):
        """Carga la base de datos desde una carpeta seleccionada."""
        folder = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta de Artemis-DB",
            os.path.expanduser("~")
        )
        
        if not folder:
            return
        
        if not os.path.exists(os.path.join(folder, "static")):
            QMessageBox.warning(
                self,
                "Error",
                "La carpeta seleccionada no contiene la estructura de Artemis-DB.\n\n"
                "Debe seleccionar la carpeta raíz del repositorio (la que contiene la carpeta 'static')."
            )
            return
        
        self.base_path = folder
        self._start_loading(folder)
    
    def auto_load_from_config(self, db_path: str):
        """Carga la base de datos desde una ruta de configuración."""
        if self._loading_in_progress:
            self.logger.warning("⚠️ Carga ya en progreso, ignorando...")
            return
        
        if not db_path or not os.path.exists(db_path):
            self.logger.warning(f"⚠️ Ruta no válida: {db_path}")
            return
        
        if not os.path.exists(os.path.join(db_path, "static")):
            self.logger.warning(f"⚠️ Ruta no contiene carpeta 'static': {db_path}")
            return
        
        self.base_path = db_path
        self._start_loading(db_path)
    
    def _start_loading(self, path: str):
        """Inicia la carga asíncrona."""
        self._loading_in_progress = True
        self.pushButton_load.setEnabled(False)
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)
        self.listWidget_signals.clear()
        
        self.label_signal_name.setText("📡 Cargando base de datos...")
        self.label_count.setText("Cargando señales...")
        QApplication.processEvents()
        
        self.loader = ArtemisLoaderThread(path)
        self.loader.progress.connect(self.update_progress)
        self.loader.finished.connect(self.on_load_finished)
        self.loader.error.connect(self.on_load_error)
        self.loader.start()
    
    def refresh_database(self):
        """Refresca la base de datos."""
        if self.base_path:
            self.reset_all_filters()
            self._start_loading(self.base_path)
    
    def update_progress(self, current: int, total: int):
        """Actualiza la barra de progreso."""
        if total > 0:
            self.progressBar.setValue(int(current * 100 / total))
            QApplication.processEvents()
    
    def on_load_finished(self, signals: List[dict], categories: Set[str], 
                         modes: Set[str], modulations: Set[str], 
                         locations: Set[str], frequencies: Set[float]):
        """Finaliza la carga y actualiza la UI."""
        self.signals = signals
        self.filtered_signals = signals.copy()
        
        # Actualizar conjuntos de valores únicos
        self.all_categories = categories or set(DEFAULT_CATEGORIES)
        self.all_modes = modes or set(DEFAULT_MODES)
        self.all_modulations = modulations or set(DEFAULT_MODULATIONS)
        self.all_locations = locations or set(DEFAULT_LOCATIONS)
        
        # Actualizar comboboxes de filtros
        self._populate_filter_comboboxs()
        
        # Actualizar rango de frecuencia
        if frequencies:
            min_freq = min(frequencies) / 1e6
            max_freq = max(frequencies) / 1e6
            self.doubleSpinBox_freq_min.setValue(min_freq)
            self.doubleSpinBox_freq_max.setValue(max_freq)
        
        # Actualizar combo de categorías (búsqueda rápida)
        self.comboBox_category.blockSignals(True)
        self.comboBox_category.clear()
        self.comboBox_category.addItem("📋 TODAS LAS CATEGORÍAS", None)
        for cat in sorted(self.all_categories):
            self.comboBox_category.addItem(cat, cat)
        self.comboBox_category.blockSignals(False)
        
        # Actualizar lista
        self.update_list()
        
        # Ocultar barra de progreso
        self.progressBar.setVisible(False)
        self.pushButton_load.setEnabled(True)
        self.label_count.setText(f"{len(signals)} señales")
        
        # Desbloquear controles
        self.set_controls_enabled(True)
        
        # Seleccionar primera señal
        if self.listWidget_signals.count() > 0:
            self.listWidget_signals.setCurrentRow(0)
            self.on_signal_selected()
        
        # Resetear filtros
        self.filters_active = False
        self.label_filter_badge.setVisible(False)
        
        self._loading_in_progress = False
        self.database_loaded.emit()
        
        self.logger.info(f"✅ Base de datos Artemis cargada: {len(signals)} señales")
    
    def on_load_error(self, error: str):
        """Maneja error de carga."""
        self.progressBar.setVisible(False)
        self.pushButton_load.setEnabled(True)
        self._loading_in_progress = False
        self.logger.error(f"Error cargando Artemis-DB: {error}")
        
        self.label_signal_name.setText("❌ Error al cargar")
        self.label_count.setText("0 señales")
        self.textEdit_frequencies.setPlainText("   Error al cargar la base de datos")
        
        QMessageBox.warning(self, "Error de Carga", f"No se pudo cargar la base de datos:\n{error}")
    
    # ------------------------------------------------------------------------
    # BÚSQUEDA Y FILTRADO
    # ------------------------------------------------------------------------
    
    def on_search_changed(self):
        """Maneja cambios en búsqueda por nombre o categoría rápida."""
        search_text = self.lineEdit_search.text().lower().strip()
        category_filter = self.comboBox_category.currentData()
        
        filtered = []
        for sig in self.signals:
            if category_filter is not None:
                if category_filter not in sig.get('categories', []):
                    continue
            if search_text:
                if search_text not in sig.get('name', '').lower():
                    continue
            filtered.append(sig)
        
        self.filtered_signals = filtered
        self.update_list()
        self.label_count.setText(f"{len(filtered)} / {len(self.signals)} señales")
    
    def clear_search(self):
        """Limpia la búsqueda por nombre y categoría."""
        self.lineEdit_search.clear()
        self.comboBox_category.setCurrentIndex(0)
    
    def apply_filters(self):
        """Aplica todos los filtros configurados."""
        freq_min = self.doubleSpinBox_freq_min.value() * 1e6
        freq_max = self.doubleSpinBox_freq_max.value() * 1e6
        bw_min = self.doubleSpinBox_bw_min.value() * 1e3
        bw_max = self.doubleSpinBox_bw_max.value() * 1e3
        
        cat_filter = self.comboBox_filter_category.currentData()
        mode_filter = self.comboBox_filter_mode.currentData()
        mod_filter = self.comboBox_filter_modulation.currentData()
        loc_filter = self.comboBox_filter_location.currentData()
        
        # Contar filtros activos
        active_count = 0
        if freq_min > 0 or freq_max < 6000e6:
            active_count += 1
        if bw_min > 0 or bw_max < 100e6:
            active_count += 1
        if cat_filter is not None:
            active_count += 1
        if mode_filter is not None:
            active_count += 1
        if mod_filter is not None:
            active_count += 1
        if loc_filter is not None:
            active_count += 1
        
        filtered = []
        for sig in self.signals:
            # Filtro de frecuencia
            if freq_min > 0 or freq_max < 6000e6:
                freqs = sig.get('frequencies', [])
                if not any(freq_min <= f.get('value', 0) <= freq_max for f in freqs):
                    continue
            
            # Filtro de ancho de banda
            if bw_min > 0 or bw_max < 100e6:
                bws = sig.get('bandwidths', [])
                if not any(bw_min <= b.get('value', 0) <= bw_max for b in bws):
                    continue
            
            # Filtros de texto
            if cat_filter is not None and cat_filter not in sig.get('categories', []):
                continue
            if mode_filter is not None and mode_filter not in sig.get('modes', []):
                continue
            if mod_filter is not None and mod_filter not in sig.get('modulations', []):
                continue
            if loc_filter is not None and loc_filter not in sig.get('locations', []):
                continue
            
            filtered.append(sig)
        
        self.filtered_signals = filtered
        self.filters_active = active_count > 0
        
        if self.filters_active:
            self.label_filter_badge.setText(f" {active_count} ")
            self.label_filter_badge.setVisible(True)
        else:
            self.label_filter_badge.setVisible(False)
        
        self.update_list()
        self.label_count.setText(f"{len(filtered)} / {len(self.signals)} señales")
        self.logger.info(f"🔍 Filtros aplicados: {len(filtered)} señales")
    
    def reset_all_filters(self):
        """Restablece todos los filtros."""
        self.doubleSpinBox_freq_min.setValue(0.0)
        self.doubleSpinBox_freq_max.setValue(6000.0)
        self.doubleSpinBox_bw_min.setValue(0.0)
        self.doubleSpinBox_bw_max.setValue(100000.0)
        
        self.comboBox_filter_category.setCurrentIndex(0)
        self.comboBox_filter_mode.setCurrentIndex(0)
        self.comboBox_filter_modulation.setCurrentIndex(0)
        self.comboBox_filter_location.setCurrentIndex(0)
        
        self.filters_active = False
        self.label_filter_badge.setVisible(False)
        
        # También limpiar búsqueda
        self.clear_search()
        
        self.filtered_signals = self.signals.copy()
        self.update_list()
        self.label_count.setText(f"{len(self.signals)} señales")
        self.logger.info("🗑️ Filtros reseteados")
    
    def clear_freq_filter(self):
        """Limpia solo el filtro de frecuencia."""
        self.doubleSpinBox_freq_min.setValue(0.0)
        self.doubleSpinBox_freq_max.setValue(6000.0)
        self.apply_filters()
    
    def clear_bw_filter(self):
        """Limpia solo el filtro de ancho de banda."""
        self.doubleSpinBox_bw_min.setValue(0.0)
        self.doubleSpinBox_bw_max.setValue(100000.0)
        self.apply_filters()
    
    # ------------------------------------------------------------------------
    # GESTIÓN DE LISTA DE SEÑALES
    # ------------------------------------------------------------------------
    
    def update_list(self):
        """Actualiza la lista de señales."""
        self.listWidget_signals.blockSignals(True)
        self.listWidget_signals.clear()
        
        for sig in self.filtered_signals:
            name = sig.get('name', 'Unknown')
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, sig.get('id', ''))
            
            freq = sig.get('frequencies', [{}])[0].get('value', 0) / 1_000_000 if sig.get('frequencies') else 0
            cats = sig.get('categories', [])
            
            tooltip_parts = []
            if freq > 0:
                tooltip_parts.append(f"📡 {freq:.3f} MHz")
            if cats:
                tooltip_parts.append(f"🏷️ {', '.join(cats[:3])}")
            
            item.setToolTip(" | ".join(tooltip_parts) if tooltip_parts else name)
            
            if self.tuned_signal_id and sig.get('id') == self.tuned_signal_id:
                item.setBackground(QColor(42, 74, 42))
            
            self.listWidget_signals.addItem(item)
        
        self.listWidget_signals.blockSignals(False)
    
    def on_signal_selected(self):
        """Muestra los detalles de la señal seleccionada."""
        selected = self.listWidget_signals.selectedItems()
        if not selected:
            self.pushButton_tune.setEnabled(False)
            return
        
        item = selected[0]
        signal_id = item.data(Qt.UserRole)
        
        for sig in self.filtered_signals:
            if sig.get('id') == signal_id:
                self.current_signal = sig
                self._display_signal_details(sig)
                self.label_tuned_status.setVisible(self.tuned_signal_id == signal_id)
                self.pushButton_tune.setEnabled(True)
                break
    
    def _display_signal_details(self, sig: dict):
        """Muestra los detalles de una señal."""
        name = sig.get('name', 'Unknown')
        self.label_signal_name.setText(f"📡 {name}")
        
        # Frecuencias
        freqs = sig.get('frequencies', [])
        if freqs:
            freq_lines = [format_frequency_line(f.get('value', 0), f.get('description', '')) for f in freqs]
            self.textEdit_frequencies.setPlainText("\n".join(freq_lines))
        else:
            self.textEdit_frequencies.setPlainText("   No especificada")
        
        # Anchos de banda
        bws = sig.get('bandwidths', [])
        if bws:
            bw_lines = [format_bandwidth_line(b.get('value', 0), b.get('description', '')) for b in bws]
            self.textEdit_bandwidths.setPlainText("\n".join(bw_lines))
        else:
            self.textEdit_bandwidths.setPlainText("   No especificado")
        
        mods = sig.get('modulations', [])
        self.label_mod_value.setText(", ".join(mods) if mods else "-")
        
        modes = sig.get('modes', [])
        self.label_mode_value.setText(", ".join(modes) if modes else "-")
        
        cats = sig.get('categories', [])
        self.label_category_value.setText(", ".join(cats) if cats else "-")
        
        locs = sig.get('locations', [])
        self.label_location_value.setText(", ".join(locs) if locs else "-")
        
        description = sig.get('description', 'Sin descripción')
        description = description.replace('#', '').replace('*', '')
        self.textEdit_description.setPlainText(description[:3000])
        
        self.show_waterfall(sig.get('waterfall_path', ''))
    
    def mark_as_tuned(self, signal_id: Optional[str]):
        """Marca una señal como sintonizada."""
        self.tuned_signal_id = signal_id
        
        if self.current_signal and self.current_signal.get('id') == signal_id:
            self.label_tuned_status.setVisible(True)
        else:
            self.label_tuned_status.setVisible(False)
        
        self.update_list()
        
        if signal_id:
            for i in range(self.listWidget_signals.count()):
                item = self.listWidget_signals.item(i)
                if item.data(Qt.UserRole) == signal_id:
                    self.listWidget_signals.setCurrentItem(item)
                    break
    
    # ------------------------------------------------------------------------
    # INTERACCIÓN CON FRECUENCIAS
    # ------------------------------------------------------------------------
    
    def on_frequencies_click(self, event):
        """Maneja click en el área de frecuencias."""
        if not self.current_signal:
            return
        
        cursor = self.textEdit_frequencies.cursorForPosition(event.pos())
        cursor.select(QTextCursor.LineUnderCursor)
        line = cursor.selectedText()
        
        if line and line.strip() and "No especificada" not in line:
            freq_mhz = parse_frequency_from_line(line)
            if freq_mhz > 0:
                self.signal_selected.emit(freq_mhz)
                if self.current_signal:
                    self.mark_as_tuned(self.current_signal.get('id'))
                self.logger.info(f"🎯 Sintonizando {freq_mhz:.3f} MHz")
    
    def on_bandwidths_click(self, event):
        """Maneja click en el área de anchos de banda."""
        pass
    
    def on_tune_clicked(self):
        """Sintoniza la primera frecuencia de la señal seleccionada."""
        if self.current_signal:
            freqs = self.current_signal.get('frequencies', [])
            if freqs:
                freq_mhz = freqs[0].get('value', 0) / 1_000_000
                if freq_mhz > 0:
                    self.signal_selected.emit(freq_mhz)
                    self.mark_as_tuned(self.current_signal.get('id'))
    
    # ------------------------------------------------------------------------
    # MENÚ CONTEXTUAL
    # ------------------------------------------------------------------------
    
    def show_context_menu(self, pos):
        """Muestra menú contextual."""
        item = self.listWidget_signals.itemAt(pos)
        if not item:
            return
        
        signal_id = item.data(Qt.UserRole)
        signal = next((s for s in self.filtered_signals if s.get('id') == signal_id), None)
        if not signal:
            return
        
        menu = QMenu(self)
        
        freqs = signal.get('frequencies', [])
        if freqs:
            first_freq = freqs[0].get('value', 0) / 1e6
            action_tune = QAction(f"🎯 Sintonizar {first_freq:.3f} MHz", self)
            action_tune.triggered.connect(lambda: self._tune_to_signal(signal))
            menu.addAction(action_tune)
        
        if len(freqs) > 1:
            freq_menu = menu.addMenu("📡 Sintonizar frecuencia...")
            for f in freqs:
                freq_mhz = f.get('value', 0) / 1e6
                desc = f.get('description', '')
                label = f"{freq_mhz:.3f} MHz"
                if desc:
                    label += f" ({desc[:20]})"
                action = QAction(label, self)
                action.triggered.connect(lambda checked, fm=freq_mhz: self.signal_selected.emit(fm))
                freq_menu.addAction(action)
        
        menu.addSeparator()
        action_copy = QAction("📋 Copiar nombre", self)
        action_copy.triggered.connect(lambda: QApplication.clipboard().setText(signal.get('name', '')))
        menu.addAction(action_copy)
        
        menu.exec_(self.listWidget_signals.mapToGlobal(pos))
    
    def _tune_to_signal(self, signal: dict):
        """Sintoniza la primera frecuencia de la señal."""
        freqs = signal.get('frequencies', [])
        if freqs:
            freq_mhz = freqs[0].get('value', 0) / 1e6
            self.signal_selected.emit(freq_mhz)
            self.mark_as_tuned(signal.get('id'))
    
    # ------------------------------------------------------------------------
    # WATERFALL
    # ------------------------------------------------------------------------
    
    def show_waterfall(self, image_path: str):
        """Muestra la imagen de waterfall."""
        if image_path and os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.label_waterfall.width() - 20,
                    self.label_waterfall.height() - 20,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.label_waterfall.setPixmap(scaled)
                self.label_waterfall.setText("")
                return
        
        self.label_waterfall.setText("📡 No hay imagen disponible\n\nSelecciona una señal con waterfall")
        self.label_waterfall.setPixmap(QPixmap())
    
    # ------------------------------------------------------------------------
    # UTILIDADES
    # ------------------------------------------------------------------------
    
    def force_refresh(self):
        """Fuerza un refresco completo de la UI."""
        if not self.signals:
            return
        
        self.update_list()
        
        current_cat = self.comboBox_category.currentData()
        self.comboBox_category.blockSignals(True)
        self.comboBox_category.clear()
        self.comboBox_category.addItem("📋 TODAS LAS CATEGORÍAS", None)
        for cat in sorted(self.all_categories):
            self.comboBox_category.addItem(cat, cat)
        
        index = self.comboBox_category.findData(current_cat)
        self.comboBox_category.setCurrentIndex(index if index >= 0 else 0)
        self.comboBox_category.blockSignals(False)
        
        self.label_count.setText(f"{len(self.filtered_signals)} / {len(self.signals)} señales")
        
        if self.current_signal:
            self.on_signal_selected()
        
        self.repaint()
        QApplication.processEvents()
    
    def resizeEvent(self, event):
        """Maneja el redimensionamiento del widget."""
        if hasattr(self, 'label_waterfall'):
            if self.label_waterfall.pixmap() and not self.label_waterfall.pixmap().isNull():
                scaled = self.label_waterfall.pixmap().scaled(
                    self.label_waterfall.width() - 20,
                    self.label_waterfall.height() - 20,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.label_waterfall.setPixmap(scaled)
        super().resizeEvent(event)
    
    def closeEvent(self, event):
        """Asegura que el hilo de carga se detenga al cerrar."""
        if self.loader and self.loader.isRunning():
            self.loader.terminate()
            self.loader.wait(1000)
        event.accept()
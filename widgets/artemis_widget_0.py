# -*- coding: utf-8 -*-

"""
Artemis Database Widget for SIMANEEM
=====================================
Widget de base de datos de señales Artemis.
"""

import os
import json
import re
import logging
from PyQt5.QtWidgets import QDockWidget, QMessageBox, QFileDialog, QApplication
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QColor, QPixmap, QTextCursor
from PyQt5.uic import loadUi


# ============================================================================
# FUNCIONES DE FORMATEO
# ============================================================================

def parse_frequency_from_line(line: str) -> float:
    """Extrae el valor numérico en MHz de una línea de frecuencia"""
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
    """Formatea una frecuencia en Hz a una línea legible"""
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
    """Formatea un ancho de banda en Hz a una línea legible"""
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
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list, list)
    error = pyqtSignal(str)
    
    def __init__(self, base_path: str):
        super().__init__()
        self.base_path = base_path
    
    def run(self):
        try:
            signals = []
            all_categories = set()
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
                
                if idx % 10 == 0:
                    self.progress.emit(idx, total)
            
            self.progress.emit(total, total)
            self.finished.emit(signals, sorted(list(all_categories)))
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _load_signal(self, folder_path: str, folder_id: str) -> dict:
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
    signal_selected = pyqtSignal(float)
    database_loaded = pyqtSignal()  # NUEVA SEÑAL para notificar cambio
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        loadUi('ui/artemis_widget.ui', self)
        
        self.signals = []
        self.filtered_signals = []
        self.current_signal = None
        self.loader = None
        self.base_path = ""
        self._loading_in_progress = False 
        
        self.setup_ui()
        self.setup_connections()  
        
        # Estado inicial: TODO BLOQUEADO excepto botón de carga
        self.set_controls_enabled(False)
        self.pushButton_load.setEnabled(True)
        
        # Mensaje inicial
        self.show_initial_message()
        
        self.logger.info("✅ ArtemisWidget inicializado (modo bloqueado)")
    
    def setup_ui(self):
        """Configura elementos adicionales de la UI"""
        self.splitter_main.setSizes([350, 650])
        self.comboBox_category.clear()
        self.comboBox_category.addItem("📋 TODAS")
        
        # Configurar text edits
        self.textEdit_frequencies.setLineWrapMode(0)
        self.textEdit_bandwidths.setLineWrapMode(0)
        
        # Conectar eventos de click
        self.textEdit_frequencies.mousePressEvent = self.on_frequencies_click
        self.textEdit_bandwidths.mousePressEvent = self.on_bandwidths_click
        
        # Estilo para cursor de mano
        self.textEdit_frequencies.setCursor(Qt.PointingHandCursor)
        self.textEdit_bandwidths.setCursor(Qt.ArrowCursor)
    
    def setup_connections(self):
        """Conecta las señales de los widgets de la UI"""
        self.lineEdit_search.textChanged.connect(self.filter_signals)
        self.comboBox_category.currentIndexChanged.connect(self.filter_signals)
        self.listWidget_signals.itemSelectionChanged.connect(self.on_signal_selected)
        self.pushButton_load.clicked.connect(self.load_database)
        self.pushButton_refresh.clicked.connect(self.refresh_database)
        self.pushButton_tune.clicked.connect(self.on_tune_clicked)
        self.pushButton_clear.clicked.connect(self.clear_search)
    
    def show_initial_message(self):
        """Muestra el mensaje inicial cuando no hay datos"""
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
    
    def set_controls_enabled(self, enabled: bool):
        """Habilita o deshabilita todos los controles excepto el botón de carga"""
        self.pushButton_refresh.setEnabled(enabled)
        self.pushButton_tune.setEnabled(enabled)
        self.lineEdit_search.setEnabled(enabled)
        self.comboBox_category.setEnabled(enabled)
        self.listWidget_signals.setEnabled(enabled)
        self.textEdit_frequencies.setEnabled(enabled)
        self.textEdit_bandwidths.setEnabled(enabled)
        self.textEdit_description.setEnabled(enabled)
        self.tabWidget.setEnabled(enabled)

        # Forzar actualización visual de los widgets habilitados/deshabilitados
        if enabled:
            self.listWidget_signals.repaint()
            self.comboBox_category.repaint()
    
    def load_database(self):
        """Carga la base de datos desde una carpeta seleccionada"""
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
        self.pushButton_load.setEnabled(False)
        self.progressBar.setVisible(True)
        self.listWidget_signals.clear()
        
        # Mostrar mensaje de carga
        self.label_signal_name.setText("📡 Cargando base de datos...")
        self.label_count.setText("Cargando señales...")
        QApplication.processEvents()
        
        self.loader = ArtemisLoaderThread(folder)
        self.loader.progress.connect(self.update_progress)
        self.loader.finished.connect(self.on_load_finished)
        self.loader.error.connect(self.on_load_error)
        self.loader.start()

    def auto_load_from_config(self, db_path: str):
        """
        Carga la base de datos desde una ruta de configuración.
        Llamado SOLO UNA VEZ desde config_manager después de cargar la configuración.
        """
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
        self._loading_in_progress = True
        self.pushButton_load.setEnabled(False)
        self.progressBar.setVisible(True)
        self.listWidget_signals.clear()
        
        self.label_signal_name.setText("📡 Cargando base de datos...")
        self.label_count.setText("Cargando señales...")
        QApplication.processEvents()
        
        self.loader = ArtemisLoaderThread(db_path)
        self.loader.progress.connect(self.update_progress)
        self.loader.finished.connect(self.on_load_finished)
        self.loader.error.connect(self.on_load_error)
        self.loader.start()
    
    def refresh_database(self):
        if self.base_path:
            self.load_database()
    
    def update_progress(self, current, total):
        if total > 0:
            self.progressBar.setValue(int(current * 100 / total))
            QApplication.processEvents()
    
    def on_load_finished(self, signals, categories):
        """Finaliza la carga y actualiza la UI"""
        self.signals = signals
        self.filtered_signals = signals
        self.all_categories = categories  # Guardar para refrescos
        
        # Actualizar combo de categorías
        self.comboBox_category.blockSignals(True)
        self.comboBox_category.clear()
        self.comboBox_category.addItem("📋 TODAS")
        for cat in categories:
            self.comboBox_category.addItem(cat)
        self.comboBox_category.blockSignals(False)
        
        # Actualizar lista de señales
        self.update_list()
        
        # Ocultar barra de progreso
        self.progressBar.setVisible(False)
        self.pushButton_load.setEnabled(True)
        
        # Actualizar contador
        self.label_count.setText(f"{len(signals)} señales")
        
        # Desbloquear todos los controles
        self.set_controls_enabled(True)
        
        # Forzar actualización de todos los widgets
        self.listWidget_signals.repaint()
        self.comboBox_category.repaint()
        self.label_count.repaint()
        self.label_signal_name.repaint()
        
        # Seleccionar primera señal automáticamente
        if self.listWidget_signals.count() > 0:
            self.listWidget_signals.setCurrentRow(0)
            QApplication.processEvents()
            self.on_signal_selected()
        
        # Forzar refresco completo adicional
        self.force_refresh()
        
        # Forzar repaint del widget completo y sus padres
        self.repaint()
        self.update()
        
        if self.parent():
            self.parent().repaint()
            self.parent().update()
        
        # Procesar eventos pendientes
        QApplication.processEvents()
        QApplication.sendPostedEvents()
        
        # NOTIFICAR QUE SE CARGÓ
        self._loading_in_progress = False
        self.database_loaded.emit()
        
        self.logger.info(f"✅ Base de datos Artemis cargada: {len(signals)} señales")
    
    def on_load_error(self, error):
        self.progressBar.setVisible(False)
        self.pushButton_load.setEnabled(True)
        self.logger.error(f"Error cargando Artemis-DB: {error}")
        
        self.label_signal_name.setText("❌ Error al cargar")
        self.label_count.setText("0 señales")
        self.textEdit_frequencies.setPlainText("   Error al cargar la base de datos")
        
        QMessageBox.warning(self, "Error de Carga", f"No se pudo cargar la base de datos:\n{error}")
    
    def filter_signals(self):
        if not self.signals:
            return
        
        search = self.lineEdit_search.text().lower()
        category = self.comboBox_category.currentText()
        
        if category == "📋 TODAS":
            category = None
        
        filtered = []
        for sig in self.signals:
            if category and category not in sig.get('categories', []):
                continue
            if search and search not in sig.get('name', '').lower():
                continue
            filtered.append(sig)
        
        self.filtered_signals = filtered
        self.update_list()
        self.label_count.setText(f"{len(filtered)} / {len(self.signals)} señales")
    
    def update_list(self):
        """Actualiza la lista de señales"""
        self.listWidget_signals.blockSignals(True)
        self.listWidget_signals.clear()
        
        for sig in self.filtered_signals:
            name = sig.get('name', 'Unknown')
            self.listWidget_signals.addItem(name)
            
            # Tooltip con información
            freq = sig.get('frequencies', [{}])[0].get('value', 0) / 1_000_000 if sig.get('frequencies') else 0
            cats = sig.get('categories', [])
            if freq > 0:
                self.listWidget_signals.item(self.listWidget_signals.count() - 1).setToolTip(
                    f"📡 {freq:.3f} MHz | 🏷️ {', '.join(cats[:2]) if cats else 'Sin categoría'}"
                )
            elif cats:
                self.listWidget_signals.item(self.listWidget_signals.count() - 1).setToolTip(
                    f"🏷️ {', '.join(cats[:2]) if cats else 'Sin categoría'}"
                )
        
        self.listWidget_signals.blockSignals(False)
        
        # Forzar actualización visual
        self.listWidget_signals.repaint()
        self.listWidget_signals.update()
        QApplication.processEvents()
    
    def clear_search(self):
        self.lineEdit_search.clear()
        self.comboBox_category.setCurrentIndex(0)
    
    def on_signal_selected(self):
        """Muestra los detalles de la señal seleccionada"""
        selected = self.listWidget_signals.selectedItems()
        if not selected:
            self.pushButton_tune.setEnabled(False)
            return
        
        selected_name = selected[0].text()
        
        for sig in self.filtered_signals:
            if sig.get('name') == selected_name:
                self.current_signal = sig
                
                # Nombre de la señal
                name = sig.get('name', 'Unknown')
                self.label_signal_name.setText(f"📡 {name}")
                
                # FRECUENCIAS
                freqs = sig.get('frequencies', [])
                if freqs:
                    freq_lines = []
                    for f in freqs:
                        line = format_frequency_line(f.get('value', 0), f.get('description', ''))
                        freq_lines.append(line)
                    self.textEdit_frequencies.setPlainText("\n".join(freq_lines))
                    self.adjust_text_height(self.textEdit_frequencies)
                else:
                    self.textEdit_frequencies.setPlainText("   No especificada")
                    self.textEdit_frequencies.setMaximumHeight(50)
                
                # ANCHOS DE BANDA
                bws = sig.get('bandwidths', [])
                if bws:
                    bw_lines = []
                    for bw in bws:
                        line = format_bandwidth_line(bw.get('value', 0), bw.get('description', ''))
                        bw_lines.append(line)
                    self.textEdit_bandwidths.setPlainText("\n".join(bw_lines))
                    self.adjust_text_height(self.textEdit_bandwidths)
                else:
                    self.textEdit_bandwidths.setPlainText("   No especificado")
                    self.textEdit_bandwidths.setMaximumHeight(50)
                
                # Modulación
                mods = sig.get('modulations', [])
                self.label_mod_value.setText(", ".join(mods) if mods else "-")
                
                # Modo
                modes = sig.get('modes', [])
                self.label_mode_value.setText(", ".join(modes) if modes else "-")
                
                # Categoría
                cats = sig.get('categories', [])
                self.label_category_value.setText(", ".join(cats) if cats else "-")
                
                # Ubicación
                locs = sig.get('locations', [])
                self.label_location_value.setText(", ".join(locs) if locs else "-")
                
                # Descripción
                description = sig.get('description', 'Sin descripción')
                description = description.replace('#', '').replace('*', '')
                self.textEdit_description.setPlainText(description[:3000])
                
                # Waterfall
                self.show_waterfall(sig.get('waterfall_path', ''))
                
                self.pushButton_tune.setEnabled(True)
                
                # Forzar actualización
                QApplication.processEvents()
                break
    
    def adjust_text_height(self, text_edit):
        """Ajusta la altura del QTextEdit según su contenido"""
        doc = text_edit.document()
        height = doc.size().height()
        text_edit.setMaximumHeight(int(height) + 15)
        text_edit.setMinimumHeight(int(height) + 5)
    
    def on_frequencies_click(self, event):
        """Maneja click en el área de frecuencias"""
        if not self.current_signal:
            return
            
        cursor = self.textEdit_frequencies.cursorForPosition(event.pos())
        cursor.select(QTextCursor.LineUnderCursor)
        line = cursor.selectedText()
        
        if line and line.strip() and "No especificada" not in line and "No hay datos" not in line:
            freq_mhz = parse_frequency_from_line(line)
            if freq_mhz > 0:
                self.signal_selected.emit(freq_mhz)
                self.logger.info(f"🎯 Sintonizando {freq_mhz:.3f} MHz desde lista de frecuencias")
                # Feedback visual temporal
                self.textEdit_frequencies.setStyleSheet(
                    "background-color: #2a2a2a; color: #dddddd; border: 1px solid #ffaa44; border-radius: 4px; font-family: monospace; font-size: 9pt;"
                )
                QTimer.singleShot(500, lambda: self.textEdit_frequencies.setStyleSheet(
                    "background-color: #1e1e1e; color: #dddddd; border: 1px solid #404040; border-radius: 4px; font-family: monospace; font-size: 9pt;"
                ))
    
    def on_bandwidths_click(self, event):
        """Maneja click en el área de anchos de banda"""
        if not self.current_signal:
            return
            
        self.textEdit_bandwidths.setStyleSheet(
            "background-color: #2a2a2a; color: #dddddd; border: 1px solid #404040; border-radius: 4px; font-family: monospace; font-size: 9pt;"
        )
        QTimer.singleShot(500, lambda: self.textEdit_bandwidths.setStyleSheet(
            "background-color: #1e1e1e; color: #dddddd; border: 1px solid #404040; border-radius: 4px; font-family: monospace; font-size: 9pt;"
        ))
    
    def show_waterfall(self, image_path: str):
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
        
        self.label_waterfall.setText("📡 No hay imagen disponible\n\nSelecciona una señal")
        self.label_waterfall.setPixmap(QPixmap())
    
    def on_tune_clicked(self):
        if self.current_signal:
            freqs = self.current_signal.get('frequencies', [])
            if freqs:
                freq_hz = freqs[0].get('value', 0)
                freq_mhz = freq_hz / 1_000_000
                if freq_mhz > 0:
                    self.signal_selected.emit(freq_mhz)
                    self.logger.info(f"🎯 Sintonizando {freq_mhz:.3f} MHz - {self.current_signal.get('name')}")
    
    def resizeEvent(self, event):
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
        if self.loader and self.loader.isRunning():
            self.loader.terminate()
            self.loader.wait(1000)
        event.accept()


    # widgets/artemis_widget.py - Añadir método force_refresh

    def force_refresh(self):
        """Fuerza un refresco completo de la UI"""
        if not self.signals:
            return
        
        # Refrescar lista
        self.update_list()
        
        # Refrescar combo de categorías
        current_cat = self.comboBox_category.currentText()
        self.comboBox_category.blockSignals(True)
        self.comboBox_category.clear()
        self.comboBox_category.addItem("📋 TODAS")
        for cat in self.all_categories:
            self.comboBox_category.addItem(cat)
        # Restaurar selección
        index = self.comboBox_category.findText(current_cat)
        if index >= 0:
            self.comboBox_category.setCurrentIndex(index)
        else:
            self.comboBox_category.setCurrentIndex(0)
        self.comboBox_category.blockSignals(False)
        
        # Refrescar contador
        self.label_count.setText(f"{len(self.filtered_signals)} / {len(self.signals)} señales")
        
        # Si hay señal seleccionada, refrescar detalles
        if self.current_signal:
            self.on_signal_selected()
        
        # Forzar repaint
        self.repaint()
        self.update()
        QApplication.processEvents()
        
        self.logger.debug("🔄 UI refrescada manualmente")
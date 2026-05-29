# -*- coding: utf-8 -*-

"""
TSCM Widget - Herramienta de Análisis Diferencial
=================================================
Widget profesional para el modo TSCM con gráfico de barras.
"""

import logging
import csv
import os
from datetime import datetime
from PyQt5.QtWidgets import (QDockWidget, QFileDialog, QMessageBox, 
                             QVBoxLayout, QWidget)
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QColor
from PyQt5.uic import loadUi


class TSCMWidget(QDockWidget):
    """
    Widget para análisis TSCM / Modo Diferencias.
    """
    
    # Señales
    tscm_capture_baseline = pyqtSignal()
    tscm_mode_toggled = pyqtSignal(bool)
    tscm_threshold_changed = pyqtSignal(float)
    tscm_dwell_changed = pyqtSignal(int)
    tscm_clear_baseline = pyqtSignal()
    tscm_export_log = pyqtSignal()
    tscm_sound_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # Cargar UI
        loadUi('ui/tscm_widget.ui', self)
        
        # Estado interno
        self.diff_mode_active = False
        self._capturing_progress = False
        self._current_detections = []
        self._detection_history = []  # Para exportación
        
        # Referencia al controller
        self.main_controller = None
        
        # Sonido
        self._sound_enabled = False
        self._last_alert_time = 0
        self._alert_cooldown = 2000
        
        # Configurar UI
        self._setup_ui()
        self._setup_connections()
        self._setup_chart()  # Crear gráfico en lugar de tabla
        
        self.logger.info("✅ TSCMWidget inicializado (con gráfico de barras)")

    def set_main_controller(self, controller):
        self.main_controller = controller
        self.logger.info("🔗 TSCMWidget conectado al MainController")
        
        if controller and hasattr(controller, 'tscm_ctrl'):
            has_baseline = controller.tscm_ctrl.has_baseline()
            self.update_baseline_status(has_baseline)

    def _setup_ui(self):
        """Configura el estado inicial de la UI."""
        # Estado baseline
        if hasattr(self, 'label_baseline_icon'):
            self.label_baseline_icon.setText("⚪")
        
        if hasattr(self, 'label_baseline_status'):
            self.label_baseline_status.setText("SIN BASELINE")
        
        if hasattr(self, 'label_mode_indicator'):
            self.label_mode_indicator.setText("INACTIVO")
            self.label_mode_indicator.setStyleSheet("color: #888888;")
        
        # Botón de modo diferencias
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setChecked(False)
            self.pushButton_diff_mode.setEnabled(False)
            self.pushButton_diff_mode.setText("▶ ACTIVAR MODO Δ")
        
        # Parámetros
        if hasattr(self, 'doubleSpinBox_threshold'):
            self.doubleSpinBox_threshold.setValue(4.0)
        
        if hasattr(self, 'spinBox_dwell'):
            self.spinBox_dwell.setValue(200)
        
        # Estadísticas
        if hasattr(self, 'label_active_alerts'):
            self.label_active_alerts.setText("0")
            self.label_active_alerts.setStyleSheet("font-size: 20pt; font-weight: bold; color: #00ff00;")
        
        if hasattr(self, 'label_last_alert'):
            self.label_last_alert.setText("--:--:--")
        
        # Barra de progreso
        if hasattr(self, 'progressBar_capture'):
            self.progressBar_capture.setVisible(False)
        
        # Botón exportar
        if hasattr(self, 'pushButton_export_log'):
            self.pushButton_export_log.setEnabled(False)

    def _setup_chart(self):
        """Crea el widget de gráfico TSCM."""
        from widgets.tscm_chart import TSCMChartWidget
        
        self.tscm_chart = TSCMChartWidget(self)
        self.tscm_chart.frequency_selected.connect(self._on_chart_frequency_selected)
        self.tscm_chart.cleared.connect(self._on_history_cleared)
        
        # Añadir al layout principal
        if hasattr(self, 'verticalLayout_main'):
            self.verticalLayout_main.addWidget(self.tscm_chart)
        
        self.logger.info("✅ Gráfico TSCM añadido")

    def _setup_connections(self):
        """Conecta las señales internas."""
        if hasattr(self, 'pushButton_capture_baseline'):
            self.pushButton_capture_baseline.clicked.connect(self._on_capture_baseline)
        
        if hasattr(self, 'pushButton_clear_baseline'):
            self.pushButton_clear_baseline.clicked.connect(self._on_clear_baseline)
        
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.toggled.connect(self._on_diff_mode_toggled)
        
        if hasattr(self, 'doubleSpinBox_threshold'):
            self.doubleSpinBox_threshold.valueChanged.connect(self.tscm_threshold_changed)
        
        if hasattr(self, 'spinBox_dwell'):
            self.spinBox_dwell.valueChanged.connect(self.tscm_dwell_changed)
        
        if hasattr(self, 'pushButton_export_log'):
            #self.pushButton_export_log.clicked.connect(self._on_export_clicked)
            self.pushButton_export_log.clicked.connect(self.export_historical_log)  # Cambiar a nuevo método
        
        if hasattr(self, 'checkBox_sound_alert'):
            self.checkBox_sound_alert.toggled.connect(self._on_sound_toggled)

    # ------------------------------------------------------------------------
    # SLOTS INTERNOS
    # ------------------------------------------------------------------------

    def _on_capture_baseline(self):
        self.logger.info("📸 Captura de baseline solicitada")
        if hasattr(self, 'pushButton_capture_baseline'):
            self.pushButton_capture_baseline.setEnabled(False)
        self.tscm_capture_baseline.emit()

    def _on_clear_baseline(self):
        self.logger.info("🗑️ Limpiar baseline solicitado")
        self.tscm_clear_baseline.emit()

    def _on_diff_mode_toggled(self, checked):
        self.logger.info(f"Modo Diferencias toggled: {checked}")
        
        has_baseline = False
        if self.main_controller and hasattr(self.main_controller, 'tscm_ctrl'):
            has_baseline = self.main_controller.tscm_ctrl.has_baseline()
        
        if checked and not has_baseline:
            self.logger.warning("No se puede activar modo Δ sin baseline")
            self.pushButton_diff_mode.blockSignals(True)
            self.pushButton_diff_mode.setChecked(False)
            self.pushButton_diff_mode.blockSignals(False)
            return
        
        self.diff_mode_active = checked
        
        if hasattr(self, 'pushButton_diff_mode'):
            if checked:
                self.pushButton_diff_mode.setText("⏹ DETENER MODO Δ")
                self.pushButton_diff_mode.setStyleSheet(
                    "background-color: #44aa44; color: white; font-weight: bold;"
                )
            else:
                self.pushButton_diff_mode.setText("▶ ACTIVAR MODO Δ")
                self.pushButton_diff_mode.setStyleSheet("")
        
        self.tscm_mode_toggled.emit(checked)

    def _on_export_clicked(self):
        self.tscm_export_log.emit()
        self._export_to_csv()

    def _on_sound_toggled(self, checked):
        self._sound_enabled = checked
        self.logger.info(f"🔊 Sonido alerta: {'activado' if checked else 'desactivado'}")
        self.tscm_sound_toggled.emit(checked)

    def _on_chart_frequency_selected(self, freq_mhz):
        """Sintoniza la frecuencia seleccionada en el gráfico."""
        if self.main_controller:
            self.main_controller.on_frequency_changed_from_plot(freq_mhz)
            self.main_controller.statusbar.showMessage(
                f"🎯 Sintonizando {freq_mhz:.4f} MHz", 2000
            )

    def _on_history_cleared(self):
        """Maneja limpieza de historial."""
        self.logger.info("🗑️ Historial limpiado desde el gráfico")

    # ------------------------------------------------------------------------
    # MÉTODOS PÚBLICOS
    # ------------------------------------------------------------------------

    def update_baseline_status(self, has_baseline: bool):
        self.logger.info(f"📊 update_baseline_status: has_baseline={has_baseline}")
        
        if hasattr(self, 'label_baseline_icon'):
            if has_baseline:
                self.label_baseline_icon.setText("🟢")
                self.label_baseline_icon.setStyleSheet("color: #00ff00;")
            else:
                self.label_baseline_icon.setText("⚪")
                self.label_baseline_icon.setStyleSheet("color: #888888;")
        
        if hasattr(self, 'label_baseline_status'):
            if has_baseline:
                self.label_baseline_status.setText("BASELINE OK")
                self.label_baseline_status.setStyleSheet("font-weight: bold; color: #00ff00;")
            else:
                self.label_baseline_status.setText("SIN BASELINE")
                self.label_baseline_status.setStyleSheet("color: #888888;")
        
        if hasattr(self, 'label_mode_indicator'):
            if has_baseline:
                self.label_mode_indicator.setText("BASELINE OK")
                self.label_mode_indicator.setStyleSheet("color: #00ff00;")
            else:
                self.label_mode_indicator.setText("INACTIVO")
                self.label_mode_indicator.setStyleSheet("color: #888888;")
        
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setEnabled(has_baseline)
        
        if hasattr(self, 'pushButton_export_log'):
            self.pushButton_export_log.setEnabled(has_baseline)
        
        if hasattr(self, 'pushButton_capture_baseline'):
            self.pushButton_capture_baseline.setEnabled(True)

    def set_diff_mode_active(self, active: bool):
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setChecked(active)
        self.diff_mode_active = active

    def set_capturing_progress(self, active: bool, progress: int = 0):
        self._capturing_progress = active
        
        if hasattr(self, 'progressBar_capture'):
            self.progressBar_capture.setVisible(active)
            if active:
                self.progressBar_capture.setValue(progress)
                self.progressBar_capture.setFormat(f"Capturando... {progress}%")
            else:
                self.progressBar_capture.setValue(0)
        
        if hasattr(self, 'pushButton_capture_baseline'):
            if active:
                self.pushButton_capture_baseline.setEnabled(False)
                self.pushButton_capture_baseline.setText("⏳ CAPTURANDO...")
            else:
                self.pushButton_capture_baseline.setEnabled(True)
                self.pushButton_capture_baseline.setText("📸 CAPTURAR BASELINE")

    def update_stats(self, alert_count: int, detections: list = None):
        """
        Actualiza estadísticas y gráfico.
        
        Args:
            alert_count: Número total de bins en alerta
            detections: Lista de detecciones del controller
        """
        # Actualizar contador
        if hasattr(self, 'label_active_alerts'):
            self.label_active_alerts.setText(str(alert_count))
            if alert_count > 0:
                self.label_active_alerts.setStyleSheet(
                    "font-size: 20pt; font-weight: bold; color: #ff4444;"
                )
            else:
                self.label_active_alerts.setStyleSheet(
                    "font-size: 20pt; font-weight: bold; color: #00ff00;"
                )
        
        # Actualizar hora última alerta
        if alert_count > 0 and hasattr(self, 'label_last_alert'):
            self.label_last_alert.setText(datetime.now().strftime("%H:%M:%S"))
            self.label_last_alert.setStyleSheet(
                "font-size: 11pt; font-weight: bold; color: #ff8844;"
            )
        
        # Guardar para exportación
        if detections:
            self._current_detections = detections
            for det in detections:
                self._detection_history.append({
                    'timestamp': datetime.now().isoformat(),
                    'freq': det.get('freq', 0),
                    'power': det.get('power', -100),
                    'bandwidth': det.get('bandwidth', 0),
                    'snr': det.get('snr', 0),
                    'type': det.get('type', 'Desconocido')
                })
        
        # Actualizar gráfico
        if hasattr(self, 'tscm_chart') and detections:
            # Obtener rango de frecuencia actual
            freq_min = 0
            freq_max = 0
            center_freq = 0
            
            if self.main_controller and self.main_controller.bladerf:
                center_freq = self.main_controller.bladerf.frequency / 1e6
                sample_rate = self.main_controller.bladerf.sample_rate / 1e6
                freq_min = center_freq - sample_rate / 2
                freq_max = center_freq + sample_rate / 2
            else:
                freq_min = 2382
                freq_max = 2438
            
            self.tscm_chart.update_detections(detections, freq_min, freq_max)
        
        # Alerta sonora
        if self._sound_enabled and detections and len(detections) > 0:
            self._play_alert_sound(detections)

    def reset_stats(self):
        """Reinicia las estadísticas."""
        if hasattr(self, 'label_active_alerts'):
            self.label_active_alerts.setText("0")
            self.label_active_alerts.setStyleSheet(
                "font-size: 20pt; font-weight: bold; color: #00ff00;"
            )
        
        if hasattr(self, 'label_last_alert'):
            self.label_last_alert.setText("--:--:--")
        
        # Limpiar histórico de detecciones
        self._detection_history = []
        self._current_detections = []
        
        if hasattr(self, 'tscm_chart'):
            self.tscm_chart.clear_historical()

    def set_controls_enabled(self, enabled: bool):
        if hasattr(self, 'pushButton_capture_baseline'):
            self.pushButton_capture_baseline.setEnabled(enabled)
        if hasattr(self, 'pushButton_clear_baseline'):
            self.pushButton_clear_baseline.setEnabled(enabled)

    def _export_to_csv(self):
        """Exporta el historial de detecciones a CSV."""
        if not self._detection_history:
            QMessageBox.information(self, "Exportar", "No hay datos para exportar")
            return
        
        try:
            os.makedirs("tscm_logs", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"tscm_logs/tscm_detecciones_{timestamp}.csv"
            
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Timestamp', 'Frecuencia (MHz)', 'Potencia (dB)', 
                    'Ancho Banda (MHz)', 'SNR (dB)', 'Tipo'
                ])
                
                for det in self._detection_history:
                    writer.writerow([
                        det['timestamp'],
                        f"{det['freq']:.4f}",
                        f"{det['power']:.1f}",
                        f"{det['bandwidth']:.2f}",
                        f"{det['snr']:.1f}",
                        det['type']
                    ])
            
            QMessageBox.information(
                self, "Exportar", 
                f"✅ {len(self._detection_history)} detecciones exportadas a:\n{filename}"
            )
            self.logger.info(f"📤 Exportadas {len(self._detection_history)} detecciones a {filename}")
            
        except Exception as e:
            self.logger.error(f"Error exportando: {e}")
            QMessageBox.warning(self, "Error", f"Error al exportar:\n{e}")

    def export_historical_log(self):
        """Exporta el log completo de señales activas a CSV."""
        if not hasattr(self, 'tscm_chart'):
            QMessageBox.warning(self, "Exportar", "Gráfico no disponible")
            return
        
        historical_data = self.tscm_chart.get_historical_data()
        
        if not historical_data and not self._detection_history:
            QMessageBox.information(self, "Exportar", "No hay datos para exportar")
            return
        
        try:
            os.makedirs("tscm_logs", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Exportar histórico de frecuencias
            filename_hist = f"tscm_logs/tscm_historial_{timestamp}.csv"
            with open(filename_hist, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Frecuencia (MHz)', 'Detecciones', 'Intensidad'])
                
                max_count = max([d['detection_count'] for d in historical_data]) if historical_data else 1
                for item in historical_data:
                    intensity = int(100 * item['detection_count'] / max_count)
                    writer.writerow([
                        f"{item['frequency_mhz']:.4f}",
                        item['detection_count'],
                        f"{intensity}%"
                    ])
            
            # Exportar detecciones por tiempo
            filename_det = f"tscm_logs/tscm_detecciones_{timestamp}.csv"
            with open(filename_det, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Timestamp', 'Frecuencia (MHz)', 'Potencia (dB)', 
                    'Ancho Banda (MHz)', 'SNR (dB)', 'Tipo'
                ])
                
                for det in self._detection_history:
                    writer.writerow([
                        det['timestamp'],
                        f"{det['freq']:.4f}",
                        f"{det['power']:.1f}",
                        f"{det['bandwidth']:.2f}",
                        f"{det['snr']:.1f}",
                        det['type']
                    ])
            
            QMessageBox.information(
                self, "Exportar", 
                f"✅ Datos exportados:\n"
                f"📊 Historial: {filename_hist}\n"
                f"📋 Detecciones: {filename_det}\n"
                f"Total: {len(historical_data)} frecuencias, {len(self._detection_history)} eventos"
            )
            self.logger.info(f"📤 Exportados {len(historical_data)} frecuencias y {len(self._detection_history)} eventos")
            
        except Exception as e:
            self.logger.error(f"Error exportando: {e}")
            QMessageBox.warning(self, "Error", f"Error al exportar:\n{e}")

    def _play_alert_sound(self, detections):
        """Reproduce sonido de alerta."""
        import time
        now = time.time() * 1000
        if now - self._last_alert_time < self._alert_cooldown:
            return
        
        max_power = max([d.get('power', -100) for d in detections])
        
        if max_power > -40:
            self._beep()
        elif max_power > -60:
            self._beep()
        else:
            return
        
        self._last_alert_time = now

    def _beep(self):
        """Reproduce un beep."""
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.beep()
        except:
            pass

    def closeEvent(self, event):
        if self.diff_mode_active and hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setChecked(False)
        event.accept()
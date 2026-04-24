# -*- coding: utf-8 -*-

"""
TSCM Widget - Herramienta de Análisis Diferencial
=================================================
Widget independiente para el modo TSCM (Technical Surveillance Counter-Measures).
"""

import logging
from datetime import datetime
from PyQt5.QtWidgets import QDockWidget
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.uic import loadUi


class TSCMWidget(QDockWidget):
    """Widget para análisis TSCM / Modo Diferencias."""
    
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
        
        # Estado
        self.diff_mode_active = False
        self.has_baseline = False
        
        # Configurar UI
        self._setup_ui_state()
        self._setup_connections()
        
        self.logger.info("✅ TSCMWidget inicializado")

    def _setup_ui_state(self):
        """Configura el estado inicial de los widgets existentes."""
        # Estado de baseline
        if hasattr(self, 'label_baseline_status'):
            self.label_baseline_status.setText("Sin Baseline Capturada")
        if hasattr(self, 'label_baseline_status_short'):
            self.label_baseline_status_short.setText("SIN BASELINE")
        if hasattr(self, 'label_baseline_icon'):
            self.label_baseline_icon.setText("⚪")
        
        # Botón de modo
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setChecked(False)
        
        # Parámetros
        if hasattr(self, 'doubleSpinBox_threshold'):
            self.doubleSpinBox_threshold.setValue(4.0)
        if hasattr(self, 'spinBox_dwell'):
            self.spinBox_dwell.setValue(200)
        
        # Estadísticas (si existen)
        if hasattr(self, 'label_active_alerts'):
            self.label_active_alerts.setText("0")

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
            self.pushButton_export_log.clicked.connect(self.tscm_export_log)
        
        if hasattr(self, 'checkBox_sound_alert'):
            self.checkBox_sound_alert.toggled.connect(self.tscm_sound_toggled)

    # ------------------------------------------------------------------------
    # SLOTS INTERNOS
    # ------------------------------------------------------------------------

    def _on_capture_baseline(self):
        """Solicita capturar la baseline."""
        self.logger.info("📸 Captura de baseline solicitada")
        self.tscm_capture_baseline.emit()

    def _on_clear_baseline(self):
        """Solicita eliminar la baseline."""
        self.logger.info("🗑️ Limpiar baseline solicitado")
        self.tscm_clear_baseline.emit()

    def _on_diff_mode_toggled(self, checked):
        """Activa/desactiva el modo diferencias."""
        self.logger.info(f"Modo Diferencias: {checked}")
        self.diff_mode_active = checked
        
        if hasattr(self, 'pushButton_diff_mode'):
            if checked:
                self.pushButton_diff_mode.setText("DETENER MODO DIFERENCIAS")
                self.pushButton_diff_mode.setStyleSheet(
                    "background-color: #44aa44; color: white; font-weight: bold;"
                )
            else:
                self.pushButton_diff_mode.setText("ACTIVAR MODO DIFERENCIAS")
                self.pushButton_diff_mode.setStyleSheet("")
        
        self.tscm_mode_toggled.emit(checked)

    # ------------------------------------------------------------------------
    # MÉTODOS PÚBLICOS (llamados desde TSCMController)
    # ------------------------------------------------------------------------

    def update_baseline_status(self, has_baseline: bool):
        """Actualiza el indicador de estado de baseline."""
        self.has_baseline = has_baseline
        
        if hasattr(self, 'label_baseline_status'):
            if has_baseline:
                self.label_baseline_status.setText("Baseline Capturada")
                self.label_baseline_status.setStyleSheet(
                    "font-weight: bold; background-color: #1a3a1a; color: #88ff88; padding: 4px;"
                )
            else:
                self.label_baseline_status.setText("Sin Baseline Capturada")
                self.label_baseline_status.setStyleSheet("")
        
        if hasattr(self, 'label_baseline_status_short'):
            if has_baseline:
                self.label_baseline_status_short.setText("BASELINE OK")
            else:
                self.label_baseline_status_short.setText("SIN BASELINE")
        
        if hasattr(self, 'label_baseline_icon'):
            if has_baseline:
                self.label_baseline_icon.setText("🟢")
            else:
                self.label_baseline_icon.setText("⚪")

    def set_diff_mode_active(self, active: bool):
        """Sincroniza el estado del botón de modo."""
        self.diff_mode_active = active
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setChecked(active)

    def set_controls_enabled(self, enabled: bool):
        """Habilita/deshabilita los controles."""
        if hasattr(self, 'pushButton_capture_baseline'):
            self.pushButton_capture_baseline.setEnabled(enabled)
        if hasattr(self, 'pushButton_clear_baseline'):
            self.pushButton_clear_baseline.setEnabled(enabled)
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setEnabled(enabled)

    def update_stats(self, alert_count: int, frequencies: list = None):
        """Actualiza las estadísticas de alertas."""
        if hasattr(self, 'label_active_alerts'):
            self.label_active_alerts.setText(str(alert_count))
            if alert_count > 0:
                self.label_active_alerts.setStyleSheet("font-weight: bold; color: #ff4444;")
            else:
                self.label_active_alerts.setStyleSheet("font-weight: bold; color: #00ff00;")

    def reset_stats(self):
        """Reinicia las estadísticas a cero."""
        if hasattr(self, 'label_active_alerts'):
            self.label_active_alerts.setText("0")
            self.label_active_alerts.setStyleSheet("font-weight: bold; color: #00ff00;")
    
    def closeEvent(self, event):
        """Maneja el cierre del widget."""
        if self.diff_mode_active:
            self.pushButton_diff_mode.setChecked(False)
        event.accept()
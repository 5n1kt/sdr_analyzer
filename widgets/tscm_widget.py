# -*- coding: utf-8 -*-

"""
TSCM Widget - Herramienta de Análisis Diferencial
=================================================
Widget independiente para el modo TSCM (Technical Surveillance Counter-Measures).
Permite capturar una baseline de RF y detectar anomalías en tiempo real.
"""

import logging
from datetime import datetime
from PyQt5.QtWidgets import QDockWidget
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.uic import loadUi


class TSCMWidget(QDockWidget):
    """
    Widget para análisis TSCM / Modo Diferencias.
    
    Señales emitidas:
        tscm_capture_baseline: Solicita capturar la baseline actual
        tscm_mode_toggled: Activa/desactiva el modo diferencias (bool)
        tscm_threshold_changed: Cambia el umbral de detección (float dB)
        tscm_dwell_changed: Cambia el tiempo de confirmación (int ms)
        tscm_clear_baseline: Elimina la baseline capturada
        tscm_export_log: Solicita exportar el log de alertas
        tscm_sound_toggled: Activa/desactiva sonido de alerta (bool)
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
        
        # Estado
        self.diff_mode_active = False
        self.has_baseline = False
        
        # Configurar UI
        self._setup_ui()
        self._setup_connections()
        
        self.logger.info("✅ TSCMWidget inicializado")

    def _setup_ui(self):
        """Configura el estado inicial de la UI."""
        self.label_baseline_status.setText("⚪ Sin Baseline Capturada")
        self.pushButton_diff_mode.setChecked(False)
        self.doubleSpinBox_threshold.setValue(4.0)
        self.spinBox_dwell.setValue(200)
        
        # Estadísticas iniciales
        self.label_active_alerts.setText("0")
        self.label_active_alerts.setStyleSheet("font-weight: bold; color: #00ff00;")
        self.label_last_detection.setText("--:--:--")
        self.label_frequencies.setText("-")
        
        # Deshabilitar exportación hasta que haya datos
        self.pushButton_export_log.setEnabled(False)

    def _setup_connections(self):
        """Conecta las señales internas de la UI."""
        self.pushButton_capture_baseline.clicked.connect(self._on_capture_baseline)
        self.pushButton_clear_baseline.clicked.connect(self._on_clear_baseline)
        self.pushButton_diff_mode.toggled.connect(self._on_diff_mode_toggled)
        self.doubleSpinBox_threshold.valueChanged.connect(self.tscm_threshold_changed)
        self.spinBox_dwell.valueChanged.connect(self.tscm_dwell_changed)
        self.pushButton_export_log.clicked.connect(self.tscm_export_log)
        self.checkBox_sound_alert.toggled.connect(self.tscm_sound_toggled)

    # ------------------------------------------------------------------------
    # SLOTS INTERNOS
    # ------------------------------------------------------------------------

    def _on_capture_baseline(self):
        """Solicita capturar la baseline."""
        self.logger.info("📸 Solicitando captura de baseline...")
        self.label_baseline_status.setText("⏳ Capturando...")
        self.tscm_capture_baseline.emit()

    def _on_clear_baseline(self):
        """Solicita eliminar la baseline."""
        self.logger.info("🗑️ Solicitando limpiar baseline...")
        self.tscm_clear_baseline.emit()

    def _on_diff_mode_toggled(self, checked):
        """Activa/desactiva el modo diferencias."""
        self.logger.info(f"🔘 Modo Diferencias toggled: {checked}")
        
        if checked:
            self.pushButton_diff_mode.setText("🟢 DETENER MODO Δ")
            self.pushButton_diff_mode.setStyleSheet(
                "background-color: #44aa44; color: white; font-weight: bold;"
            )
        else:
            self.pushButton_diff_mode.setText("🔴 ACTIVAR MODO DIFERENCIAS")
            self.pushButton_diff_mode.setStyleSheet("")
        
        self.diff_mode_active = checked
        self.tscm_mode_toggled.emit(checked)

    # ------------------------------------------------------------------------
    # MÉTODOS PÚBLICOS (llamados desde TSCMController)
    # ------------------------------------------------------------------------

    def update_baseline_status(self, has_baseline: bool):
        """Actualiza el indicador de estado de baseline."""
        self.has_baseline = has_baseline
        
        if has_baseline:
            self.label_baseline_status.setText("🟢 Baseline Capturada")
            self.label_baseline_status.setStyleSheet(
                "font-weight: bold; padding: 8px; background-color: #1a3a1a; "
                "border: 1px solid #00aa00; border-radius: 4px; color: #88ff88;"
            )
            # Habilitar exportación si hay baseline
            self.pushButton_export_log.setEnabled(True)
        else:
            self.label_baseline_status.setText("⚪ Sin Baseline Capturada")
            self.label_baseline_status.setStyleSheet(
                "font-weight: bold; padding: 8px; background-color: #2a2a2a; border-radius: 4px;"
            )

    def set_diff_mode_active(self, active: bool):
        """Sincroniza el estado del botón de modo."""
        self.pushButton_diff_mode.setChecked(active)
        self.diff_mode_active = active

    def update_stats(self, alert_count: int, frequencies: list = None):
        """
        Actualiza las estadísticas de alertas.
        
        Args:
            alert_count: Número de bins con alerta activa
            frequencies: Lista de frecuencias con alerta (opcional)
        """
        self.label_active_alerts.setText(str(alert_count))
        
        if alert_count > 0:
            self.label_active_alerts.setStyleSheet("font-weight: bold; color: #ff4444;")
            self.label_last_detection.setText(datetime.now().strftime("%H:%M:%S"))
            
            if frequencies and len(frequencies) > 0:
                # Mostrar hasta 3 frecuencias
                freq_str = ", ".join([f"{f:.3f}" for f in frequencies[:3]])
                if len(frequencies) > 3:
                    freq_str += f" (+{len(frequencies)-3})"
                self.label_frequencies.setText(freq_str + " MHz")
        else:
            self.label_active_alerts.setStyleSheet("font-weight: bold; color: #00ff00;")
            # No actualizamos last_detection ni frequencies cuando no hay alertas

    def reset_stats(self):
        """Reinicia las estadísticas a cero."""
        self.label_active_alerts.setText("0")
        self.label_active_alerts.setStyleSheet("font-weight: bold; color: #00ff00;")
        self.label_last_detection.setText("--:--:--")
        self.label_frequencies.setText("-")

    def set_controls_enabled(self, enabled: bool):
        """Habilita/deshabilita los controles de baseline y modo."""
        self.pushButton_capture_baseline.setEnabled(enabled)
        self.pushButton_clear_baseline.setEnabled(enabled)
        self.pushButton_diff_mode.setEnabled(enabled)

    # ------------------------------------------------------------------------
    # OVERRIDES
    # ------------------------------------------------------------------------

    def closeEvent(self, event):
        """Maneja el cierre del widget."""
        # Si el modo diferencias está activo, desactivarlo antes de cerrar
        if self.diff_mode_active:
            self.pushButton_diff_mode.setChecked(False)
        event.accept()
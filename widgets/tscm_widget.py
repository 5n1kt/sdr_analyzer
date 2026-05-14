# -*- coding: utf-8 -*-

"""
TSCM Widget - Herramienta de Análisis Diferencial
=================================================
Widget profesional para el modo TSCM (Technical Surveillance Counter-Measures).
Diseñado para la nueva interfaz con estilo consistente.
"""

import logging
from datetime import datetime
from PyQt5.QtWidgets import QDockWidget, QApplication
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from PyQt5.uic import loadUi


class TSCMWidget(QDockWidget):
    """
    Widget para análisis TSCM / Modo Diferencias.
    
    Señales:
        tscm_capture_baseline: Solicita capturar baseline
        tscm_mode_toggled: Activa/desactiva modo diferencias (bool)
        tscm_threshold_changed: Cambia umbral (float dB)
        tscm_dwell_changed: Cambia tiempo confirmación (int ms)
        tscm_clear_baseline: Elimina baseline
        tscm_export_log: Exporta log
        tscm_sound_toggled: Activa/desactiva sonido (bool)
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
        
        # Referencia al controller (se establece después)
        self.main_controller = None
        
        # Configurar UI
        self._setup_ui()
        self._setup_connections()
        
        self.logger.info("✅ TSCMWidget inicializado (nueva interfaz)")

    def set_main_controller(self, controller):
        """Establece referencia al controlador principal."""
        self.main_controller = controller
        self.logger.info("🔗 TSCMWidget conectado al MainController")
        
        # Actualizar estado inicial preguntando al controller
        if controller and hasattr(controller, 'tscm_ctrl'):
            has_baseline = controller.tscm_ctrl.has_baseline()
            self.logger.info(f"   Estado inicial baseline: {has_baseline}")
            self.update_baseline_status(has_baseline)

    def _setup_ui(self):
        """Configura el estado inicial de la UI."""
        self.logger.info("📐 Configurando UI...")
        
        # Estado baseline - usando nombres del nuevo UI
        if hasattr(self, 'label_baseline_icon'):
            self.label_baseline_icon.setText("⚪")
        
        if hasattr(self, 'label_baseline_status'):
            self.label_baseline_status.setText("SIN BASELINE")
        
        if hasattr(self, 'label_mode_indicator'):
            self.label_mode_indicator.setText("INACTIVO")
            self.label_mode_indicator.setStyleSheet("color: #888888;")
        
        # Botón de modo diferencias - INICIALMENTE DESHABILITADO
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setChecked(False)
            self.pushButton_diff_mode.setEnabled(False)  # Se habilita cuando hay baseline
            self.pushButton_diff_mode.setText("▶ ACTIVAR MODO Δ")
        
        # Parámetros por defecto
        if hasattr(self, 'doubleSpinBox_threshold'):
            self.doubleSpinBox_threshold.setValue(4.0)
        
        if hasattr(self, 'spinBox_dwell'):
            self.spinBox_dwell.setValue(200)
        
        # Estadísticas iniciales
        if hasattr(self, 'label_active_alerts'):
            self.label_active_alerts.setText("0")
            self.label_active_alerts.setStyleSheet("font-size: 20pt; font-weight: bold; color: #00ff00;")
        
        if hasattr(self, 'label_last_alert'):
            self.label_last_alert.setText("--:--:--")
        
        # Ocultar barra de progreso inicialmente
        if hasattr(self, 'progressBar_capture'):
            self.progressBar_capture.setVisible(False)
        
        # Exportar inicialmente deshabilitado
        if hasattr(self, 'pushButton_export_log'):
            self.pushButton_export_log.setEnabled(False)
        
        self.logger.info("✅ UI configurada")

    def _setup_connections(self):
        """Conecta las señales internas de la UI."""
        if hasattr(self, 'pushButton_capture_baseline'):
            self.pushButton_capture_baseline.clicked.connect(self._on_capture_baseline)
            self.logger.info("   Conectado: pushButton_capture_baseline")
        
        if hasattr(self, 'pushButton_clear_baseline'):
            self.pushButton_clear_baseline.clicked.connect(self._on_clear_baseline)
            self.logger.info("   Conectado: pushButton_clear_baseline")
        
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.toggled.connect(self._on_diff_mode_toggled)
            self.logger.info("   Conectado: pushButton_diff_mode")
        
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
        if hasattr(self, 'pushButton_capture_baseline'):
            self.pushButton_capture_baseline.setEnabled(False)
        self.tscm_capture_baseline.emit()

    def _on_clear_baseline(self):
        """Solicita eliminar la baseline."""
        self.logger.info("🗑️ Limpiar baseline solicitado")
        self.tscm_clear_baseline.emit()

    def _on_diff_mode_toggled(self, checked):
        """Activa/desactiva el modo diferencias."""
        self.logger.info(f"Modo Diferencias toggled: {checked}")
        
        # Verificar baseline consultando al controller
        has_baseline = False
        if self.main_controller and hasattr(self.main_controller, 'tscm_ctrl'):
            has_baseline = self.main_controller.tscm_ctrl.has_baseline()
            self.logger.info(f"   Controller has_baseline = {has_baseline}")
        else:
            # Fallback: usar variable local
            has_baseline = getattr(self, '_has_baseline_cache', False)
            self.logger.info(f"   Cache has_baseline = {has_baseline}")
        
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

    # ------------------------------------------------------------------------
    # MÉTODOS PÚBLICOS (llamados desde TSCMController)
    # ------------------------------------------------------------------------

    def update_baseline_status(self, has_baseline: bool):
        """
        Actualiza el indicador de estado de baseline.
        Este método es llamado por TSCMController cuando cambia el estado.
        """
        self.logger.info(f"📊 update_baseline_status: has_baseline={has_baseline}")
        
        # Cache para fallback
        self._has_baseline_cache = has_baseline
        
        # Actualizar ícono
        if hasattr(self, 'label_baseline_icon'):
            if has_baseline:
                self.label_baseline_icon.setText("🟢")
                self.label_baseline_icon.setStyleSheet("color: #00ff00;")
            else:
                self.label_baseline_icon.setText("⚪")
                self.label_baseline_icon.setStyleSheet("color: #888888;")
        
        # Actualizar texto de estado
        if hasattr(self, 'label_baseline_status'):
            if has_baseline:
                self.label_baseline_status.setText("BASELINE OK")
                self.label_baseline_status.setStyleSheet(
                    "font-weight: bold; color: #00ff00;"
                )
            else:
                self.label_baseline_status.setText("SIN BASELINE")
                self.label_baseline_status.setStyleSheet("color: #888888;")
        
        # Actualizar indicador de modo
        if hasattr(self, 'label_mode_indicator'):
            if has_baseline:
                self.label_mode_indicator.setText("BASELINE OK")
                self.label_mode_indicator.setStyleSheet("color: #00ff00;")
            else:
                self.label_mode_indicator.setText("INACTIVO")
                self.label_mode_indicator.setStyleSheet("color: #888888;")
        
        # ===== HABILITAR/DESHABILITAR BOTÓN DE MODO Δ =====
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setEnabled(has_baseline)
            self.logger.info(f"   pushButton_diff_mode ENABLED = {has_baseline}")
            # Forzar actualización visual
            self.pushButton_diff_mode.repaint()
            QApplication.processEvents()
        
        # Habilitar exportación si hay baseline
        if hasattr(self, 'pushButton_export_log'):
            self.pushButton_export_log.setEnabled(has_baseline)
        
        # Re-habilitar botón de captura
        if hasattr(self, 'pushButton_capture_baseline'):
            self.pushButton_capture_baseline.setEnabled(True)

    def set_diff_mode_active(self, active: bool):
        """Sincroniza el estado del botón de modo (desde controller)."""
        if hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setChecked(active)
        self.diff_mode_active = active

    def set_capturing_progress(self, active: bool, progress: int = 0):
        """Muestra/oculta barra de progreso durante captura."""
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

    def update_stats(self, alert_count: int, frequencies: list = None):
        """Actualiza las estadísticas de alertas."""
        
        # Actualizar contador
        if hasattr(self, 'label_active_alerts'):
            self.label_active_alerts.setText(str(alert_count))
            
            if alert_count > 0:
                self.label_active_alerts.setStyleSheet(
                    "font-size: 20pt; font-weight: bold; color: #ff4444; font-family: monospace;"
                )
            else:
                self.label_active_alerts.setStyleSheet(
                    "font-size: 20pt; font-weight: bold; color: #00ff00; font-family: monospace;"
                )
        
        # Actualizar hora
        if alert_count > 0 and hasattr(self, 'label_last_alert'):
            self.label_last_alert.setText(datetime.now().strftime("%H:%M:%S"))
            self.label_last_alert.setStyleSheet(
                "font-size: 11pt; font-weight: bold; color: #ff8844; font-family: monospace;"
            )
        
        # ===== MOSTRAR FRECUENCIAS EN LOG =====
        if frequencies and len(frequencies) > 0:
            freq_str = ", ".join([f"{f:.4f}" for f in frequencies[:10]])
            if len(frequencies) > 10:
                freq_str += f" ... (+{len(frequencies)-10})"
            self.logger.info(f"📡 ALERTA - Frecuencias: {freq_str} MHz")

    def reset_stats(self):
        """Reinicia las estadísticas a cero."""
        if hasattr(self, 'label_active_alerts'):
            self.label_active_alerts.setText("0")
            self.label_active_alerts.setStyleSheet(
                "font-size: 20pt; font-weight: bold; color: #00ff00; font-family: monospace;"
            )
        
        if hasattr(self, 'label_last_alert'):
            self.label_last_alert.setText("--:--:--")
            self.label_last_alert.setStyleSheet(
                "font-size: 11pt; font-weight: bold; color: #aaaaaa; font-family: monospace;"
            )

    def set_controls_enabled(self, enabled: bool):
        """Habilita/deshabilita los controles de baseline (no el modo Δ)."""
        if hasattr(self, 'pushButton_capture_baseline'):
            self.pushButton_capture_baseline.setEnabled(enabled)
        
        if hasattr(self, 'pushButton_clear_baseline'):
            self.pushButton_clear_baseline.setEnabled(enabled)
        
        # Nota: pushButton_diff_mode NO se toca aquí, se controla por update_baseline_status

    def closeEvent(self, event):
        """Maneja el cierre del widget."""
        if self.diff_mode_active and hasattr(self, 'pushButton_diff_mode'):
            self.pushButton_diff_mode.setChecked(False)
        event.accept()
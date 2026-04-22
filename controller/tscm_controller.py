# -*- coding: utf-8 -*-

"""
TSCM Controller - Controlador de Análisis Diferencial
=====================================================
Gestiona la lógica del modo TSCM (Technical Surveillance Counter-Measures).
Trabaja en conjunto con FFTController para acceder a los datos del espectro.
"""

import logging
import numpy as np
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal


class TSCMController(QObject):
    """
    Controlador para el análisis TSCM / Modo Diferencias.
    
    Señales:
        stats_updated: Emitida cuando cambian las estadísticas (alert_count, frequencies)
    """
    
    stats_updated = pyqtSignal(int, list)

    def __init__(self, main_controller):
        super().__init__()
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.TSCMController")
        
        # Estado TSCM
        self.baseline_spectrum = None
        self.diff_mode_enabled = False
        self.diff_threshold_db = 4.0
        self.dwell_frames = 6  # 200ms a 30fps ≈ 6 frames
        self.alert_dwell_counter = None
        self._baseline_captured = False
        
        # Referencia al widget (se establece después)
        self.widget = None
        
        # Contador de frames para logs
        self._tscm_frame_counter = 0
        
        self.logger.info("✅ TSCMController inicializado")

    def set_widget(self, widget):
        """Establece la referencia al widget TSCM."""
        self.widget = widget
        
        # Conectar señales del widget
        if widget:
            widget.tscm_capture_baseline.connect(self.capture_baseline)
            widget.tscm_mode_toggled.connect(self.toggle_diff_mode)
            widget.tscm_threshold_changed.connect(self.set_diff_threshold)
            widget.tscm_dwell_changed.connect(self.set_dwell_time)
            widget.tscm_clear_baseline.connect(self.clear_baseline)
            widget.tscm_export_log.connect(self.export_log)
            widget.tscm_sound_toggled.connect(self.toggle_sound)
            self.logger.info("✅ Señales TSCM conectadas")

    # ------------------------------------------------------------------------
    # MÉTODOS PRINCIPALES TSCM
    # ------------------------------------------------------------------------

    def capture_baseline(self):
        """
        Captura el espectro actual (max_hold) como línea base.
        """
        self.logger.info("=" * 50)
        self.logger.info("📸 CAPTURANDO BASELINE TSCM...")
        
        # Obtener max_hold del FFTController
        if hasattr(self.main, 'fft_ctrl') and hasattr(self.main.fft_ctrl, 'main'):
            max_hold = self.main.fft_ctrl.main.max_hold
        else:
            max_hold = getattr(self.main, 'max_hold', None)
        
        if max_hold is not None:
            self.logger.info(f"   max_hold shape: {max_hold.shape}")
            self.logger.info(f"   max_hold min/max: {max_hold.min():.1f} / {max_hold.max():.1f} dB")
            
            self.baseline_spectrum = max_hold.copy()
            self.alert_dwell_counter = np.zeros(len(self.baseline_spectrum), dtype=int)
            self._baseline_captured = True
            
            if self.widget:
                self.widget.update_baseline_status(True)
            
            self.logger.info("✅ Baseline capturada exitosamente")
            self.main.statusbar.showMessage("📸 Baseline TSCM capturada", 2000)
            
            self.logger.info("=" * 50)
            return True
        
        self.logger.error("❌ No se pudo capturar baseline: max_hold es None")
        self.main.statusbar.showMessage("❌ Error: No hay datos para capturar baseline", 3000)
        
        if self.widget:
            self.widget.update_baseline_status(False)
        
        self.logger.info("=" * 50)
        return False

    def toggle_diff_mode(self, enabled: bool):
        """
        Activa o desactiva el modo de análisis diferencial.
        """
        self.logger.info("=" * 50)
        self.logger.info(f"🔘 TOGGLE MODO DIFERENCIAS: {enabled}")
        
        # Verificar que el SDR esté capturando
        if enabled and not self.main.is_running:
            self.logger.warning("⚠️ No se puede activar TSCM: captura no iniciada")
            self.main.statusbar.showMessage("❌ Inicie la captura antes de activar TSCM", 3000)
            if self.widget:
                self.widget.set_diff_mode_active(False)
            return
        
        self.diff_mode_enabled = enabled
        
        if enabled:
            # Si no hay baseline, capturarla automáticamente
            if self.baseline_spectrum is None:
                self.logger.info("   ⚠️ No hay baseline, capturando automáticamente...")
                if not self.capture_baseline():
                    self.logger.error("   ❌ No se pudo capturar baseline automáticamente")
                    self.main.statusbar.showMessage("❌ Error al capturar baseline automática", 3000)
                    if self.widget:
                        self.widget.set_diff_mode_active(False)
                    self.diff_mode_enabled = False
                    return
            
            # Desactivar Max/Min en Visualization
            self._set_max_min_enabled(False)
            
            self.logger.info(f"   Umbral: {self.diff_threshold_db} dB")
            self.logger.info(f"   Dwell frames: {self.dwell_frames}")
            self.main.statusbar.showMessage("🔴 MODO DIFERENCIAS (TSCM) ACTIVADO", 0)
            
            # Resetear estadísticas
            if self.widget:
                self.widget.reset_stats()
        else:
            # Restaurar Max/Min
            self._set_max_min_enabled(True)
            
            self.logger.info("   Modo diferencias DESACTIVADO")
            self.main.statusbar.showMessage("⚪ Modo Diferencias Desactivado", 2000)
        
        # Notificar al FFTController que el modo TSCM cambió
        self._notify_fft_controller()
        
        self.logger.info("=" * 50)

    def set_diff_threshold(self, threshold_db: float):
        """Establece el umbral de diferencia en dB."""
        self.diff_threshold_db = threshold_db
        self.logger.info(f"📊 Umbral TSCM actualizado: {threshold_db} dB")

    def set_dwell_time(self, dwell_ms: int):
        """Establece el tiempo de confirmación (dwell time)."""
        self.dwell_frames = max(1, int(dwell_ms / 33))  # 33ms por frame a 30fps
        self.logger.info(f"⏱️ Dwell TSCM actualizado: {dwell_ms}ms → {self.dwell_frames} frames")

    def clear_baseline(self):
        """Elimina la baseline capturada."""
        self.logger.info("=" * 50)
        self.logger.info("🗑️ LIMPIANDO BASELINE TSCM...")
        
        self.baseline_spectrum = None
        self.alert_dwell_counter = None
        self._baseline_captured = False
        
        if self.widget:
            self.widget.update_baseline_status(False)
        
        # Si el modo diferencias está activo, desactivarlo
        if self.diff_mode_enabled:
            self.logger.info("   ⚠️ Modo diferencias activo, desactivando...")
            self.diff_mode_enabled = False
            if self.widget:
                self.widget.set_diff_mode_active(False)
            self._set_max_min_enabled(True)
            self._notify_fft_controller()
        
        self.logger.info("✅ Baseline eliminada")
        self.main.statusbar.showMessage("🗑️ Baseline TSCM eliminada", 2000)
        self.logger.info("=" * 50)

    # ------------------------------------------------------------------------
    # PROCESAMIENTO DE ESPECTRO (llamado desde FFTController)
    # ------------------------------------------------------------------------

    def process_spectrum(self, live_spectrum: np.ndarray, freq_axis_mhz: np.ndarray = None) -> tuple:
        """
        Procesa el espectro actual aplicando la lógica TSCM.
        
        Args:
            live_spectrum: Espectro actual en dB
            freq_axis_mhz: Eje de frecuencias en MHz (opcional, para estadísticas)
            
        Returns:
            tuple: (filtered_spectrum, baseline_to_plot)
        """
        if not self.diff_mode_enabled or self.baseline_spectrum is None:
            return live_spectrum, None
        
        if len(live_spectrum) != len(self.baseline_spectrum):
            self.logger.warning(f"⚠️ Tamaño incompatible: live={len(live_spectrum)}, baseline={len(self.baseline_spectrum)}")
            return live_spectrum, None
        
        # 1. Calcular diferencia instantánea
        diff = live_spectrum - self.baseline_spectrum
        instant_alert = diff > self.diff_threshold_db
        
        # 2. Actualizar contador de persistencia
        self.alert_dwell_counter = np.where(
            instant_alert,
            np.minimum(self.alert_dwell_counter + 1, self.dwell_frames),
            np.maximum(self.alert_dwell_counter - 2, 0)
        )
        
        # 3. Máscara final
        confirmed_alert_mask = self.alert_dwell_counter >= self.dwell_frames
        
        # 4. Aplicar máscara
        filtered_spectrum = np.where(
            confirmed_alert_mask,
            live_spectrum,
            self.main.FLOOR_DB
        )
        
        # 5. Actualizar estadísticas y logs
        self._tscm_frame_counter += 1
        alert_count = np.sum(confirmed_alert_mask)
        
        # Actualizar widget con estadísticas
        if self.widget and self._tscm_frame_counter % 10 == 0:  # Cada ~333ms
            if alert_count > 0 and freq_axis_mhz is not None:
                alert_indices = np.where(confirmed_alert_mask)[0]
                alert_freqs = freq_axis_mhz[alert_indices][:5].tolist()
                self.widget.update_stats(alert_count, alert_freqs)
            else:
                self.widget.update_stats(alert_count)
        
        # Log periódico
        if self._tscm_frame_counter % 30 == 0:  # Cada ~1 segundo
            self.logger.info(f"🎯 MODO TSCM ACTIVO - Frame {self._tscm_frame_counter}")
            self.logger.info(f"   Umbral: {self.diff_threshold_db} dB")
            self.logger.info(f"   Baseline min/max: {self.baseline_spectrum.min():.1f} / {self.baseline_spectrum.max():.1f} dB")
            self.logger.info(f"   Live min/max: {live_spectrum.min():.1f} / {live_spectrum.max():.1f} dB")
            self.logger.info(f"   Diferencia máxima: {diff.max():.1f} dB")
            self.logger.info(f"   Alertas instantáneas: {np.sum(instant_alert)} bins")
            self.logger.info(f"   Alertas activas: {alert_count} / {len(live_spectrum)} bins")
            
            if alert_count > 0 and freq_axis_mhz is not None:
                alert_indices = np.where(confirmed_alert_mask)[0]
                self.logger.info(f"   Frecuencias con alerta: {freq_axis_mhz[alert_indices][:5]} MHz")
        
        # Emitir señal de estadísticas
        if alert_count > 0 and freq_axis_mhz is not None:
            alert_indices = np.where(confirmed_alert_mask)[0]
            self.stats_updated.emit(alert_count, freq_axis_mhz[alert_indices][:5].tolist())
        
        return filtered_spectrum, self.baseline_spectrum

    def is_diff_mode_active(self) -> bool:
        """Retorna True si el modo diferencias está activo."""
        return self.diff_mode_enabled

    def has_baseline(self) -> bool:
        """Retorna True si hay una baseline capturada."""
        return self._baseline_captured and self.baseline_spectrum is not None

    # ------------------------------------------------------------------------
    # MÉTODOS AUXILIARES
    # ------------------------------------------------------------------------

    def _set_max_min_enabled(self, enabled: bool):
        """Habilita/deshabilita las curvas Max/Min en VisualizationWidget."""
        if hasattr(self.main, 'viz_widget'):
            if hasattr(self.main.viz_widget, 'checkBox_plot_max'):
                self.main.viz_widget.checkBox_plot_max.setEnabled(enabled)
                if not enabled:
                    self.main.viz_widget.checkBox_plot_max.setChecked(False)
            if hasattr(self.main.viz_widget, 'checkBox_plot_min'):
                self.main.viz_widget.checkBox_plot_min.setEnabled(enabled)
                if not enabled:
                    self.main.viz_widget.checkBox_plot_min.setChecked(False)
            if hasattr(self.main.viz_widget, 'comboBox_hold_time'):
                self.main.viz_widget.comboBox_hold_time.setEnabled(enabled)

    def _notify_fft_controller(self):
        """Notifica al FFTController que el estado TSCM ha cambiado."""
        if hasattr(self.main, 'fft_ctrl'):
            # Establecer una bandera que FFTController pueda consultar
            pass  # FFTController consultará is_diff_mode_active()

    def export_log(self):
        """Exporta el log de alertas a un archivo."""
        self.logger.info("📤 Exportando log de alertas TSCM...")
        # TODO: Implementar exportación a CSV
        self.main.statusbar.showMessage("📤 Exportación de alertas (funcionalidad en desarrollo)", 3000)

    def toggle_sound(self, enabled: bool):
        """Activa/desactiva el sonido de alerta."""
        self.logger.info(f"🔊 Sonido de alerta: {'activado' if enabled else 'desactivado'}")
        # TODO: Implementar sonido de alerta

    def on_capture_started(self):
        """Llamado cuando se inicia la captura."""
        if self.widget:
            self.widget.set_controls_enabled(True)

    def on_capture_stopped(self):
        """Llamado cuando se detiene la captura."""
        if self.diff_mode_enabled:
            self.toggle_diff_mode(False)
        if self.widget:
            self.widget.set_controls_enabled(False)
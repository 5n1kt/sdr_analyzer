# -*- coding: utf-8 -*-

"""
TSCM Controller - Controlador de Análisis Diferencial
"""

import logging
import numpy as np
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal, QTimer


class TSCMController(QObject):
    
    stats_updated = pyqtSignal(int, list)

    def __init__(self, main_controller):
        super().__init__()
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.TSCMController")
        
        # Estado TSCM
        self.baseline_spectrum = None
        self.diff_mode_enabled = False
        self.diff_threshold_db = 4.0
        self.dwell_frames = 6
        self.alert_dwell_counter = None
        self._baseline_captured = False
        
        # Para captura por tiempo
        self._capture_in_progress = False
        self._capture_buffer = []
        self._capture_timer = None
        self._capture_duration_frames = 30  # 1 segundo por defecto (30 fps)
        self._capture_frame_count = 0
        
        self.widget = None
        self._tscm_frame_counter = 0
        
        self.logger.info("✅ TSCMController inicializado")

    def set_widget(self, widget):
        self.widget = widget
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
    # CAPTURA DE BASELINE CON TIEMPO (CORREGIDO)
    # ------------------------------------------------------------------------

    def capture_baseline(self):
        """
        Captura la baseline RESPETANDO el tiempo seleccionado en el widget.
        """
        self.logger.info("=" * 60)
        self.logger.info("📸 CAPTURANDO BASELINE TSCM...")
        
        # Verificar que la captura RF esté activa
        if not self.main.is_running:
            self.logger.error("❌ La captura RF no está activa")
            self.main.statusbar.showMessage("❌ Inicie la captura RF antes de capturar baseline", 3000)
            if self.widget:
                self.widget.update_baseline_status(False)
            return False
        
        # Obtener tiempo de captura del widget
        capture_time_seconds = self._get_capture_time_from_widget()
        self.logger.info(f"   Tiempo de captura: {capture_time_seconds} segundos")
        
        # Calcular frames necesarios (asumiendo ~30 fps)
        # Los frames de FFT llegan a ~30 por segundo
        frames_needed = int(capture_time_seconds * 30)
        self._capture_duration_frames = max(5, frames_needed)  # Mínimo 5 frames
        
        self.logger.info(f"   Frames a capturar: {self._capture_duration_frames}")
        
        # Iniciar captura
        self._capture_in_progress = True
        self._capture_buffer = []
        self._capture_frame_count = 0
        
        # Mostrar progreso en UI
        if self.widget:
            self.widget.set_capturing_progress(True, 0)
            self.widget.pushButton_capture_baseline.setEnabled(False)
        
        # Iniciar timer para recolectar frames (cada 33ms ~ 30 fps)
        self._capture_timer = QTimer()
        self._capture_timer.timeout.connect(self._collect_baseline_frame)
        self._capture_timer.start(33)  # ~30 fps
        
        return True

    def _get_capture_time_from_widget(self) -> float:
        """
        Obtiene el tiempo de captura del combobox del widget.
        Valores posibles: 1, 2, 3, 5, 10 segundos
        """
        if self.widget and hasattr(self.widget, 'comboBox_capture_time'):
            # El combobox tiene textos como "1 seg", "2 seg", etc.
            text = self.widget.comboBox_capture_time.currentText()
            try:
                # Extraer el número
                import re
                match = re.search(r'(\d+)', text)
                if match:
                    return float(match.group(1))
            except:
                pass
        return 2.0  # Valor por defecto: 2 segundos

    def _collect_baseline_frame(self):
        """
        Recolecta un frame para la baseline (llamado por el timer).
        """
        if not self._capture_in_progress:
            return
        
        # Obtener espectro actual
        spectrum = self._get_live_spectrum()
        
        if spectrum is not None:
            self._capture_buffer.append(spectrum.copy())
            self.logger.debug(f"   Frame {len(self._capture_buffer)} capturado")
        
        self._capture_frame_count += 1
        
        # Actualizar progreso en UI
        if self.widget:
            progress = int(self._capture_frame_count * 100 / self._capture_duration_frames)
            progress = min(progress, 99)  # No mostrar 100% hasta el final
            self.widget.set_capturing_progress(True, progress)
        
        # Verificar si completamos la captura
        if self._capture_frame_count >= self._capture_duration_frames:
            self._finalize_baseline_capture()

    def _finalize_baseline_capture(self):
        """
        Finaliza la captura y calcula la baseline promediada.
        """
        # Detener timer
        if self._capture_timer:
            self._capture_timer.stop()
            self._capture_timer = None
        
        self._capture_in_progress = False
        
        if not self._capture_buffer:
            self.logger.error("❌ No se capturaron frames para baseline")
            if self.widget:
                self.widget.update_baseline_status(False)
                self.widget.set_capturing_progress(False, 0)
                self.widget.pushButton_capture_baseline.setEnabled(True)
            return False
        
        # Calcular baseline como MEDIANA de todos los frames (más robusta que promedio)
        stacked = np.stack(self._capture_buffer, axis=0)
        self.baseline_spectrum = np.median(stacked, axis=0)
        
        # Alternativa: usar promedio si prefieres
        # self.baseline_spectrum = np.mean(stacked, axis=0)
        
        self.alert_dwell_counter = np.zeros(len(self.baseline_spectrum), dtype=int)
        self._baseline_captured = True
        
        # Log de resultados
        self.logger.info(f"✅ Baseline capturada con {len(self._capture_buffer)} frames")
        self.logger.info(f"   Shape: {self.baseline_spectrum.shape}")
        self.logger.info(f"   Min: {self.baseline_spectrum.min():.1f} dB")
        self.logger.info(f"   Max: {self.baseline_spectrum.max():.1f} dB")
        self.logger.info(f"   Mean: {self.baseline_spectrum.mean():.1f} dB")
        
        # Actualizar UI
        if self.widget:
            self.widget.update_baseline_status(True)
            self.widget.set_capturing_progress(False, 100)
            self.widget.pushButton_capture_baseline.setEnabled(True)
        
        self.main.statusbar.showMessage(
            f"📸 Baseline capturada ({len(self._capture_buffer)} frames, {self.baseline_spectrum.shape[0]} bins)", 
            3000
        )
        
        self.logger.info("=" * 60)
        
        # Limpiar buffer
        self._capture_buffer = None
        
        return True

    def _get_live_spectrum(self) -> np.ndarray:
        """Obtiene el espectro actual en vivo."""
        # Opción 1: Espectro del FFTController
        if hasattr(self.main, 'fft_ctrl'):
            if hasattr(self.main.fft_ctrl, '_prev_spectrum'):
                spectrum = self.main.fft_ctrl._prev_spectrum
                if spectrum is not None and len(spectrum) > 0:
                    return spectrum
        
        # Opción 2: max_hold
        if hasattr(self.main, 'max_hold') and self.main.max_hold is not None:
            spectrum = self.main.max_hold
            if len(spectrum) > 0 and np.max(spectrum) > -100:
                return spectrum
        
        return None

    # ------------------------------------------------------------------------
    # MODO DIFERENCIAS
    # ------------------------------------------------------------------------

    def toggle_diff_mode(self, enabled: bool):
        """Activa o desactiva el modo de análisis diferencial."""
        self.logger.info("=" * 60)
        self.logger.info(f"🔘 toggle_diff_mode({enabled})")
        
        if enabled and self.baseline_spectrum is None:
            self.logger.warning("⚠️ No se puede activar TSCM: no hay baseline")
            self.main.statusbar.showMessage("❌ Capture baseline primero", 3000)
            if self.widget:
                self.widget.set_diff_mode_active(False)
            return
        
        if enabled and not self.main.is_running:
            self.logger.warning("⚠️ No se puede activar TSCM: captura no iniciada")
            self.main.statusbar.showMessage("❌ Inicie la captura RF antes de activar TSCM", 3000)
            if self.widget:
                self.widget.set_diff_mode_active(False)
            return
        
        # Guardar estado de max/min antes de activar TSCM
        if enabled and not self.diff_mode_enabled:
            self._saved_max_enabled = self.main.plot_max
            self._saved_min_enabled = self.main.plot_min
            self.logger.info(f"   Guardado estado Max={self._saved_max_enabled}, Min={self._saved_min_enabled}")
        
        self.diff_mode_enabled = enabled
        
        if enabled:
            self.logger.info(f"   ✅ Modo diferencias ACTIVADO")
            self.logger.info(f"   Umbral: {self.diff_threshold_db} dB")
            self.main.statusbar.showMessage("🔴 MODO DIFERENCIAS (TSCM) ACTIVADO", 0)
            if self.widget:
                self.widget.reset_stats()
        else:
            # Restaurar max/min al salir de TSCM
            if hasattr(self, '_saved_max_enabled'):
                self.main.plot_max = self._saved_max_enabled
                self.main.plot_min = self._saved_min_enabled
                self.logger.info(f"   Restaurado Max={self.main.plot_max}, Min={self.main.plot_min}")
            
            self.logger.info(f"   ✅ Modo diferencias DESACTIVADO")
            self.main.statusbar.showMessage("⚪ Modo Diferencias Desactivado", 2000)
        
        # Actualizar UI de max/min en el widget de visualización
        if hasattr(self.main, 'viz_widget'):
            if hasattr(self.main.viz_widget, 'checkBox_plot_max'):
                self.main.viz_widget.checkBox_plot_max.setChecked(self.main.plot_max)
            if hasattr(self.main.viz_widget, 'checkBox_plot_min'):
                self.main.viz_widget.checkBox_plot_min.setChecked(self.main.plot_min)
        
        if hasattr(self.main, 'update_mode_indicator'):
            if enabled:
                self.main.update_mode_indicator('tscm')
            else:
                self.main.update_mode_indicator('live')
        
        self.logger.info("=" * 60)

    def set_diff_threshold(self, threshold_db: float):
        self.diff_threshold_db = threshold_db
        self.logger.info(f"📊 Umbral TSCM: {threshold_db} dB")

    def set_dwell_time(self, dwell_ms: int):
        self.dwell_frames = max(1, int(dwell_ms / 33))
        self.logger.info(f"⏱️ Dwell TSCM: {dwell_ms}ms → {self.dwell_frames} frames")

    def clear_baseline(self):
        """Elimina la baseline capturada."""
        self.logger.info("🗑️ LIMPIANDO BASELINE TSCM...")
        
        # Si hay una captura en progreso, cancelarla
        if self._capture_in_progress:
            if self._capture_timer:
                self._capture_timer.stop()
                self._capture_timer = None
            self._capture_in_progress = False
            self._capture_buffer = None
        
        self.baseline_spectrum = None
        self.alert_dwell_counter = None
        self._baseline_captured = False
        
        if self.widget:
            self.widget.update_baseline_status(False)
            self.widget.set_capturing_progress(False, 0)
            self.widget.pushButton_capture_baseline.setEnabled(True)
        
        if self.diff_mode_enabled:
            self.diff_mode_enabled = False
            if self.widget:
                self.widget.set_diff_mode_active(False)
            if hasattr(self.main, 'update_mode_indicator'):
                self.main.update_mode_indicator('live')
        
        self.main.statusbar.showMessage("🗑️ Baseline TSCM eliminada", 2000)
        self.logger.info("✅ Baseline eliminada")

    def is_diff_mode_active(self) -> bool:
        return self.diff_mode_enabled

    def has_baseline(self) -> bool:
        return self._baseline_captured and self.baseline_spectrum is not None

    def process_spectrum(self, live_spectrum: np.ndarray, freq_axis_mhz: np.ndarray = None) -> tuple:
        if not self.diff_mode_enabled or self.baseline_spectrum is None:
            return live_spectrum, None
        
        if len(live_spectrum) != len(self.baseline_spectrum):
            return live_spectrum, None
        
        diff = live_spectrum - self.baseline_spectrum
        instant_alert = diff > self.diff_threshold_db
        
        self.alert_dwell_counter = np.where(
            instant_alert,
            np.minimum(self.alert_dwell_counter + 1, self.dwell_frames),
            np.maximum(self.alert_dwell_counter - 2, 0)
        )
        
        confirmed_alert_mask = self.alert_dwell_counter >= self.dwell_frames

        
        filtered_spectrum = np.where(
            confirmed_alert_mask,
            live_spectrum,
            self.main.FLOOR_DB
        )
        
        self._tscm_frame_counter += 1
        alert_count = np.sum(confirmed_alert_mask)
        
        if self.widget and self._tscm_frame_counter % 10 == 0:
            if alert_count > 0 and freq_axis_mhz is not None:
                alert_indices = np.where(confirmed_alert_mask)[0]
                alert_freqs = freq_axis_mhz[alert_indices][:5].tolist()
                self.widget.update_stats(alert_count, alert_freqs)
            else:
                self.widget.update_stats(alert_count)
        
        return filtered_spectrum, self.baseline_spectrum
    
  

    def export_log(self):
        self.logger.info("📤 Exportando log de alertas TSCM...")
        self.main.statusbar.showMessage("📤 Exportación de alertas (funcionalidad en desarrollo)", 3000)

    def toggle_sound(self, enabled: bool):
        self.logger.info(f"🔊 Sonido alerta: {'activado' if enabled else 'desactivado'}")

    def on_capture_started(self):
        if self.widget:
            self.widget.set_controls_enabled(True)

    def on_capture_stopped(self):
        if self.diff_mode_enabled:
            self.toggle_diff_mode(False)
        if self.widget:
            self.widget.set_controls_enabled(False)
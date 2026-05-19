# -*- coding: utf-8 -*-

"""
TSCM Controller - Controlador de Análisis Diferencial
=====================================================
Gestiona la lógica del modo TSCM (Technical Surveillance Counter-Measures).
Implementa agrupación de frecuencias para mostrar señales reales, no bins individuales.
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
        self._capture_duration_frames = 30
        self._capture_frame_count = 0
        
        # Guardar estado de max/min
        self._saved_max_enabled = False
        self._saved_min_enabled = False
        
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
    # CAPTURA DE BASELINE CON TIEMPO
    # ------------------------------------------------------------------------

    def capture_baseline(self):
        """Captura la baseline respetando el tiempo seleccionado."""
        self.logger.info("=" * 60)
        self.logger.info("📸 CAPTURANDO BASELINE TSCM...")
        
        if not self.main.is_running:
            self.logger.error("❌ La captura RF no está activa")
            self.main.statusbar.showMessage("❌ Inicie la captura RF antes de capturar baseline", 3000)
            if self.widget:
                self.widget.update_baseline_status(False)
            return False
        
        capture_time_seconds = self._get_capture_time_from_widget()
        self.logger.info(f"   Tiempo de captura: {capture_time_seconds} segundos")
        
        frames_needed = int(capture_time_seconds * 30)
        self._capture_duration_frames = max(5, frames_needed)
        
        self.logger.info(f"   Frames a capturar: {self._capture_duration_frames}")
        
        self._capture_in_progress = True
        self._capture_buffer = []
        self._capture_frame_count = 0
        
        if self.widget:
            self.widget.set_capturing_progress(True, 0)
            self.widget.pushButton_capture_baseline.setEnabled(False)
        
        self._capture_timer = QTimer()
        self._capture_timer.timeout.connect(self._collect_baseline_frame)
        self._capture_timer.start(33)
        
        return True

    def _get_capture_time_from_widget(self) -> float:
        """Obtiene el tiempo de captura del combobox."""
        if self.widget and hasattr(self.widget, 'comboBox_capture_time'):
            text = self.widget.comboBox_capture_time.currentText()
            try:
                import re
                match = re.search(r'(\d+)', text)
                if match:
                    return float(match.group(1))
            except:
                pass
        return 2.0

    def _collect_baseline_frame(self):
        """Recolecta un frame para la baseline."""
        if not self._capture_in_progress:
            return
        
        spectrum = self._get_live_spectrum()
        
        if spectrum is not None:
            self._capture_buffer.append(spectrum.copy())
        
        self._capture_frame_count += 1
        
        if self.widget:
            progress = int(self._capture_frame_count * 100 / self._capture_duration_frames)
            progress = min(progress, 99)
            self.widget.set_capturing_progress(True, progress)
        
        if self._capture_frame_count >= self._capture_duration_frames:
            self._finalize_baseline_capture()

    def _finalize_baseline_capture(self):
        """Finaliza la captura y calcula la baseline promediada."""
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
        
        stacked = np.stack(self._capture_buffer, axis=0)
        self.baseline_spectrum = np.median(stacked, axis=0)
        
        self.alert_dwell_counter = np.zeros(len(self.baseline_spectrum), dtype=int)
        self._baseline_captured = True
        
        self.logger.info(f"✅ Baseline capturada con {len(self._capture_buffer)} frames")
        self.logger.info(f"   Shape: {self.baseline_spectrum.shape}")
        self.logger.info(f"   Min: {self.baseline_spectrum.min():.1f} dB")
        self.logger.info(f"   Max: {self.baseline_spectrum.max():.1f} dB")
        self.logger.info(f"   Mean: {self.baseline_spectrum.mean():.1f} dB")
        
        if self.widget:
            self.widget.update_baseline_status(True)
            self.widget.set_capturing_progress(False, 100)
            self.widget.pushButton_capture_baseline.setEnabled(True)
        
        self.main.statusbar.showMessage(
            f"📸 Baseline capturada ({len(self._capture_buffer)} frames)", 
            3000
        )
        
        self.logger.info("=" * 60)
        self._capture_buffer = None
        
        return True

    # ------------------------------------------------------------------------
    # OBTENER ESPECTRO VIVO
    # ------------------------------------------------------------------------

    def _get_live_spectrum(self) -> np.ndarray:
        """Obtiene el espectro actual en vivo."""
        if hasattr(self.main, 'fft_ctrl'):
            if hasattr(self.main.fft_ctrl, '_prev_spectrum'):
                spectrum = self.main.fft_ctrl._prev_spectrum
                if spectrum is not None and len(spectrum) > 0:
                    return spectrum
        
        if hasattr(self.main, 'max_hold') and self.main.max_hold is not None:
            spectrum = self.main.max_hold
            if len(spectrum) > 0 and np.max(spectrum) > -100:
                return spectrum
        
        return None

    # ------------------------------------------------------------------------
    # AGRUPACIÓN DE FRECUENCIAS (OPCIÓN 3)
    # ------------------------------------------------------------------------

    def _group_alert_frequencies(self, alert_indices, freq_axis_mhz, min_gap_mhz=0.5):
        """
        Agrupa bins contiguos en alerta y devuelve frecuencias representativas.
        
        Args:
            alert_indices: Array de índices de bins en alerta
            freq_axis_mhz: Array de frecuencias en MHz
            min_gap_mhz: Separación mínima entre grupos (MHz)
                         Valores típicos: 0.1 para señales muy cercanas, 
                                         0.5 para separación normal,
                                         1.0 para señales distantes
        
        Returns:
            Lista de frecuencias centrales de cada grupo (MHz)
        """
        if len(alert_indices) == 0:
            return []
        
        # Obtener frecuencias de los bins en alerta
        freqs = freq_axis_mhz[alert_indices]
        
        # Calcular diferencias entre bins consecutivos
        diffs = np.diff(freqs)
        
        # Encontrar puntos de corte (donde la diferencia > min_gap_mhz)
        # Convertir min_gap_mhz a MHz (ya está en MHz)
        cut_points = np.where(diffs > min_gap_mhz)[0]
        
        # Crear grupos
        groups = []
        start_idx = 0
        
        for cut in cut_points:
            # Grupo desde start_idx hasta cut
            group_freqs = freqs[start_idx:cut + 1]
            if len(group_freqs) > 0:
                # Frecuencia central del grupo
                center_freq = np.mean(group_freqs)
                groups.append(round(center_freq, 4))
            start_idx = cut + 1
        
        # Último grupo
        last_group = freqs[start_idx:]
        if len(last_group) > 0:
            center_freq = np.mean(last_group)
            groups.append(round(center_freq, 4))
        
        return groups

    def _get_alert_ranges(self, alert_indices, freq_axis_mhz, min_gap_mhz=0.5):
        """
        Devuelve rangos de frecuencia donde hay alertas (formato string).
        
        Returns:
            Lista de strings como "2412.5-2420.3" o "2450.0"
        """
        if len(alert_indices) == 0:
            return []
        
        freqs = freq_axis_mhz[alert_indices]
        diffs = np.diff(freqs)
        cut_points = np.where(diffs > min_gap_mhz)[0]
        
        ranges = []
        start_idx = 0
        
        for cut in cut_points:
            start_freq = freqs[start_idx]
            end_freq = freqs[cut]
            
            if end_freq - start_freq > 0.1:
                ranges.append(f"{start_freq:.3f}-{end_freq:.3f}")
            else:
                ranges.append(f"{start_freq:.3f}")
            
            start_idx = cut + 1
        
        # Último rango
        start_freq = freqs[start_idx]
        end_freq = freqs[-1]
        if end_freq - start_freq > 0.1:
            ranges.append(f"{start_freq:.3f}-{end_freq:.3f}")
        else:
            ranges.append(f"{start_freq:.3f}")
        
        return ranges

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
        
        # Guardar estado de max/min antes de activar
        if enabled and not self.diff_mode_enabled:
            self._saved_max_enabled = self.main.plot_max
            self._saved_min_enabled = self.main.plot_min
            self.logger.info(f"   Guardado Max={self._saved_max_enabled}, Min={self._saved_min_enabled}")
            
            # Ocultar max/min en UI
            if hasattr(self.main, 'viz_widget'):
                if hasattr(self.main.viz_widget, 'checkBox_plot_max'):
                    self.main.viz_widget.checkBox_plot_max.setChecked(False)
                if hasattr(self.main.viz_widget, 'checkBox_plot_min'):
                    self.main.viz_widget.checkBox_plot_min.setChecked(False)
        
        self.diff_mode_enabled = enabled
        
        if enabled:
            self.logger.info(f"   ✅ Modo diferencias ACTIVADO")
            self.logger.info(f"   Umbral: {self.diff_threshold_db} dB")
            self.logger.info(f"   Dwell frames: {self.dwell_frames}")
            self.main.statusbar.showMessage("🔴 MODO DIFERENCIAS (TSCM) ACTIVADO", 0)
            if self.widget:
                self.widget.reset_stats()
        else:
            # Restaurar max/min al salir
            if hasattr(self, '_saved_max_enabled'):
                self.main.plot_max = self._saved_max_enabled
                self.main.plot_min = self._saved_min_enabled
                self.logger.info(f"   Restaurado Max={self.main.plot_max}, Min={self.main.plot_min}")
                
                # Restaurar UI de max/min
                if hasattr(self.main, 'viz_widget'):
                    if hasattr(self.main.viz_widget, 'checkBox_plot_max'):
                        self.main.viz_widget.checkBox_plot_max.setChecked(self.main.plot_max)
                    if hasattr(self.main.viz_widget, 'checkBox_plot_min'):
                        self.main.viz_widget.checkBox_plot_min.setChecked(self.main.plot_min)
            
            self.logger.info(f"   ✅ Modo diferencias DESACTIVADO")
            self.main.statusbar.showMessage("⚪ Modo Diferencias Desactivado", 2000)
        
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

    # ------------------------------------------------------------------------
    # PROCESAMIENTO DE ESPECTRO (CORE)
    # ------------------------------------------------------------------------

    '''def process_spectrum(self, live_spectrum: np.ndarray, freq_axis_mhz: np.ndarray = None) -> tuple:
        """
        Procesa el espectro actual aplicando la lógica TSCM.
        
        Args:
            live_spectrum: Espectro actual en dB
            freq_axis_mhz: Eje de frecuencias en MHz
        
        Returns:
            tuple: (filtered_spectrum, baseline_to_plot)
        """
        if not self.diff_mode_enabled or self.baseline_spectrum is None:
            return live_spectrum, None
        
        if len(live_spectrum) != len(self.baseline_spectrum):
            return live_spectrum, None
        
        # Calcular diferencia
        diff = live_spectrum - self.baseline_spectrum
        instant_alert = diff > self.diff_threshold_db
        
        # Actualizar contador de persistencia
        self.alert_dwell_counter = np.where(
            instant_alert,
            np.minimum(self.alert_dwell_counter + 1, self.dwell_frames),
            np.maximum(self.alert_dwell_counter - 2, 0)
        )
        
        confirmed_alert_mask = self.alert_dwell_counter >= self.dwell_frames
        
        # Espectro filtrado
        filtered_spectrum = np.where(
            confirmed_alert_mask,
            live_spectrum,
            self.main.FLOOR_DB
        )
        
        self._tscm_frame_counter += 1
        alert_count = np.sum(confirmed_alert_mask)
        
        # ===== ACTUALIZAR ESTADÍSTICAS CON AGRUPACIÓN DE FRECUENCIAS =====
        if self.widget and self._tscm_frame_counter % 10 == 0:
            if alert_count > 0 and freq_axis_mhz is not None:
                alert_indices = np.where(confirmed_alert_mask)[0]
                
                # OPCIÓN 3: Agrupar frecuencias por cercanía (0.5 MHz de separación)
                # Una señal de 20 MHz se agrupa en UNA frecuencia central
                grouped_freqs = self._group_alert_frequencies(
                    alert_indices, 
                    freq_axis_mhz, 
                    min_gap_mhz=0.5  # 500 kHz de separación mínima
                )
                
                # También obtener rangos para logging
                ranges = self._get_alert_ranges(
                    alert_indices, 
                    freq_axis_mhz, 
                    min_gap_mhz=0.5
                )
                
                # Log detallado
                self.logger.info(f"🎯 TSCM: {alert_count} bins en alerta → {len(grouped_freqs)} señales distintas")
                if ranges:
                    self.logger.info(f"   Rangos: {', '.join(ranges[:5])}" + 
                                    (f" (+{len(ranges)-5})" if len(ranges) > 5 else ""))
                
                # Enviar al widget (máximo 10 señales para no saturar)
                self.widget.update_stats(alert_count, grouped_freqs[:10])
            else:
                self.widget.update_stats(alert_count)
        
        return filtered_spectrum, self.baseline_spectrum'''
    
    def process_spectrum(self, live_spectrum: np.ndarray, freq_axis_mhz: np.ndarray = None) -> tuple:
        """
        Procesa el espectro actual aplicando la lógica TSCM.
        
        Returns:
            tuple: (filtered_spectrum, baseline_to_plot, detections_list)
        """
        if not self.diff_mode_enabled or self.baseline_spectrum is None:
            return live_spectrum, None, []
        
        if len(live_spectrum) != len(self.baseline_spectrum):
            return live_spectrum, None, []
        
        # Calcular diferencia
        diff = live_spectrum - self.baseline_spectrum
        instant_alert = diff > self.diff_threshold_db
        
        # Actualizar contador de persistencia
        self.alert_dwell_counter = np.where(
            instant_alert,
            np.minimum(self.alert_dwell_counter + 1, self.dwell_frames),
            np.maximum(self.alert_dwell_counter - 2, 0)
        )
        
        confirmed_alert_mask = self.alert_dwell_counter >= self.dwell_frames
        
        # Espectro filtrado
        filtered_spectrum = np.where(
            confirmed_alert_mask,
            live_spectrum,
            self.main.FLOOR_DB
        )
        
        self._tscm_frame_counter += 1
        alert_count = np.sum(confirmed_alert_mask)
        
        # Detectar grupos de alertas (señales)
        detections = []
        if alert_count > 0 and freq_axis_mhz is not None:
            alert_indices = np.where(confirmed_alert_mask)[0]
            
            # Agrupar por cercanía
            groups = self._group_alert_indices(alert_indices, freq_axis_mhz, min_gap_mhz=0.5)
            
            for group in groups:
                if len(group) == 0:
                    continue
                
                # Calcular métricas del grupo
                center_freq = float(np.mean(freq_axis_mhz[group]))
                bandwidth_mhz = self._get_detection_bandwidth(freq_axis_mhz, group)
                max_power = self._get_max_power_in_group(live_spectrum, group)
                snr = self._get_avg_snr_in_group(self.baseline_spectrum, live_spectrum, group)
                
                # Clasificar por ancho de banda
                sig_type, sig_icon, sig_desc = self._classify_signal_by_bw(bandwidth_mhz)
                
                detections.append({
                    'freq': round(center_freq, 4),
                    'bandwidth': bandwidth_mhz,
                    'power': round(max_power, 1),
                    'snr': round(snr, 1),
                    'type': sig_type,
                    'type_icon': sig_icon,
                    'description': sig_desc,
                    'bins': len(group)
                })
            
            # Log de detecciones (CORREGIDO)
            if detections:
                det_str = []
                for d in detections[:5]:
                    det_str.append(f"{d['freq']:.1f}MHz({d['type']})")
                self.logger.info(f"🎯 {len(detections)} señales detectadas: {', '.join(det_str)}")
        
        # Actualizar widget con detecciones (cada 10 frames)
        if self.widget and self._tscm_frame_counter % 10 == 0:
            self.widget.update_stats(alert_count, detections if detections else None)

        baseline_to_plot = self.baseline_spectrum  # <-- Debe ser el array completo
        
        return filtered_spectrum, baseline_to_plot, detections

    
    def is_diff_mode_active(self) -> bool:
        return self.diff_mode_enabled

    def has_baseline(self) -> bool:
        return self._baseline_captured and self.baseline_spectrum is not None

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

    def _classify_signal_by_bw(self, bandwidth_mhz: float) -> tuple:
        """
        Clasifica una señal por su ancho de banda.
        
        Returns:
            tuple: (tipo_string, icono, descripcion)
        """
        if bandwidth_mhz < 0.05:
            return ("Portadora", "⚡", "Señal muy estrecha")
        elif bandwidth_mhz < 0.2:
            return ("Digital estrecha", "📻", "Comunicación digital")
        elif bandwidth_mhz < 0.5:
            return ("Voz digital", "🎤", "Walkie-talkie digital")
        elif bandwidth_mhz < 2:
            return ("Voz", "📞", "Comunicación de voz")
        elif bandwidth_mhz < 7:
            return ("Digital ancha", "📡", "Transmisión de datos")
        elif bandwidth_mhz < 15:
            return ("WiFi 20MHz", "📶", "Red WiFi estándar")
        elif bandwidth_mhz < 30:
            return ("WiFi 40MHz", "📶📶", "WiFi de alto ancho")
        elif bandwidth_mhz < 60:
            return ("Radar/Drone", "🚁", "Posible drone o radar")
        else:
            return ("Ultra ancha", "📡📡", "Señal muy ancha")

    def _get_detection_bandwidth(self, freq_axis_mhz, alert_indices):
        """Calcula el ancho de banda de un grupo de bins en alerta."""
        if len(alert_indices) < 2:
            return 0.05  # Mínimo 50 kHz
        
        freqs = freq_axis_mhz[alert_indices]
        return round(freqs[-1] - freqs[0], 3)

    def _get_max_power_in_group(self, spectrum, alert_indices):
        """Obtiene la potencia máxima en un grupo de bins."""
        if len(alert_indices) == 0:
            return -120
        return float(np.max(spectrum[alert_indices]))

    def _get_avg_snr_in_group(self, baseline, spectrum, alert_indices):
        """Calcula el SNR promedio en un grupo."""
        if len(alert_indices) == 0:
            return 0
        diff = spectrum[alert_indices] - baseline[alert_indices]
        return float(np.mean(diff))
    
    def _group_alert_indices(self, alert_indices, freq_axis_mhz, min_gap_mhz=0.5):
        """
        Agrupa índices de bins contiguos en alerta.
        
        Returns:
            Lista de listas de índices agrupados
        """
        if len(alert_indices) == 0:
            return []
        
        freqs = freq_axis_mhz[alert_indices]
        groups = []
        current_group = [alert_indices[0]]
        
        for i in range(1, len(alert_indices)):
            # Verificar si los bins son contiguos en frecuencia
            if freqs[i] - freqs[i-1] < min_gap_mhz:
                current_group.append(alert_indices[i])
            else:
                groups.append(current_group)
                current_group = [alert_indices[i]]
        
        groups.append(current_group)
        return groups
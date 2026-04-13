# controller/detector_controller.py
# -*- coding: utf-8 -*-
#
# CORRECCIONES APLICADAS
# ──────────────────────
# 1. [CRÍTICO] set_frequency_fast() reemplazado por set_frequency().
#    BladeRFDevice implementa la interfaz SDRDevice que expone set_frequency()
#    como método del contrato. El método set_frequency_fast() ya no existe.
#    Afectaba dos sitios:
#      - on_frequency_selected()   (selección manual en la tabla)
#      - _scan_next_frequency()    (timer de barrido de banda)
#
# 2. create_widget() duplicado eliminado (corrección anterior conservada).
#    Solo existe una versión que conecta todas las señales incluyendo
#    scan_config_updated.
#
# 3. Bloques de código comentados con '''...''' eliminados.
#    Los mensajes de log completos están activos.

import logging
from PyQt5.QtCore import QTimer

from workers.gr_inspector_adapter import GRInspectorAdapter
from widgets.signal_detector_widget import SignalDetectorWidget


class DetectorController:

    SCAN_INTERVAL_MS     = 600
    MIN_SCAN_INTERVAL_MS = 500

    FPV_FREQUENCIES_MHZ = [
        5645, 5665, 5685, 5705, 5725, 5745, 5765, 5785, 5805, 5825, 5845, 5865
    ]

    def __init__(self, main_controller):
        self.main   = main_controller
        self.logger = logging.getLogger(f"{__name__}.DetectorController")

        self.widget             = None
        self.adapter            = None
        self.current_freq_index = 0
        self.scan_timer         = None
        self.scan_config        = {}

        self.logger.info("✅ DetectorController inicializado")

    # ------------------------------------------------------------------
    # CICLO DE VIDA DEL WIDGET
    # ------------------------------------------------------------------

    def create_widget(self):
        """
        Crea el widget del detector y conecta TODAS sus señales.
        Versión única — eliminada la definición duplicada anterior.
        """
        if self.widget is None:
            self.widget = SignalDetectorWidget(self.main)
            self.widget.main_controller = self.main

            self.widget.scan_started.connect(self.on_scan_started)
            self.widget.scan_stopped.connect(self.on_scan_stopped)
            self.widget.scan_paused.connect(self.on_scan_paused)
            self.widget.scan_resumed.connect(self.on_scan_resumed)
            self.widget.frequency_selected.connect(self.on_frequency_selected)
            self.widget.scan_config_updated.connect(self.on_config_updated)

        return self.widget

    # ------------------------------------------------------------------
    # SLOTS DE ESCANEO
    # ------------------------------------------------------------------

    def on_scan_started(self, config: dict):
        self.logger.info("▶ Iniciando detector")
        self.scan_config = config

        self.stop_adapter()

        if not self.main.is_running or not self.main.ring_buffer:
            self.widget.update_inspector_status(False)
            self.widget.update_scan_state(False)
            self.logger.error("❌ Debe iniciar la captura primero")
            return

        sample_rate = self.main.bladerf.sample_rate if self.main.bladerf else 2e6

        self.adapter = GRInspectorAdapter(
            ring_buffer = self.main.ring_buffer,
            sample_rate = sample_rate,
        )
        self.adapter.configure(config)

        self.adapter.inspector_ready.connect(self.widget.update_inspector_status)
        self.adapter.detection_result.connect(self.widget.add_detection)
        self.adapter.stats_updated.connect(self._on_stats_updated)
        self.adapter.scan_progress.connect(self._on_scan_progress)
        self.adapter.values_updated.connect(self.widget.update_detector_values)

        self.adapter.values_updated.connect(self._update_spectrum_lines)

        self.adapter.start_processing()

        interval = self.SCAN_INTERVAL_MS
        if interval < self.MIN_SCAN_INTERVAL_MS:
            self.logger.warning(
                f"⚠️ scan_timer {interval} ms < mínimo recomendado "
                f"{self.MIN_SCAN_INTERVAL_MS} ms. "
                "Puede producir detecciones poco confiables."
            )

        self.current_freq_index = 0
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self._scan_next_frequency)
        self.scan_timer.start(interval)

        self.widget.update_scan_state(True, False)

        band_name  = config.get('band_name', '?')
        freq_count = len(config.get('band_frequencies', []))
        est_time_s = freq_count * interval / 1000
        self.logger.info(
            f"📡 Escaneando '{band_name}' — "
            f"{freq_count} frecuencias × {interval} ms ≈ {est_time_s:.0f} s/pasada"
        )

    def on_scan_stopped(self):
        self.logger.info("⏹ Deteniendo detector")
        self.stop_adapter()
        self.widget.update_scan_state(False)

    def on_scan_paused(self):
        self.logger.info("⏸ Pausando detector")
        if self.adapter:
            self.adapter.pause_processing()
        if self.scan_timer:
            self.scan_timer.stop()
        self.widget.update_scan_state(True, True)

    def on_scan_resumed(self):
        self.logger.info("▶ Reanudando detector")
        if self.adapter:
            self.adapter.resume_processing()
        if self.scan_timer and not self.scan_timer.isActive():
            self.scan_timer.start(self.SCAN_INTERVAL_MS)
        self.widget.update_scan_state(True, False)

    def on_frequency_selected(self, freq_mhz: float):
        """Sintoniza el SDR a la frecuencia seleccionada en la tabla."""
        self.logger.info(f"🎯 frequency_selected: {freq_mhz:.3f} MHz")

        if not self.main.bladerf:
            self.logger.warning("⚠️ BladeRF no disponible")
            return

        # CORRECCIÓN 1: set_frequency() en lugar de set_frequency_fast()
        success = self.main.bladerf.set_frequency(freq_mhz * 1e6)
        if success:
            self.main.sync_frequency_widgets(freq_mhz)
            if self.adapter:
                self.adapter.set_current_frequency(freq_mhz)
            self.main.statusbar.showMessage(
                f"📡 Sintonizado a {freq_mhz:.3f} MHz", 3000
            )
        else:
            self.logger.error(f"❌ Error al sintonizar {freq_mhz:.3f} MHz")

    # ------------------------------------------------------------------
    # CONTROL INTERNO
    # ------------------------------------------------------------------

    def stop_adapter(self):
        if self.scan_timer:
            self.scan_timer.stop()
            self.scan_timer = None

        if self.adapter and self.adapter.isRunning():
            self.adapter.stop_processing()
            self.adapter.wait(2000)
            self.adapter = None

    def _scan_next_frequency(self):
        """Avanza a la siguiente frecuencia del barrido de banda."""
        if not self.main.is_running or not self.main.bladerf:
            return

        frequencies = self.widget.get_band_frequencies()
        if not frequencies:
            return

        total = len(frequencies)
        if self.current_freq_index >= total:
            self.current_freq_index = 0

        freq_mhz = frequencies[self.current_freq_index]

        # CORRECCIÓN 1: set_frequency() en lugar de set_frequency_fast()
        self.main.bladerf.set_frequency(freq_mhz * 1e6)

        if self.adapter:
            self.adapter.set_current_frequency(freq_mhz)
            self.adapter.set_scan_progress(self.current_freq_index, total)

        self.current_freq_index += 1

    # ------------------------------------------------------------------
    # SLOTS DE ESTADÍSTICAS Y PROGRESO
    # ------------------------------------------------------------------

    def _on_stats_updated(self, samples: int, detections: int):
        self.widget.update_progress(samples, detections)

    def _on_scan_progress(self, index: int, total: int):
        if total > 0:
            self.widget.progressBar.setValue(int((index / total) * 100))

    # ------------------------------------------------------------------
    # SLOTS DE CONFIGURACIÓN DESDE EL WIDGET
    # ------------------------------------------------------------------

    def on_config_updated(self, config: dict):
        self.logger.info(f"⚙️ Configuración actualizada: {list(config.keys())}")

        if config.get('sync_detector_values'):
            self.logger.info("🔄 Sincronización manual solicitada")
            self._force_sync_values()
        elif config.get('request_values'):
            self._update_values_from_adapter()

        if 'show_threshold' in config:
            self._update_threshold_visibility(
                config['show_threshold'],
                config.get('threshold_value')
            )

        if 'show_noise' in config:
            self._update_noise_visibility(
                config['show_noise'],
                config.get('noise_value')
            )

    def _force_sync_values(self):
        self.logger.info("🔄 Forzando sincronización de valores")

        if self.adapter and hasattr(self.adapter, 'cfar') and self.adapter.cfar:
            cfar = self.adapter.cfar
            self.logger.info(
                f"   CFAR: umbral={cfar.threshold_db:.1f} dB, "
                f"ruido={cfar.noise_floor_db:.1f} dB"
            )
            self.widget.update_detector_values(
                cfar.threshold_db,
                cfar.noise_floor_db
            )
            if not self.widget.checkBox_auto_threshold.isChecked():
                self.widget.doubleSpinBox_threshold.blockSignals(True)
                self.widget.doubleSpinBox_threshold.setValue(cfar.threshold_db)
                self.widget.doubleSpinBox_threshold.blockSignals(False)
        else:
            self.logger.warning("⚠️ No se puede sincronizar: adaptador o CFAR no disponible")

    def _update_values_from_adapter(self):
        if self.adapter and hasattr(self.adapter, 'cfar') and self.adapter.cfar:
            cfar = self.adapter.cfar
            self.widget.update_detector_values(
                cfar.threshold_db,
                cfar.noise_floor_db
            )

    def _update_threshold_visibility(self, visible: bool, value: float = None):
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.set_threshold_visible(visible)
            if value is not None:
                self.main.spectrum_plot.update_threshold(value)

    def _update_noise_visibility(self, visible: bool, value: float = None):
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.set_noise_visible(visible)
            if value is not None:
                self.main.spectrum_plot.update_noise(value)

    def _update_spectrum_lines(self, threshold_db: float, noise_db: float):
        """
        Actualiza las líneas de umbral y ruido en el gráfico de espectro.
        """
        if hasattr(self.main, 'spectrum_plot'):
            # Actualizar línea de umbral
            self.main.spectrum_plot.update_threshold(threshold_db)
            # Actualizar línea de ruido
            self.main.spectrum_plot.update_noise(noise_db)
            
            self.logger.debug(f"📊 Líneas actualizadas: umbral={threshold_db:.1f} dB, ruido={noise_db:.1f} dB")
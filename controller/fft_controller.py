# controller/fft_controller.py
# -*- coding: utf-8 -*-
#
# CORRECCIONES APLICADAS
# ──────────────────────
# 1. [BACKPRESSURE] Integración de on_frame_consumed() del FFTProcessor.
#    fft_data_ready se conecta a update_spectrum(), que al terminar llama
#    fft_processor.on_frame_consumed() para notificar que el frame fue
#    procesado. Esto activa el mecanismo anti-colas-infinitas del worker.
#    Se aplica tanto al procesador de captura (fft_processor) como al de
#    reproducción (playback_fft_processor), ya que ambos usan la misma clase.
#
#    La conexión se centraliza aquí en dos métodos:
#      connect_fft_processor(processor)         → para captura en vivo
#      connect_playback_fft_processor(processor) → para reproducción
#    Así rf_controller y playback_controller ya no necesitan conectar
#    fft_data_ready directamente.
#
# 2. [POTENCIAL] _periodic_log usaba np.random.randint(100) == 0 para
#    decidir si loguear. Esto llama al generador de números aleatorios
#    en el hilo principal 30 veces por segundo, lo cual es innecesario
#    y no determinístico. Reemplazado por un contador modular.
#
# 3. [LIMPIEZA] _handle_restart accedía a fft_processor._stop_flag
#    directamente (atributo privado). Reemplazado por is_running
#    que es la propiedad pública equivalente.

import logging
import numpy as np
import traceback
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer


class FFTController:
    """
    Gestiona todo lo relacionado con FFT y procesamiento espectral.

    Es el único lugar que conecta fft_data_ready de cualquier
    FFTProcessorZeroCopy al pipeline de renderizado.
    """

    def __init__(self, main_controller):
        self.main   = main_controller
        self.logger = logging.getLogger(f"{__name__}.FFTController")

        # Buffer para persistencia del espectro.
        # Se inicializa en None y se rellena en el primer frame.
        self._prev_spectrum = None

        # CORRECCIÓN 2: contador para log periódico (cada 300 frames ≈ 10s a 30fps)
        self._log_frame_counter = 0
        self._LOG_EVERY_N       = 300

    # ------------------------------------------------------------------
    # CONEXIÓN DE PROCESADORES — punto único de conexión de fft_data_ready
    # ------------------------------------------------------------------

    def connect_fft_processor(self, processor) -> None:
        """
        Conecta las señales de un FFTProcessorZeroCopy de captura en vivo.

        CORRECCIÓN 1: en lugar de conectar fft_data_ready directamente a
        update_spectrum (como hacía rf_controller), se conecta a
        _on_fft_data_live, que llama a update_spectrum y luego notifica
        al processor que el frame fue consumido.

        Llamar desde rf_controller._create_processors() en lugar de:
            self.main.fft_processor.fft_data_ready.connect(
                self.main.update_spectrum
            )
        """
        processor.fft_data_ready.connect(self._on_fft_data_live)
        processor.stats_updated.connect(self._on_fft_stats)
        self.logger.info("✅ FFTProcessor de captura conectado")

    def connect_playback_fft_processor(self, processor) -> None:
        """
        Conecta las señales de un FFTProcessorZeroCopy de reproducción.

        CORRECCIÓN 1: mismo patrón que connect_fft_processor pero
        usa el procesador de reproducción.

        Llamar desde playback_controller._create_playback_pipeline()
        en lugar de:
            self.main.playback_fft_processor.fft_data_ready.connect(
                self.main.update_spectrum
            )
        """
        processor.fft_data_ready.connect(self._on_fft_data_playback)
        self.logger.info("✅ FFTProcessor de reproducción conectado")

    # ------------------------------------------------------------------
    # SLOTS RECEPTORES DE FFT DATA — llaman a on_frame_consumed()
    # ------------------------------------------------------------------

    def _on_fft_data_live(self, fft_data: np.ndarray) -> None:
        """
        Slot receptor para captura en vivo.
        Procesa el frame y notifica al worker que puede emitir el siguiente.
        """
        self.update_spectrum(fft_data)

        # CORRECCIÓN 1: notificar al processor que el frame fue consumido
        if (self.main.fft_processor is not None
                and hasattr(self.main.fft_processor, 'on_frame_consumed')):
            self.main.fft_processor.on_frame_consumed()

    def _on_fft_data_playback(self, fft_data: np.ndarray) -> None:
        """
        Slot receptor para reproducción.
        """
        self.update_spectrum(fft_data)

        if (self.main.playback_fft_processor is not None
                and hasattr(self.main.playback_fft_processor, 'on_frame_consumed')):
            self.main.playback_fft_processor.on_frame_consumed()

    # ------------------------------------------------------------------
    # ACTUALIZACIÓN DE CONFIGURACIÓN FFT
    # ------------------------------------------------------------------

    def update_fft_settings(self, settings: dict) -> None:
        """Actualiza parámetros FFT con lógica de reinicio inteligente."""
        if not self.main.fft_processor:
            return

        self._log_changes(settings)

        restart_needed, fft_size_changed = self._check_restart_needed(settings)
        processor_restart = self.main.fft_processor.update_settings(settings)
        restart_needed    = restart_needed or processor_restart

        if restart_needed and self.main.is_running:
            self._handle_restart(settings, fft_size_changed)

    def _log_changes(self, settings: dict) -> None:
        changes = [
            f"{k}: {settings[k]}"
            for k in ('window', 'averaging', 'overlap', 'fft_size')
            if k in settings
        ]
        if changes:
            self.logger.info(f"🔄 Cambios FFT: {', '.join(changes)}")

    def _check_restart_needed(self, settings: dict) -> tuple:
        restart_needed   = False
        fft_size_changed = False

        if 'fft_size' in settings:
            old_size = getattr(self.main.fft_processor, 'fft_size', 0)
            new_size = settings['fft_size']
            if new_size != old_size:
                restart_needed   = True
                fft_size_changed = True
                self.logger.info(f"📏 Cambio de tamaño FFT: {old_size} → {new_size}")

        return restart_needed, fft_size_changed

    def _handle_restart(self, settings: dict, fft_size_changed: bool) -> None:
        self.main.statusbar.showMessage("Reconfigurando FFT...", 1000)

        # CORRECCIÓN 3: usar is_running en lugar de _stop_flag (privado)
        if self.main.fft_processor.isRunning():
            self.main.fft_processor.stop(immediate=True)
            QTimer.singleShot(
                50,
                lambda: self._continue_reconfig(settings, fft_size_changed)
            )
        else:
            self._continue_reconfig(settings, fft_size_changed)

    def _continue_reconfig(self, settings: dict, fft_size_changed: bool) -> None:
        try:
            self.main.statusbar.showMessage("⚙️ Reconfigurando FFT... espere", 0)
            QApplication.processEvents()

            if fft_size_changed and hasattr(self.main, 'waterfall'):
                self.main.waterfall.resize_buffer(settings['fft_size'])
                QApplication.processEvents()

            if fft_size_changed:
                new_size = settings['fft_size']
                self.main.max_hold  = np.full(new_size, self.main.FLOOR_DB)
                self.main.min_hold  = np.full(new_size, self.main.CEILING_DB)
                self._prev_spectrum = None

            self._clear_ring_buffer()

            # CORRECCIÓN 3: ya no tocamos _stop_flag directamente
            self.main.statusbar.showMessage("🚀 Iniciando nuevo FFT...", 500)
            QApplication.processEvents()
            self.main.fft_processor.start()

            self.main.statusbar.showMessage("✅ FFT reconfigurado", 2000)
            self.logger.info("✅ FFT reconfigurado correctamente")

        except Exception as exc:
            self.logger.error(f"❌ Error en reconfiguración FFT: {exc}")
            self.main.statusbar.showMessage(f"Error: {exc}", 3000)
            traceback.print_exc()

    def _clear_ring_buffer(self) -> None:
        if not hasattr(self.main, 'ring_buffer') or not self.main.ring_buffer:
            return

        drained = 0
        for _ in range(self.main.ring_buffer.num_buffers):
            result = self.main.ring_buffer.get_read_buffer(timeout_ms=10)
            if result:
                _, idx = result
                self.main.ring_buffer.release_read(idx)
                drained += 1

        if drained > 0:
            self.logger.info(f"🧹 Drenados {drained} buffers del ring")

    # ------------------------------------------------------------------
    # ACTUALIZACIÓN DE GRÁFICOS
    # ------------------------------------------------------------------

    def update_spectrum(self, fft_data: np.ndarray) -> None:
        """
        Actualiza todos los gráficos con el frame FFT recibido.

        Aplica persistencia (EMA), actualiza max/min hold, spectrum
        plot y waterfall.
        """
        try:
            sample_rate, center_freq_hz = self._get_current_parameters()

            fft_size        = len(fft_data)
            center_freq_mhz = center_freq_hz / 1e6
            sample_rate_mhz = sample_rate    / 1e6

            freq_axis_mhz = np.linspace(
                center_freq_mhz - sample_rate_mhz / 2,
                center_freq_mhz + sample_rate_mhz / 2,
                fft_size,
            )

            # CORRECCIÓN 2: log periódico con contador, no con random
            self._log_frame_counter += 1
            if self._log_frame_counter >= self._LOG_EVERY_N:
                self._log_frame_counter = 0
                self.logger.info(
                    f"📊 Eje X: {freq_axis_mhz[0]:.1f} – {freq_axis_mhz[-1]:.1f} MHz "
                    f"(SR={sample_rate_mhz:.1f} MHz)"
                )

            # ── Persistencia (EMA) ────────────────────────────────────
            p     = float(getattr(self.main, 'persistence_factor', 0.0))
            alpha = 1.0 - float(np.clip(p, 0.0, 0.99))

            fft_f32 = fft_data.astype(np.float32)

            if self._prev_spectrum is None or len(self._prev_spectrum) != fft_size:
                displayed = fft_f32.copy()
            else:
                displayed = (
                    alpha * fft_f32 + (1.0 - alpha) * self._prev_spectrum
                ).astype(np.float32)

            self._prev_spectrum = displayed.copy()

            # ── Waterfall ────────────────────────────────────────────
            self._update_waterfall(
                displayed, freq_axis_mhz, center_freq_mhz, sample_rate_mhz,
                alpha=alpha,
            )

            # ── Max / Min hold (datos RAW sin suavizar) ──────────────
            if getattr(self.main, 'reset_max_min_flag', False):
                self.main.reset_max_min_flag = False
                self.logger.info("🔄 Reiniciando buffers max/min")
                self.main.max_hold = fft_data.copy()
                self.main.min_hold = fft_data.copy()
            else:
                self._update_hold_buffers(fft_data, fft_size)

            # ── Spectrum plot ─────────────────────────────────────────
            self._update_spectrum_plot(displayed, freq_axis_mhz)
            self._update_plot_range(center_freq_mhz, sample_rate_mhz)

        except Exception as exc:
            self.logger.error(f"Error actualizando gráficos: {exc}")
            traceback.print_exc()

    def _get_current_parameters(self) -> tuple:
        if self.main.is_playing_back and self.main.player:
            return self.main.player.sample_rate, self.main.player.freq_mhz * 1e6
        sr   = self.main.bladerf.sample_rate if self.main.bladerf else 2e6
        freq = self.main.bladerf.frequency   if self.main.bladerf else 100e6
        return sr, freq

    def _update_waterfall(
        self, fft_data, freq_axis, center_freq, sample_rate, alpha: float = 1.0
    ) -> None:
        if hasattr(self.main, 'waterfall'):
            self.main.waterfall.update_spectrum(
                fft_data, freq_axis, center_freq, sample_rate, alpha=alpha
            )

    def _update_hold_buffers(self, fft_data: np.ndarray, fft_size: int) -> None:
        if self.main.max_hold is None or len(self.main.max_hold) != fft_size:
            self.main.max_hold = fft_data.copy()
        else:
            np.maximum(self.main.max_hold, fft_data, out=self.main.max_hold)

        if self.main.min_hold is None or len(self.main.min_hold) != fft_size:
            self.main.min_hold = fft_data.copy()
        else:
            np.minimum(self.main.min_hold, fft_data, out=self.main.min_hold)

    def _update_spectrum_plot(self, fft_data: np.ndarray, freq_axis) -> None:
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.update_plot(
                fft_data,
                freq_axis,
                max_hold=self.main.max_hold if self.main.plot_max else None,
                min_hold=self.main.min_hold if self.main.plot_min else None,
            )

    def _update_plot_range(self, center_freq: float, sample_rate: float) -> None:
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.plot_widget.setXRange(
                center_freq - sample_rate / 2,
                center_freq + sample_rate / 2,
            )

    # ------------------------------------------------------------------
    # SLOT DE ESTADÍSTICAS
    # ------------------------------------------------------------------

    def _on_fft_stats(self, stats: dict) -> None:
        """Recibe estadísticas del FFTProcessor (reservado para monitoreo)."""
        pass

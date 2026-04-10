# controller/rf_controller.py
# -*- coding: utf-8 -*-


import logging
import traceback
import numpy as np
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtCore import QTimer

from sdr.sdr_factory import SDRDeviceFactory
from workers.shared_buffer import IQRingBuffer
from workers.iq_processor_zerocopy import IQProcessorZeroCopy
from workers.fft_processor_zerocopy import FFTProcessorZeroCopy


class RFController:
    """Gestiona todo lo relacionado con el hardware RF y recepción."""

    def __init__(self, main_controller):
        self.main   = main_controller
        self.logger = logging.getLogger(f"{__name__}.RFController")

        self.overflow_check_timer = None

    # ------------------------------------------------------------------
    # INICIALIZACIÓN DE HARDWARE
    # ------------------------------------------------------------------

    def initialize_sdr(self, device_type: str = 'bladerf') -> None:
        """
        Inicializa el hardware SDR usando la fábrica.

        Parameters
        ----------
        device_type : clave del driver ('bladerf', 'rtlsdr', 'hackrf'…)
                      Por defecto 'bladerf' para compatibilidad con el
                      código existente que llama a initialize_bladerf().
        """
        try:
            self.logger.info(f"🔧 Inicializando SDR: '{device_type}'...")

            device = SDRDeviceFactory.create(device_type)
            device.initialize()

            # Mantener el atributo 'bladerf' para compatibilidad
            # con el resto del código mientras se migra gradualmente.
            self.main.bladerf = device

            self._update_ui_with_ranges()

            self.logger.info(f"✅ {device.device_name} listo para operar")
            self.main.statusbar.showMessage(
                f"{device.device_name} conectado"
            )

            if hasattr(self.main, 'frequency_spinner'):
                self.main.frequency_spinner.setFrequency(
                    device.frequency / 1e6
                )

        except Exception as exc:
            self._handle_initialization_error(exc)

    def initialize_bladerf(self) -> None:
        """
        Alias de compatibilidad hacia initialize_sdr('bladerf').
        Permite que el código existente siga funcionando sin cambios
        mientras se migra gradualmente.
        """
        self.initialize_sdr('bladerf')

    def _update_ui_with_ranges(self) -> None:
        """
        Pasa los rangos del hardware al widget RF.

        CAMBIO: los rangos son ahora SDRRange (con .min, .max, .step),
        no tipos propietarios de libbladeRF. RFControlsWidget ya usaba
        .min, .max y .step, por lo que es compatible sin modificar el widget.
        """
        if not hasattr(self.main, 'rf_widget'):
            return

        rf     = self.main.rf_widget
        device = self.main.bladerf

        rf.set_frequency_range(device.freq_range)
        rf.set_gain_range(device.gain_range)
        rf.set_gain_modes(device.gain_modes)
        rf.set_sample_rate_range(device.sample_rate_range)
        rf.set_bandwidth_range(device.bandwidth_range)

        # Mantener referencia directa para el widget (compatibilidad)
        rf.bladerf = device

    def _handle_initialization_error(self, error: Exception) -> None:
        self.logger.error(f"❌ Error fatal inicializando SDR: {error}")
        traceback.print_exc()

        self.main.statusbar.showMessage(f"ERROR: {error}")
        QMessageBox.critical(
            self.main,
            "Error de Hardware",
            f"No se pudo inicializar el SDR:\n{error}\n\n"
            "La aplicación continuará en modo limitado."
        )
        self.main.bladerf = None

    # ------------------------------------------------------------------
    # CONTROL DE RECEPCIÓN
    # ------------------------------------------------------------------

    def toggle_rx(self) -> None:
        if not self.main.is_running:
            self.start_rx()
        else:
            self.stop_rx()

    def start_rx(self) -> None:
        try:
            if not self.main.bladerf:
                raise RuntimeError("SDR no disponible")

            self._check_imports()

            fft_size   = self._get_fft_size()
            rf_pending = self._get_rf_pending()

            params = self.main.rf_widget.get_settings()
            params.update(rf_pending)
            self.main.bladerf.configure(params)

            self.logger.info("=" * 60)
            self.logger.info("🚀 INICIANDO PIPELINE ZERO-COPY")
            self.logger.info("=" * 60)

            self._create_buffers()
            self._create_processors(params, fft_size)
            self._init_hold_buffers(fft_size)

            self.main.iq_processor.start()
            self.main.fft_processor.start()

            if hasattr(self.main, 'audio_ctrl'):
                self.logger.info("🔊 Iniciando demodulador de audio...")
                self.main.audio_ctrl.on_capture_started()
            else:
                self.logger.warning("⚠️ Audio controller no disponible")

            self.main.is_running = True
            self._update_ui_running_state(True, params)
            self._start_monitoring()

        except Exception as exc:
            self._handle_start_error(exc)

    def _check_imports(self) -> None:
        try:
            from workers.shared_buffer import IQRingBuffer          # noqa: F401
            from workers.iq_processor_zerocopy import IQProcessorZeroCopy  # noqa: F401
            from workers.fft_processor_zerocopy import FFTProcessorZeroCopy  # noqa: F401
            self.logger.info("✅ Imports OK")
        except ImportError as exc:
            self.logger.error(f"❌ Error de import: {exc}")
            raise

    def _get_fft_size(self) -> int:
        if hasattr(self.main, 'fft_widget'):
            pending = self.main.fft_widget.get_pending_size()
            if pending:
                self.logger.info(f"🔄 Aplicando tamaño FFT pendiente: {pending}")
                return int(pending)
            return self.main.fft_widget.get_settings()['fft_size']
        return 1024

    def _get_rf_pending(self) -> dict:
        if hasattr(self.main, 'rf_widget'):
            pending = self.main.rf_widget.get_pending_changes()
            if pending:
                self.logger.info(f"🔄 Aplicando cambios RF pendientes: {pending}")
            return pending
        return {}

    def _create_buffers(self) -> None:
        """Crea los ring buffers ajustando el tamaño según sample rate."""
        device           = self.main.bladerf
        samples_per_block = device.samples_per_block

        # CAMBIO: se accede a device.sample_rate (interfaz), no bladerf.sample_rate
        current_sr = device.sample_rate
        if current_sr > 40e6:
            num_viz_buffers = 24
            num_rec_buffers = 8192
            self.logger.info(
                f"⚡ Sample rate alto ({current_sr/1e6:.0f} MHz) — "
                "usando buffers grandes"
            )
        else:
            num_viz_buffers = 12
            num_rec_buffers = 4096

        self.main.ring_buffer = IQRingBuffer(
            num_buffers      = num_viz_buffers,
            samples_per_buffer = samples_per_block,
            use_shared_memory  = False
        )
        self.main.recording_ring_buffer = IQRingBuffer(
            num_buffers      = num_rec_buffers,
            samples_per_buffer = samples_per_block,
            use_shared_memory  = True
        )
        
        # Notificar al IQ Manager
        if hasattr(self.main, 'iq_manager'):
            freq_mhz = self.main.bladerf.frequency / 1e6
            sr       = self.main.bladerf.sample_rate
            self.main.iq_manager.set_rf_info(freq_mhz, sr)
            self.main.iq_manager.on_capture_started(self.main.recording_ring_buffer)

    def _create_processors(self, params: dict, fft_size: int) -> None:
        device = self.main.bladerf

        self.main.iq_processor = IQProcessorZeroCopy(
            device,
            self.main.ring_buffer,
            self.main.recording_ring_buffer
        )

        self._configure_throttling(params, device.samples_per_block)

        self.main.fft_processor = FFTProcessorZeroCopy(
            self.main.ring_buffer,
            sample_rate = params['sample_rate']
        )

        fft_settings = self.main.fft_widget.get_settings()
        self.main.fft_processor.update_settings({
            'fft_size'   : fft_size,
            'window'     : fft_settings['window'],
            'averaging'  : fft_settings['averaging'],
            'overlap'    : fft_settings['overlap'],
            'sample_rate': params['sample_rate']
        })

        #self.main.fft_processor.fft_data_ready.connect(self.main.update_spectrum)
        self.main.iq_processor.stats_updated.connect(self._on_iq_stats)
        #self.main.fft_processor.stats_updated.connect(self._on_fft_stats)
        self.main.fft_ctrl.connect_fft_processor(self.main.fft_processor)          


    def _configure_throttling(self, params: dict, samples_per_block: int) -> None:
        iqp = self.main.iq_processor
        iqp.throttle_enabled         = True
        iqp.target_fps               = 30
        iqp.sample_rate              = params['sample_rate']
        iqp.blocks_per_second        = params['sample_rate'] / samples_per_block
        iqp.throttle_factor          = max(
            1, int(iqp.blocks_per_second / iqp.target_blocks_per_second)
        )
        iqp.expected_interval        = 1.0 / iqp.target_blocks_per_second
        self.logger.info(f"⚙️ Throttling visualización: {iqp.throttle_factor}x")

    def _init_hold_buffers(self, fft_size: int) -> None:
        self.main.max_hold = np.full(fft_size, self.main.FLOOR_DB)
        self.main.min_hold = np.full(fft_size, self.main.CEILING_DB)

    def _update_ui_running_state(
        self, running: bool, params: dict = None
    ) -> None:
        btn = self.main.pushButton_start_stop_main

        if running:
            btn.setText("Detener")
            btn.setStyleSheet(
                "background-color: #ff4444; color: white; font-weight: bold;"
            )
            if hasattr(self.main, 'fft_widget'):
                self.main.fft_widget.on_capture_started()
            if hasattr(self.main, 'rf_widget'):
                self.main.rf_widget.on_capture_started()

            sample_rate = params['sample_rate'] if params else 2e6
            fft_size    = params.get('fft_size', 1024) if params else 1024
            self.main.statusbar.showMessage(
                f"Capturando — Throttling {self.main.iq_processor.throttle_factor}x | "
                f"Sample Rate: {sample_rate/1e6:.1f} MHz | FFT: {fft_size}"
            )
        else:
            btn.setText("Iniciar")
            btn.setStyleSheet("")
            if hasattr(self.main, 'fft_widget'):
                self.main.fft_widget.on_capture_stopped()
            if hasattr(self.main, 'rf_widget'):
                self.main.rf_widget.on_capture_stopped()
            self.main.statusbar.showMessage("Detenido")

    def _start_monitoring(self) -> None:
        self.overflow_check_timer = QTimer()
        self.overflow_check_timer.timeout.connect(self._check_overflows)
        self.overflow_check_timer.start(2000)

    def _handle_start_error(self, error: Exception) -> None:
        self.logger.error(f"❌ Error en start_rx: {error}")
        traceback.print_exc()
        self.main.statusbar.showMessage(f"Error al iniciar: {error}")

    def stop_rx(self) -> None:
        try:
            if hasattr(self.main, 'audio_ctrl') and self.main.audio_ctrl.is_active:
                self.logger.info("🔇 Deteniendo demodulador de audio...")
                self.main.audio_ctrl.on_capture_stopped()

            if self.overflow_check_timer:
                self.overflow_check_timer.stop()

            if self.main.fft_processor is not None:
                self.logger.info("⏹️ Deteniendo FFTProcessor...")
                self.main.fft_processor.stop()
                self.main.fft_processor = None

            if self.main.iq_processor is not None:
                self.logger.info("⏹️ Deteniendo IQProcessor...")
                self.main.iq_processor.stop()
                self.main.iq_processor = None

            if hasattr(self.main, 'iq_manager'):
                self.main.iq_manager.on_capture_stopped()

            self.main.ring_buffer            = None
            self.main.recording_ring_buffer  = None

            # CAMBIO: se usa device.streaming (interfaz), no bladerf.streaming
            if self.main.bladerf and self.main.bladerf.streaming:
                self.main.bladerf.stop_stream()

            self.main.is_running = False
            self._update_ui_running_state(False)
            self.logger.info("✅ Captura detenida")

        except Exception as exc:
            self.logger.error(f"❌ Error en stop_rx: {exc}")
            self.main.iq_processor          = None
            self.main.fft_processor         = None
            self.main.ring_buffer           = None
            self.main.recording_ring_buffer = None
            self.main.is_running            = False

    # ------------------------------------------------------------------
    # ACTUALIZACIÓN DE CONFIGURACIÓN RF
    # ------------------------------------------------------------------

    def update_rf_settings(self, settings: dict) -> None:
        if not settings or not isinstance(settings, dict):
            self.logger.warning("⚠️ update_rf_settings: settings inválido")
            return

        if not self.main.bladerf:
            self.logger.warning("⚠️ SDR no disponible")
            return

        changes = self._format_changes(settings)
        if changes:
            self.logger.info(f"📻 Actualizando RF: {changes}")

        # Cambio de solo frecuencia mientras se está capturando → ruta rápida
        if self._is_frequency_only_change(settings) and self.main.is_running:
            if self._try_fast_frequency_change(settings):
                return

        was_running = self.main.is_running
        if was_running:
            self.logger.info("⏸ Deteniendo captura para aplicar cambios...")
            self.stop_rx()

        self._apply_rf_config(settings)

        if 'sample_rate' in settings and settings['sample_rate'] is not None:
            self._handle_sample_rate_change(settings['sample_rate'])

        if was_running:
            self.logger.info("▶ Reiniciando captura...")
            self.start_rx()

    def _format_changes(self, settings: dict) -> str:
        parts = []
        if settings.get('frequency')   is not None:
            parts.append(f"freq={settings['frequency']/1e6:.1f} MHz")
        if settings.get('sample_rate') is not None:
            parts.append(f"sr={settings['sample_rate']/1e6:.1f} MSPS")
        if settings.get('bandwidth')   is not None:
            parts.append(f"bw={settings['bandwidth']/1e6:.1f} MHz")
        if settings.get('gain')        is not None:
            parts.append(f"gain={settings['gain']} dB")
        return ', '.join(parts)

    def _is_frequency_only_change(self, settings: dict) -> bool:
        return (
            len(settings) == 1
            and 'frequency' in settings
            and settings['frequency'] is not None
        )

    def _try_fast_frequency_change(self, settings: dict) -> bool:
        """
        Usa device.set_frequency() del contrato SDRDevice.

        CAMBIO: ya no busca set_frequency_fast() con hasattr — todos los
        drivers implementan set_frequency() como parte de la interfaz.
        """
        freq_hz = settings['frequency']
        self.logger.info(f"📡 Cambio rápido a {freq_hz/1e6:.3f} MHz")

        success = self.main.bladerf.set_frequency(freq_hz)
        if success:
            self.main.sync_frequency_widgets(freq_hz / 1e6)
            return True

        self.logger.error("❌ Error en cambio rápido de frecuencia")
        return False

    def _apply_rf_config(self, settings: dict) -> None:
        filtered = {k: v for k, v in settings.items() if v is not None}
        if filtered:
            self.main.bladerf.configure(filtered)

    def _handle_sample_rate_change(self, new_sr: float) -> None:
        self.logger.info(f"🔄 Sample rate → {new_sr/1e6:.1f} MSPS")

        if hasattr(self.main, 'iq_processor') and self.main.iq_processor:
            self.main.iq_processor.update_sample_rate(new_sr)

        if hasattr(self.main, 'fft_processor') and self.main.fft_processor:
            self.main.fft_processor.update_settings({'sample_rate': new_sr})

        '''if hasattr(self.main, 'iq_manager'):
            self.main.iq_manager.current_sample_rate = new_sr'''

        if hasattr(self.main, 'iq_manager') and self.main.bladerf:
            freq_mhz = self.main.bladerf.frequency / 1e6
            self.main.iq_manager.set_rf_info(freq_mhz, new_sr)

    # ------------------------------------------------------------------
    # ESTADÍSTICAS Y MONITOREO
    # ------------------------------------------------------------------

    def _on_iq_stats(self, stats: dict) -> None:
        if stats['overflow_skips'] > 0:
            self.logger.warning(f"⚠️ IQ overflows: {stats['overflow_skips']}")
            self.main.statusbar.showMessage(
                f"Overflows: {stats['overflow_skips']}", 2000
            )

    def _on_fft_stats(self, stats: dict) -> None:
        pass

    def _check_overflows(self) -> None:
        if hasattr(self.main, 'ring_buffer') and self.main.ring_buffer:
            stats = self.main.ring_buffer.get_stats()
            if stats['overflow'] > 0:
                self.logger.warning(
                    f"⚠️ Ring buffer overflows: {stats['overflow']}"
                )
                self.main.statusbar.showMessage(
                    f"Overflows: {stats['overflow']}", 2000
                )

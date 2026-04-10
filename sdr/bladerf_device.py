# sdr/bladerf_device.py
# -*- coding: utf-8 -*-
#
# Implementación de SDRDevice para BladeRF 2.0 micro.
#
# Todo el código específico de libbladeRF (_bladerf.GainMode, SC16_Q11,
# sync_rx, ChannelLayout…) queda encapsulado aquí.
# Ningún controller, worker ni widget debe importar este módulo
# directamente — deben obtener la instancia a través de SDRDeviceFactory.
#
# Correcciones respecto al BladeRFManager original
# ─────────────────────────────────────────────────
# 1. Umbral de saturación corregido: 2047/2048 ≈ 0.9995 (era 0.9).
# 2. Reducción automática de ganancia tras 3 saturaciones consecutivas
#    en modo Manual (-6 dB por evento).
# 3. close() llama a self.sdr.close() antes de soltar la referencia.
# 4. Rangos expuestos como SDRRange, no como tipos propietarios de libbladeRF.
# 5. gain_modes expuesto como list[str], no como lista de objetos enum.
# 6. set_frequency() unifica set_frequency_fast() como parte del contrato.
# 7. read_samples() centraliza sync_rx — los workers nunca acceden a sdr.sync_rx.

import numpy as np
import logging
import time
import threading

from sdr.sdr_device import SDRDevice, SDRRange

try:
    from bladerf import _bladerf
    BLADERF_AVAILABLE = True
except ImportError:
    BLADERF_AVAILABLE = False


# =======================================================================
# MAPEO DE MODOS DE GANANCIA
# =======================================================================

# Mapeo bidireccional entre strings legibles y constantes de libbladeRF.
# Se mantiene aquí para que ningún código externo necesite importar _bladerf.
_GAIN_MODE_TO_INT = {
    'Manual':   1,
    'Default':  0,
    'Fast AGC': 2,
    'Slow AGC': 3,
    'Hybrid':   4,
}
_INT_TO_GAIN_MODE = {v: k for k, v in _GAIN_MODE_TO_INT.items()}


class BladeRFDevice(SDRDevice):
    """
    Driver para BladeRF 2.0 micro.

    Implementa el contrato SDRDevice completo.
    Toda la API de libbladeRF (_bladerf.*) es privada a esta clase.
    """

    # ------------------------------------------------------------------
    # CONSTANTES INTERNAS
    # ------------------------------------------------------------------
    _BYTES_PER_SAMPLE     = 4          # SC16_Q11: 2 bytes I + 2 bytes Q
    _DEFAULT_SPB          = 8192       # samples_per_block por defecto
    _SC16_Q11_SCALE       = 2048.0     # 2^11 — divisor del formato SC16_Q11
    _ADC_SATURATION       = 2047.0 / 2048.0   # ≈ 0.9995 (12-bit ADC)
    _SATURATION_DB_STEP   = 6.0        # dB a reducir por evento de saturación
    _SATURATION_COUNT_MAX = 3          # saturaciones consecutivas antes de actuar

    # ------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        # Objetos de libbladeRF (privados)
        self._sdr    = None
        self._rx_ch  = None
        self._lock   = threading.Lock()

        # Estado público
        self._is_initialized = False
        self._streaming      = False

        # Parámetros RF actuales
        self._frequency   = 100e6
        self._sample_rate = 2e6
        self._bandwidth   = 1e6
        self._gain        = 50.0
        self._gain_mode   = 'Manual'

        # Configuración del buffer
        self._buffer_size    = 8192
        self._num_buffers    = 16
        self._num_transfers  = 8

        # Rangos (se populan en initialize())
        self._freq_range        = SDRRange(70e6,    6e9,   1.0)
        self._sample_rate_range = SDRRange(160e3,  61.44e6, 1.0)
        self._bandwidth_range   = SDRRange(200e3,  56e6,   1.0)
        self._gain_range        = SDRRange(0.0,    73.0,   1.0)
        self._gain_modes_list   = list(_GAIN_MODE_TO_INT.keys())

        # Control de saturación
        self._saturation_count = 0

    def __del__(self):
        self.close()

    # ------------------------------------------------------------------
    # PROPIEDADES DE ESTADO
    # ------------------------------------------------------------------

    @property
    def frequency(self) -> float:
        return self._frequency

    @property
    def sample_rate(self) -> float:
        return self._sample_rate

    @property
    def bandwidth(self) -> float:
        return self._bandwidth

    @property
    def gain(self) -> float:
        return self._gain

    @property
    def gain_mode(self) -> str:
        return self._gain_mode

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    @property
    def streaming(self) -> bool:
        return self._streaming

    # ------------------------------------------------------------------
    # PROPIEDADES DE CAPACIDAD
    # ------------------------------------------------------------------

    @property
    def freq_range(self) -> SDRRange:
        return self._freq_range

    @property
    def sample_rate_range(self) -> SDRRange:
        return self._sample_rate_range

    @property
    def bandwidth_range(self) -> SDRRange:
        return self._bandwidth_range

    @property
    def gain_range(self) -> SDRRange:
        return self._gain_range

    @property
    def gain_modes(self) -> list:
        return self._gain_modes_list

    # ------------------------------------------------------------------
    # METADATOS
    # ------------------------------------------------------------------

    @property
    def device_name(self) -> str:
        return 'BladeRF 2.0 micro'

    @property
    def samples_per_block(self) -> int:
        return self._DEFAULT_SPB

    @property
    def bytes_per_sample(self) -> int:
        return self._BYTES_PER_SAMPLE

    # ------------------------------------------------------------------
    # CICLO DE VIDA
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        if not BLADERF_AVAILABLE:
            raise RuntimeError(
                "La librería 'bladerf' no está instalada. "
                "Ejecuta: pip install bladerf"
            )

        with self._lock:
            try:
                devices = _bladerf.get_device_list()
                if not devices:
                    raise RuntimeError("No se encontró ningún BladeRF conectado")

                self.logger.info(f"Dispositivo encontrado: {devices[0]}")

                self._sdr   = _bladerf.BladeRF()
                self._rx_ch = self._sdr.Channel(_bladerf.CHANNEL_RX(0))

                self.logger.info(f"libbladeRF versión : {_bladerf.version()}")
                self.logger.info(f"Firmware           : {self._sdr.get_fw_version()}")
                self.logger.info(f"FPGA               : {self._sdr.get_fpga_version()}")

                # Convertir rangos propietarios a SDRRange
                _fr  = self._rx_ch.frequency_range
                _srr = self._rx_ch.sample_rate_range
                _bwr = self._rx_ch.bandwidth_range
                _gr  = self._sdr.get_gain_range(_bladerf.CHANNEL_RX(0))

                self._freq_range        = SDRRange(_fr.min,  _fr.max,  getattr(_fr,  'step', 1.0))
                self._sample_rate_range = SDRRange(_srr.min, _srr.max, getattr(_srr, 'step', 1.0))
                self._bandwidth_range   = SDRRange(_bwr.min, _bwr.max, getattr(_bwr, 'step', 1.0))
                self._gain_range        = SDRRange(_gr.min,  _gr.max,  getattr(_gr,  'step', 1.0))

                # Convertir gain_modes a lista de strings
                raw_modes = self._rx_ch.gain_modes
                self._gain_modes_list = [
                    _INT_TO_GAIN_MODE.get(
                        m.value if hasattr(m, 'value') else int(m),
                        str(m)
                    )
                    for m in raw_modes
                ]

                self.logger.info(
                    f"Rango frecuencia   : "
                    f"{self._freq_range.min/1e6:.0f} – {self._freq_range.max/1e6:.0f} MHz"
                )
                self.logger.info(
                    f"Rango sample rate  : "
                    f"{self._sample_rate_range.min/1e6:.1f} – "
                    f"{self._sample_rate_range.max/1e6:.1f} MSPS"
                )
                self.logger.info(
                    f"Rango ganancia     : "
                    f"{self._gain_range.min:.0f} – {self._gain_range.max:.0f} dB"
                )
                self.logger.info(
                    f"Modos de ganancia  : {self._gain_modes_list}"
                )

                self._apply_rf_settings()
                self._setup_sync_stream()

                self._is_initialized = True
                self.logger.info("✅ BladeRF 2.0 inicializado correctamente")
                return True

            except Exception as exc:
                self.logger.error(f"❌ Error inicializando BladeRF: {exc}")
                raise

    def configure(self, params: dict) -> bool:
        with self._lock:
            # Cambio de frecuencia sola → ruta rápida sin lock externo
            if set(params.keys()) == {'frequency'}:
                return self._set_frequency_nolock(params['frequency'])

            was_streaming = self._streaming

            try:
                if was_streaming:
                    self._stop_stream_nolock()

                if 'frequency' in params and params['frequency'] is not None:
                    self._frequency = self._freq_range.clamp(params['frequency'])

                if 'sample_rate' in params and params['sample_rate'] is not None:
                    self._sample_rate = self._sample_rate_range.clamp(
                        params['sample_rate']
                    )

                if 'bandwidth' in params and params['bandwidth'] is not None:
                    self._bandwidth = self._bandwidth_range.clamp(
                        params['bandwidth']
                    )

                if 'gain' in params and params['gain'] is not None:
                    self._gain = self._gain_range.clamp(params['gain'])

                if 'gain_mode' in params and params['gain_mode'] is not None:
                    mode = params['gain_mode']
                    # Aceptar string o entero
                    if isinstance(mode, str) and mode in _GAIN_MODE_TO_INT:
                        self._gain_mode = mode
                    elif isinstance(mode, int) and mode in _INT_TO_GAIN_MODE:
                        self._gain_mode = _INT_TO_GAIN_MODE[mode]

                self._apply_rf_settings()
                self._setup_sync_stream()

                if was_streaming:
                    self._start_stream_nolock()

                return True

            except Exception as exc:
                self.logger.error(f"❌ Error configurando BladeRF: {exc}")
                return False

    def set_frequency(self, hz: float) -> bool:
        """Cambio rápido de frecuencia sin reiniciar el stream."""
        with self._lock:
            return self._set_frequency_nolock(hz)

    def start_stream(self) -> None:
        with self._lock:
            self._start_stream_nolock()

    def stop_stream(self) -> None:
        with self._lock:
            self._stop_stream_nolock()

    def read_samples(self, buffer: bytearray, num_samples: int) -> bool:
        """
        Lee muestras raw del hardware en `buffer`.

        Maneja TimeoutError (reinicia el stream) y DeviceError
        (reinicia el dispositivo completo).

        Los workers deben llamar a este método; NUNCA deben acceder a
        self._sdr.sync_rx directamente.
        """
        if not self._is_initialized:
            raise RuntimeError("BladeRF no inicializado")

        with self._lock:
            if not self._streaming:
                self._start_stream_nolock()

        try:
            self._sdr.sync_rx(buffer, num_samples)
            return True

        except _bladerf.TimeoutError:
            self.logger.warning("⚠️ Timeout en sync_rx — reiniciando stream")
            with self._lock:
                self._stop_stream_nolock()
                self._setup_sync_stream()
                self._start_stream_nolock()
            self._sdr.sync_rx(buffer, num_samples)
            return True

        except _bladerf.DeviceError as exc:
            self.logger.error(f"❌ Error de dispositivo: {exc} — reiniciando")
            self.close()
            time.sleep(1.0)
            self.initialize()
            raise RuntimeError(f"Dispositivo reiniciado tras error: {exc}")

    def bytes_to_complex(
        self, buffer: bytearray, num_samples: int
    ) -> np.ndarray:
        """
        Convierte un buffer SC16_Q11 a complex64 normalizado.

        División por 2048 (2^11) produce rango [-1.0, +1.0].
        Verifica saturación y reduce ganancia automáticamente si se detecta.
        """
        samples   = np.frombuffer(buffer, dtype=np.int16, count=num_samples * 2)
        i_samples = samples[0::2].astype(np.float32)
        q_samples = samples[1::2].astype(np.float32)
        iq_data   = (i_samples + 1j * q_samples) / self._SC16_Q11_SCALE

        self._check_saturation(iq_data)
        return iq_data

    def close(self) -> None:
        with self._lock:
            self._stop_stream_nolock()

            if self._rx_ch:
                try:
                    self._rx_ch.enable = False
                except Exception:
                    pass
                self._rx_ch = None

            if self._sdr:
                try:
                    self._sdr.close()      # CORRECCIÓN: cierre explícito
                except Exception:
                    pass
                self._sdr = None

            self._is_initialized = False
            self.logger.info("BladeRF desconectado")

    # ------------------------------------------------------------------
    # PRIVADOS — solo se llaman con el lock ya adquirido
    # ------------------------------------------------------------------

    def _set_frequency_nolock(self, hz: float) -> bool:
        try:
            if not self._is_initialized or self._rx_ch is None:
                self.logger.error("❌ BladeRF no inicializado")
                return False

            hz = self._freq_range.clamp(hz)
            self._rx_ch.frequency = int(hz)
            self._frequency = hz
            self.logger.info(f"📡 Frecuencia → {hz/1e6:.3f} MHz")
            return True

        except Exception as exc:
            self.logger.error(f"❌ Error cambiando frecuencia: {exc}")
            return False

    def _apply_rf_settings(self):
        """Aplica todos los parámetros al hardware (llamar con lock)."""
        mode_int = _GAIN_MODE_TO_INT.get(self._gain_mode, 1)

        self._rx_ch.frequency   = int(self._frequency)
        self._rx_ch.sample_rate = int(self._sample_rate)
        self._rx_ch.bandwidth   = int(self._bandwidth)
        self._rx_ch.gain_mode   = mode_int
        self._rx_ch.gain        = int(self._gain)

    def _setup_sync_stream(self):
        """Configura el stream síncrono SC16_Q11 (llamar con lock)."""
        self._sdr.sync_config(
            layout       = _bladerf.ChannelLayout.RX_X1,
            fmt          = _bladerf.Format.SC16_Q11,
            num_buffers  = self._num_buffers,
            buffer_size  = self._buffer_size,
            num_transfers= self._num_transfers,
            stream_timeout = 3500
        )
        self.logger.info("Stream síncrono SC16_Q11 configurado")

    def _start_stream_nolock(self):
        self._rx_ch.enable = True
        self._streaming = True
        self.logger.info("Streaming iniciado")

    def _stop_stream_nolock(self):
        if self._rx_ch:
            try:
                self._rx_ch.enable = False
            except Exception:
                pass
        self._streaming = False

    def _check_saturation(self, iq_data: np.ndarray) -> None:
        """
        Detecta saturación del ADC y reduce ganancia si persiste.

        CORRECCIÓN: umbral real del ADC de 12 bits en SC16_Q11 = 2047/2048
        (≈ 0.9995), no 0.9. El umbral anterior disparaba falsos positivos
        con señales fuertes pero válidas.
        """
        max_val = float(np.max(np.abs(iq_data)))

        if max_val >= self._ADC_SATURATION:
            self._saturation_count += 1
            self.logger.warning(
                f"⚠️ Saturación ADC [{self._saturation_count}x]: "
                f"{max_val:.4f} ≥ {self._ADC_SATURATION:.4f}"
            )

            if (self._gain_mode == 'Manual'
                    and self._saturation_count >= self._SATURATION_COUNT_MAX):
                new_gain = self._gain_range.clamp(
                    self._gain - self._SATURATION_DB_STEP
                )
                with self._lock:
                    self._rx_ch.gain = int(new_gain)
                    self._gain = new_gain
                self._saturation_count = 0
                self.logger.warning(
                    f"🔧 Ganancia reducida automáticamente a {new_gain:.0f} dB"
                )
        else:
            self._saturation_count = 0

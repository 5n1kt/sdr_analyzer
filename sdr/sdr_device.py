# sdr/sdr_device.py
# -*- coding: utf-8 -*-
#
# Interfaz abstracta para dispositivos SDR.
#
# Toda clase de hardware (BladeRF, RTL-SDR, HackRF, etc.) debe heredar
# de SDRDevice e implementar sus métodos y propiedades abstractas.
#
# El resto del sistema (controllers, workers, widgets) SOLO debe depender
# de SDRDevice, nunca de una implementación concreta.
#
# Contrato de rangos
# ──────────────────
# Los rangos se exponen siempre como dicts con claves uniformes:
#
#   freq_range        → {'min': Hz,  'max': Hz,  'step': Hz}
#   sample_rate_range → {'min': Hz,  'max': Hz,  'step': Hz}
#   bandwidth_range   → {'min': Hz,  'max': Hz,  'step': Hz}
#   gain_range        → {'min': dB,  'max': dB}
#   gain_modes        → list[str]   ej. ['Manual', 'AGC', 'Fast AGC']
#
# Esto elimina la dependencia de tipos propietarios de libbladeRF
# (RangeObject, GainMode…) en los widgets y controllers.

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import numpy as np


# =======================================================================
# DATACLASS DE RANGO — REEMPLAZA LOS TIPOS PROPIETARIOS DE libbladeRF
# =======================================================================

@dataclass
class SDRRange:
    """
    Rango de un parámetro SDR.

    Sustituye a los objetos RangeObject de libbladeRF y a cualquier
    estructura equivalente de otras bibliotecas SDR.

    Atributos
    ---------
    min   : valor mínimo (Hz para frecuencias/tasas, dB para ganancia)
    max   : valor máximo
    step  : resolución del parámetro (1 si no aplica)
    """
    min: float
    max: float
    step: float = 1.0

    def clamp(self, value: float) -> float:
        """Devuelve value limitado al rango [min, max]."""
        return float(max(self.min, min(value, self.max)))


# =======================================================================
# INTERFAZ ABSTRACTA
# =======================================================================

class SDRDevice(ABC):
    """
    Contrato que debe cumplir cualquier driver de hardware SDR.

    Uso previsto
    ────────────
    1. Crear una subclase concreta, por ejemplo BladeRFDevice(SDRDevice).
    2. Implementar todos los métodos y propiedades abstractas.
    3. Obtener la instancia a través de SDRDeviceFactory, nunca directamente.

    En los controllers y workers se usa SOLO esta interfaz:

        device: SDRDevice = SDRDeviceFactory.create('bladerf')
        device.initialize()
        device.configure({'frequency': 100e6, 'sample_rate': 2e6})
    """

    # ------------------------------------------------------------------
    # PROPIEDADES DE ESTADO — deben ser accesibles sin inicializar
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def frequency(self) -> float:
        """Frecuencia central actual en Hz."""

    @property
    @abstractmethod
    def sample_rate(self) -> float:
        """Tasa de muestreo actual en Hz."""

    @property
    @abstractmethod
    def bandwidth(self) -> float:
        """Ancho de banda del filtro RF en Hz."""

    @property
    @abstractmethod
    def gain(self) -> float:
        """Ganancia de recepción actual en dB."""

    @property
    @abstractmethod
    def gain_mode(self) -> str:
        """Modo de ganancia actual como string (ej. 'Manual', 'AGC')."""

    @property
    @abstractmethod
    def is_initialized(self) -> bool:
        """True si el dispositivo fue inicializado correctamente."""

    @property
    @abstractmethod
    def streaming(self) -> bool:
        """True si el stream de muestras está activo."""

    # ------------------------------------------------------------------
    # PROPIEDADES DE CAPACIDAD — disponibles tras initialize()
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def freq_range(self) -> SDRRange:
        """Rango de frecuencia soportado."""

    @property
    @abstractmethod
    def sample_rate_range(self) -> SDRRange:
        """Rango de tasa de muestreo soportada."""

    @property
    @abstractmethod
    def bandwidth_range(self) -> SDRRange:
        """Rango de ancho de banda soportado."""

    @property
    @abstractmethod
    def gain_range(self) -> SDRRange:
        """Rango de ganancia soportado."""

    @property
    @abstractmethod
    def gain_modes(self) -> list:
        """Lista de modos de ganancia disponibles como strings."""

    # ------------------------------------------------------------------
    # METADATOS DEL DISPOSITIVO
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def device_name(self) -> str:
        """Nombre del dispositivo, ej. 'BladeRF 2.0 micro'."""

    @property
    @abstractmethod
    def samples_per_block(self) -> int:
        """Número de muestras IQ por bloque de transferencia."""

    @property
    @abstractmethod
    def bytes_per_sample(self) -> int:
        """Bytes que ocupa una muestra IQ en el buffer raw."""

    # ------------------------------------------------------------------
    # CICLO DE VIDA
    # ------------------------------------------------------------------

    @abstractmethod
    def initialize(self) -> bool:
        """
        Abre el dispositivo y lo deja listo para recibir.

        Returns
        -------
        True si la inicialización fue exitosa.

        Raises
        ------
        RuntimeError si el hardware no se encuentra o falla.
        """

    @abstractmethod
    def configure(self, params: dict) -> bool:
        """
        Aplica uno o varios parámetros RF.

        Parámetros reconocidos
        ----------------------
        frequency   : Hz (float)
        sample_rate : Hz (float)
        bandwidth   : Hz (float)
        gain        : dB (float)
        gain_mode   : str  ('Manual', 'AGC', etc.)

        Claves desconocidas deben ignorarse (no lanzar excepción).

        Returns
        -------
        True si todos los parámetros se aplicaron sin error.
        """

    @abstractmethod
    def set_frequency(self, hz: float) -> bool:
        """
        Cambia la frecuencia sin reiniciar el stream.

        Equivale a la optimización set_frequency_fast de BladeRFManager.
        Todas las implementaciones deben soportarlo aunque internamente
        no sea más rápido que configure({'frequency': hz}).

        Returns
        -------
        True si el cambio fue exitoso.
        """

    @abstractmethod
    def start_stream(self) -> None:
        """Activa la recepción continua de muestras."""

    @abstractmethod
    def stop_stream(self) -> None:
        """Detiene la recepción de muestras."""

    @abstractmethod
    def read_samples(self, buffer: bytearray, num_samples: int) -> bool:
        """
        Llena `buffer` con `num_samples` muestras IQ raw del hardware.

        El formato del buffer (int16 interleaved, uint8, etc.) es
        específico de cada implementación. El llamador obtiene muestras
        normalizadas a través de bytes_to_complex().

        Returns
        -------
        True si la lectura fue exitosa.
        """

    @abstractmethod
    def bytes_to_complex(
        self, buffer: bytearray, num_samples: int
    ) -> np.ndarray:
        """
        Convierte un buffer raw a array complex64 normalizado.

        La normalización debe hacer que |max| ≈ 1.0 para una señal
        que satura el ADC. Cada implementación aplica el divisor
        correcto según su formato de muestras.

        Returns
        -------
        np.ndarray de dtype complex64, shape (num_samples,)
        """

    @abstractmethod
    def close(self) -> None:
        """Libera todos los recursos del hardware."""

    # ------------------------------------------------------------------
    # MÉTODO CONCRETO — disponible en todas las implementaciones
    # ------------------------------------------------------------------

    def receive_samples(self, num_samples: int = 4096) -> np.ndarray:
        """
        Lee muestras y las devuelve como complex64 normalizado.

        Implementación por defecto que combina read_samples() +
        bytes_to_complex(). Las subclases pueden sobreescribirla
        si necesitan lógica adicional (timeout handling, reconexión…).
        """
        buf = bytearray(num_samples * self.bytes_per_sample)
        if not self.read_samples(buf, num_samples):
            raise RuntimeError("read_samples() falló")
        return self.bytes_to_complex(buf, num_samples)

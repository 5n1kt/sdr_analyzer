# sdr/sdr_factory.py
# -*- coding: utf-8 -*-
#
# Fábrica de dispositivos SDR.
#
# Es el ÚNICO lugar del sistema donde se menciona una clase concreta
# de hardware. Todo el resto del código recibe un SDRDevice y trabaja
# con la interfaz abstracta.
#
# Uso en rf_controller.py
# ────────────────────────
#   from sdr.sdr_factory import SDRDeviceFactory
#
#   device = SDRDeviceFactory.create('bladerf')   # o 'rtlsdr', 'hackrf'…
#   device.initialize()
#   self.main.bladerf = device
#
# Agregar un nuevo SDR
# ────────────────────
# 1. Crear sdr/mi_sdr_device.py con class MiSDRDevice(SDRDevice).
# 2. Implementar todos los métodos abstractos.
# 3. Registrar el nombre en SDRDeviceFactory._REGISTRY (una línea).
# 4. Listo — ningún otro archivo necesita cambios.

from __future__ import annotations
import logging
from typing import Optional

from sdr.sdr_device import SDRDevice

logger = logging.getLogger(__name__)


class SDRDeviceFactory:
    """
    Fábrica estática para instanciar drivers SDR por nombre.

    El registro es perezoso (lazy): las clases concretas se importan
    solo cuando se solicitan, por lo que los paquetes de hardware que
    no están instalados no causan ImportError al cargar la fábrica.
    """

    # ------------------------------------------------------------------
    # REGISTRO DE DRIVERS
    # Formato:  'nombre_clave': ('módulo', 'NombreClase')
    # ------------------------------------------------------------------
    _REGISTRY: dict[str, tuple[str, str]] = {
        'bladerf': ('sdr.bladerf_device',  'BladeRFDevice'),
        # Para agregar RTL-SDR cuando esté listo:
        # 'rtlsdr':  ('sdr.rtlsdr_device',  'RTLSDRDevice'),
        # Para HackRF:
        # 'hackrf':  ('sdr.hackrf_device',  'HackRFDevice'),
    }

    @classmethod
    def create(cls, device_type: str) -> SDRDevice:
        """
        Crea e instancia el driver correspondiente a `device_type`.

        Parameters
        ----------
        device_type : str
            Clave del driver. Los valores registrados son:
            'bladerf'  — BladeRF 2.0 micro (libbladeRF)

        Returns
        -------
        SDRDevice
            Instancia del driver, sin inicializar.
            Llama a device.initialize() después de obtenerla.

        Raises
        ------
        ValueError  si device_type no está registrado.
        ImportError si la librería del hardware no está instalada.
        """
        key = device_type.lower().strip()

        if key not in cls._REGISTRY:
            available = ', '.join(f"'{k}'" for k in cls._REGISTRY)
            raise ValueError(
                f"SDR desconocido: '{device_type}'. "
                f"Opciones disponibles: {available}"
            )

        module_path, class_name = cls._REGISTRY[key]

        try:
            import importlib
            module  = importlib.import_module(module_path)
            klass   = getattr(module, class_name)
            device  = klass()
            logger.info(f"✅ Driver creado: {class_name} ('{key}')")
            return device

        except ImportError as exc:
            raise ImportError(
                f"No se pudo importar el driver '{key}' desde '{module_path}'. "
                f"¿Está instalada la librería de hardware? Detalle: {exc}"
            ) from exc

    @classmethod
    def available_drivers(cls) -> list[str]:
        """Retorna la lista de claves de drivers registrados."""
        return list(cls._REGISTRY.keys())

    @classmethod
    def register(cls, key: str, module_path: str, class_name: str) -> None:
        """
        Registra un driver externo en tiempo de ejecución.

        Útil para plugins o drivers que no forman parte del paquete
        principal pero se quieren integrar sin modificar este archivo.

        Parameters
        ----------
        key         : clave de identificación (ej. 'midevice')
        module_path : ruta del módulo Python (ej. 'plugins.mi_sdr_device')
        class_name  : nombre de la clase (ej. 'MiSDRDevice')
        """
        cls._REGISTRY[key.lower()] = (module_path, class_name)
        logger.info(f"Driver registrado: '{key}' → {module_path}.{class_name}")

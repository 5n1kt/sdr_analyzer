# sdr/__init__.py
# -*- coding: utf-8 -*-
#
# Paquete de abstracción de hardware SDR.
#
# Exportaciones públicas del paquete:
#   SDRDevice       — interfaz abstracta
#   SDRRange        — dataclass de rango (reemplaza tipos de libbladeRF)
#   SDRDeviceFactory — fábrica para obtener instancias de drivers

from sdr.sdr_device  import SDRDevice, SDRRange
from sdr.sdr_factory import SDRDeviceFactory

__all__ = ['SDRDevice', 'SDRRange', 'SDRDeviceFactory']

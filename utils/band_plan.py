# utils/band_plan.py
# -*- coding: utf-8 -*-

"""
Gestor de Bandas de Frecuencia (Band Plan)
Utiliza el archivo bands.json existente para la configuración.
Similar a la funcionalidad de GQRX.
"""

import json
import os
import logging
from typing import List, Dict, Tuple, Optional
from PyQt5.QtGui import QColor


class BandPlan:
    """
    Gestor de bandas de frecuencia para visualización en el espectro.
    Carga las bandas desde el archivo bands.json existente.
    """
    
    # Mapeo de tipos a colores (si no están definidos en el JSON)
    TYPE_COLORS = {
        'broadcast': '#00aa00',      # FM, TV
        'aviation': '#aa8800',       # Aeronáutica
        'amateur': '#00aa88',        # Radioaficionados
        'cellular': '#aa44aa',       # Telefonía móvil
        'wifi': '#ffaa44',           # WiFi
        'drone': '#ff8844',          # Drones
        'fpv': '#ff8844',            # FPV
        'radar': '#ff4444',          # Radar
        'microwave': '#aa8844',      # Microondas
        'communications': '#888888', # Comunicaciones
        'custom': '#88aa44',         # Personalizada
        'unknown': '#666666'         # Desconocido
    }
    
    def __init__(self, config_file='config/bands.json'):
        self.logger = logging.getLogger(__name__)
        self.config_file = config_file
        self.bands: List[Dict] = []
        self._load_bands_from_json()
    
    def _load_bands_from_json(self):
        """Carga las bandas desde el archivo bands.json existente."""
        try:
            # Buscar en múltiples ubicaciones posibles
            possible_paths = [
                self.config_file,
                'config/bands.json',
                '../config/bands.json',
                os.path.join(os.path.dirname(__file__), '../config/bands.json')
            ]
            
            loaded = False
            for path in possible_paths:
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.bands = data.get('bands', [])
                        loaded = True
                        self.logger.info(f"✅ Cargadas {len(self.bands)} bandas desde {path}")
                        break
            
            if not loaded:
                self.logger.warning(f"⚠️ Archivo bands.json no encontrado, usando bandas por defecto")
                self._load_default_bands()
            
            # Procesar bandas para visualización
            self._process_bands_for_display()
            
        except Exception as e:
            self.logger.error(f"Error cargando bandas: {e}")
            self._load_default_bands()
    
    def _process_bands_for_display(self):
        """Procesa las bandas para añadir información de visualización."""
        for band in self.bands:
            # Asegurar que tenga un color basado en su tipo
            if 'color' not in band:
                band_type = band.get('type', 'unknown')
                band['color'] = self.TYPE_COLORS.get(band_type, '#888888')
            
            # Extraer rango en MHz
            range_str = band.get('range', '')
            if range_str:
                try:
                    # Parsear rango como "88 - 108 MHz" o "2400 - 2483 MHz"
                    parts = range_str.split('-')
                    if len(parts) == 2:
                        start_mhz = float(parts[0].strip())
                        # Extraer el número antes de 'MHz'
                        end_part = parts[1].strip().split()[0]
                        end_mhz = float(end_part)
                        band['start_mhz'] = start_mhz
                        band['end_mhz'] = end_mhz
                except:
                    # Si falla el parsing, usar valores por defecto
                    band['start_mhz'] = 0
                    band['end_mhz'] = 0
            
            # Asegurar campos necesarios para visualización
            band['visible'] = not band.get('unavailable', False)
            band['priority'] = self._get_band_priority(band)
    
    def _get_band_priority(self, band: Dict) -> int:
        """Determina la prioridad de visualización de la banda."""
        priority_map = {
            'broadcast': 5,
            'aviation': 5,
            'amateur': 5,
            'wifi': 5,
            'drone': 5,
            'fpv': 5,
            'cellular': 4,
            'radar': 3,
            'microwave': 3,
            'communications': 4,
            'custom': 5
        }
        return priority_map.get(band.get('type', 'unknown'), 3)
    
    def _load_default_bands(self):
        """Carga bandas por defecto si no se encuentra el JSON."""
        self.bands = [
            {
                'name': 'FM Broadcast',
                'display': 'FM Broadcast',
                'start_mhz': 88.0,
                'end_mhz': 108.0,
                'type': 'broadcast',
                'color': '#00aa00',
                'visible': True,
                'priority': 5,
                'description': 'Radio FM comercial'
            },
            {
                'name': 'Airband',
                'display': 'Airband',
                'start_mhz': 118.0,
                'end_mhz': 137.0,
                'type': 'aviation',
                'color': '#aa8800',
                'visible': True,
                'priority': 5,
                'description': 'Comunicaciones aeronáuticas'
            },
            {
                'name': 'WiFi 2.4 GHz',
                'display': 'WiFi 2.4 GHz',
                'start_mhz': 2400.0,
                'end_mhz': 2483.0,
                'type': 'wifi',
                'color': '#ffaa44',
                'visible': True,
                'priority': 5,
                'description': 'Redes WiFi y dispositivos ISM'
            },
            {
                'name': 'DRON 5.8 GHz',
                'display': 'DRON 5.8 GHz',
                'start_mhz': 5645.0,
                'end_mhz': 5945.0,
                'type': 'drone',
                'color': '#ff8844',
                'visible': True,
                'priority': 5,
                'description': 'DJI, Autel, FPV analógico'
            }
        ]
        self.logger.info(f"✅ Cargadas {len(self.bands)} bandas por defecto")
    
    def get_bands_in_range(self, start_mhz: float, end_mhz: float) -> List[Dict]:
        """
        Retorna las bandas que están total o parcialmente dentro del rango visible.
        """
        visible_bands = []
        
        for band in self.bands:
            # Saltar bandas no disponibles
            if band.get('unavailable', False):
                continue
            
            # Saltar bandas marcadas como no visibles
            if not band.get('visible', True):
                continue
            
            # Obtener límites de la banda
            band_start = band.get('start_mhz', 0)
            band_end = band.get('end_mhz', 0)
            
            if band_start == 0 and band_end == 0:
                continue
            
            # Verificar si la banda se superpone con el rango visible
            if band_end >= start_mhz and band_start <= end_mhz:
                visible_bands.append(band)
        
        # Ordenar por prioridad (mayor prioridad primero)
        visible_bands.sort(key=lambda b: b.get('priority', 0), reverse=True)
        
        return visible_bands
    
    def get_band_color(self, band: Dict, alpha: int = 70) -> QColor:
        """
        Retorna el color de la banda con transparencia.
        """
        color_str = band.get('color', '#888888')
        color = QColor(color_str)
        color.setAlpha(alpha)
        return color
    
    def get_band_by_frequency(self, freq_mhz: float) -> Optional[Dict]:
        """
        Retorna la banda que contiene la frecuencia dada.
        """
        for band in self.bands:
            if band.get('unavailable', False):
                continue
            
            band_start = band.get('start_mhz', 0)
            band_end = band.get('end_mhz', 0)
            
            if band_start <= freq_mhz <= band_end:
                return band
        return None
    
    def get_band_tooltip(self, freq_mhz: float) -> str:
        """
        Retorna un tooltip con información de la banda en una frecuencia.
        """
        band = self.get_band_by_frequency(freq_mhz)
        if band:
            tooltip = f"{band.get('display', band.get('name', 'Unknown'))}\n"
            tooltip += f"{band.get('description', '')}\n" if band.get('description') else ""
            tooltip += f"{band.get('start_mhz', 0):.1f}-{band.get('end_mhz', 0):.1f} MHz"
            
            if band.get('type'):
                tooltip += f"\nTipo: {band.get('type')}"
            
            return tooltip
        return "Banda no definida"
    
    def get_all_bands(self) -> List[Dict]:
        """Retorna todas las bandas cargadas."""
        return self.bands
    
    def get_band_names(self) -> List[str]:
        """Retorna los nombres de todas las bandas."""
        return [band.get('display', band.get('name', '')) for band in self.bands 
                if not band.get('unavailable', False)]
    
    def set_band_visibility(self, band_name: str, visible: bool):
        """
        Cambia la visibilidad de una banda específica.
        """
        for band in self.bands:
            band_display = band.get('display', band.get('name', ''))
            if band_display == band_name:
                band['visible'] = visible
                self.logger.debug(f"📡 Banda {band_name} visible={visible}")
                return
    
    def get_bands_by_type(self, band_type: str) -> List[Dict]:
        """
        Retorna todas las bandas de un tipo específico.
        """
        return [band for band in self.bands 
                if band.get('type') == band_type and not band.get('unavailable', False)]
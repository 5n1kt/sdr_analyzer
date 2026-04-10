# utils/band_manager.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import json
import os
import logging
import numpy as np


# =======================================================================
# GESTOR DE BANDAS DE FRECUENCIA
# =======================================================================
class BandManager:
    """
    Gestor de bandas de frecuencia.
    Carga las bandas desde un archivo JSON de configuración.
    """
    
    def __init__(self, config_file='config/bands.json'):
        self.logger = logging.getLogger(__name__)
        self.config_file = config_file
        self.bands = []
        self.bands_by_index = {}
        self.load_bands()
    
    def load_bands(self):
        """Carga las bandas desde el archivo JSON."""
        try:
            # Crear directorio si no existe
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.bands = data.get('bands', [])
                self.logger.info(f"✅ Cargadas {len(self.bands)} bandas desde {self.config_file}")
            else:
                self.logger.warning(f"⚠️ Archivo de bandas no encontrado: {self.config_file}")
                self.bands = self._get_default_bands()
                self.save_bands()
            
            # Indexar por índice
            self.bands_by_index = {band['index']: band for band in self.bands}
            
        except Exception as e:
            self.logger.error(f"Error cargando bandas: {e}")
            self.bands = self._get_default_bands()
    
    def save_bands(self):
        """Guarda las bandas en el archivo JSON."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({'bands': self.bands}, f, indent=2, ensure_ascii=False)
            self.logger.info(f"✅ Guardadas {len(self.bands)} bandas en {self.config_file}")
        except Exception as e:
            self.logger.error(f"Error guardando bandas: {e}")
    
    def get_band(self, index):
        """Obtiene una banda por su índice."""
        return self.bands_by_index.get(index)
    
    def get_all_bands(self):
        """Obtiene todas las bandas ordenadas por índice."""
        return sorted(self.bands, key=lambda b: b['index'])
    
    def get_display_names(self):
        """Obtiene lista de nombres para mostrar en el combobox."""
        return [(band['index'], band['display']) for band in self.get_all_bands()]
    
    def generate_frequencies(self, band):
        """
        Genera la lista de frecuencias para una banda según su configuración.
        """
        if band.get('unavailable', False):
            return []
        
        freq_config = band.get('frequencies', {})
        if not freq_config:
            return []
        
        freq_type = freq_config.get('type')
        
        if freq_type == 'range':
            # Rango simple con paso
            start = freq_config['start']
            end = freq_config['end']
            step = freq_config['step']
            return [round(f, 3) for f in np.arange(start, end + step/2, step)]
        
        elif freq_type == 'list':
            # Lista explícita
            return freq_config['values']
        
        elif freq_type == 'range_multi':
            # Múltiples rangos
            frequencies = []
            for r in freq_config.get('ranges', []):
                start = r['start']
                end = r['end']
                step = r['step']
                frequencies.extend([round(f, 3) for f in np.arange(start, end + step/2, step)])
            
            # Añadir valores extra
            frequencies.extend(freq_config.get('extra', []))
            return sorted(list(set(frequencies)))
        
        elif freq_type == 'generator':
            # Usar generador específico
            func_name = freq_config.get('function')
            if func_name == 'drone_24ghz':
                return self._generate_drone_24ghz()
            elif func_name == 'drone_58ghz':
                return self._generate_drone_58ghz()
        
        return []
    
    def _generate_drone_24ghz(self):
        """Genera frecuencias para la banda de 2.4 GHz."""
        frequencies = []
        frequencies.extend([2400 + i*20 for i in range(5)])  # DJI
        frequencies.extend([2410, 2430, 2450, 2470])        # Autel
        frequencies.extend([2412, 2437, 2462])              # WiFi
        return sorted(list(set(frequencies)))
    
    def _generate_drone_58ghz(self):
        """Genera frecuencias para la banda de 5.8 GHz."""
        frequencies = []
        frequencies.extend([5735, 5755, 5775, 5795, 5815, 5835, 5855])  # DJI
        frequencies.extend([5740, 5760, 5780, 5800, 5820, 5840, 5860])  # Autel
        frequencies.extend([5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917])  # Raceband
        frequencies.extend([5705, 5745, 5785, 5825, 5865])  # Bandas A/B
        frequencies.extend([5645, 5665, 5685, 5885, 5905, 5925, 5945])  # Bandas E/F
        return sorted(list(set(frequencies)))
    
    def _get_default_bands(self):
        """Bands por defecto si no hay archivo."""
        return [
            {
                "index": 0,
                "name": "CB Radio",
                "display": "⚠️ CB Radio",
                "range": "26 - 28 MHz",
                "type": "communications",
                "mode": "NARROW",
                "unavailable": True,
                "note": "Fuera de rango del BladeRF (70MHz - 6GHz)",
                "frequencies": []
            },
            {
                "index": 1,
                "name": "FM Broadcast",
                "display": "📻 FM Broadcast",
                "range": "88 - 108 MHz",
                "type": "broadcast",
                "mode": "WIDE",
                "description": "Radio FM comercial",
                "frequencies": {
                    "type": "range",
                    "start": 88,
                    "end": 108,
                    "step": 0.1
                }
            }
            # ... más bandas por defecto
        ]

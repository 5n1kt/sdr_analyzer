# -*- coding: utf-8 -*-

"""
Band Manager - Frequency Band Configuration
============================================
Manages frequency bands for signal detection.

Loads bands from config/bands.json with support for:
    - Simple range: {type: "range", start, end, step}
    - List: {type: "list", values: [...]}
    - Multiple ranges: {type: "range_multi", ranges: [...], extra: [...]}
    - Generators: {type: "generator", function: "drone_24ghz"}

Format of bands.json:
    {
        "bands": [
            {
                "index": 0,
                "name": "FM Broadcast",
                "display": "📻 FM Broadcast",
                "range": "88 - 108 MHz",
                "type": "broadcast",
                "mode": "WIDE",
                "frequencies": {"type": "range", "start": 88, "end": 108, "step": 0.1}
            },
            ...
        ]
    }
"""

import json
import os
import logging
import numpy as np


# ============================================================================
# BAND MANAGER
# ============================================================================

class BandManager:
    """
    Manages frequency bands loaded from JSON configuration.
    
    Provides methods for:
        - Loading bands from config/bands.json
        - Generating frequency lists for scanning
        - Getting band display names
        - Saving band configurations
    """
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, config_file: str = 'config/bands.json'):
        """
        Initialize band manager.
        
        Args:
            config_file: Path to bands.json configuration file
        """
        self.logger = logging.getLogger(__name__)
        self.config_file = config_file
        self.bands = []
        self.bands_by_index = {}
        self.load_bands()
    
    # ------------------------------------------------------------------------
    # BAND LOADING
    # ------------------------------------------------------------------------
    
    def load_bands(self) -> None:
        """Load bands from JSON file."""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.bands = data.get('bands', [])
                self.logger.info(f"✅ Loaded {len(self.bands)} bands from {self.config_file}")
            else:
                self.logger.warning(f"⚠️ Band file not found: {self.config_file}")
                self.bands = self._get_default_bands()
                self.save_bands()
            
            # Index by index
            self.bands_by_index = {band['index']: band for band in self.bands}
            
        except Exception as e:
            self.logger.error(f"Error loading bands: {e}")
            self.bands = self._get_default_bands()
    
    def save_bands(self) -> None:
        """Save bands to JSON file."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({'bands': self.bands}, f, indent=2, ensure_ascii=False)
            self.logger.info(f"✅ Saved {len(self.bands)} bands to {self.config_file}")
        except Exception as e:
            self.logger.error(f"Error saving bands: {e}")
    
    def _get_default_bands(self) -> list:
        """Return default bands if no file exists."""
        return [
            {
                "index": 0,
                "name": "CB Radio",
                "display": "⚠️ CB Radio",
                "range": "26 - 28 MHz",
                "type": "communications",
                "mode": "NARROW",
                "unavailable": True,
                "note": "Out of BladeRF range (70MHz - 6GHz)",
                "frequencies": []
            },
            {
                "index": 1,
                "name": "FM Broadcast",
                "display": "📻 FM Broadcast",
                "range": "88 - 108 MHz",
                "type": "broadcast",
                "mode": "WIDE",
                "description": "Commercial FM radio",
                "frequencies": {
                    "type": "range",
                    "start": 88,
                    "end": 108,
                    "step": 0.1
                }
            },
            {
                "index": 2,
                "name": "Airband",
                "display": "✈️ Airband",
                "range": "118 - 137 MHz",
                "type": "aviation",
                "mode": "NARROW",
                "description": "Aircraft communications (AM)",
                "frequencies": {
                    "type": "range",
                    "start": 118,
                    "end": 137,
                    "step": 0.025
                }
            },
            {
                "index": 3,
                "name": "Amateur 2m",
                "display": "📡 2m Band",
                "range": "144 - 148 MHz",
                "type": "amateur",
                "mode": "NARROW",
                "description": "Amateur radio 2m band",
                "frequencies": {
                    "type": "range",
                    "start": 144,
                    "end": 148,
                    "step": 0.025
                }
            },
            {
                "index": 4,
                "name": "WiFi 2.4 GHz",
                "display": "📶 WiFi 2.4 GHz",
                "range": "2400 - 2483 MHz",
                "type": "wifi",
                "mode": "WIDE",
                "description": "WiFi and ISM devices",
                "frequencies": {
                    "type": "range",
                    "start": 2400,
                    "end": 2483,
                    "step": 5
                }
            },
            {
                "index": 5,
                "name": "Drone 2.4 GHz",
                "display": "🚁 Drone 2.4 GHz",
                "range": "2400 - 2483 MHz",
                "type": "drone",
                "mode": "WIDE",
                "description": "DJI, Autel control links",
                "frequencies": {
                    "type": "generator",
                    "function": "drone_24ghz"
                }
            },
            {
                "index": 6,
                "name": "Drone 5.8 GHz",
                "display": "🚁 Drone 5.8 GHz",
                "range": "5645 - 5945 MHz",
                "type": "drone",
                "mode": "WIDE",
                "description": "DJI, Autel, FPV analog video",
                "frequencies": {
                    "type": "generator",
                    "function": "drone_58ghz"
                }
            },
            {
                "index": 7,
                "name": "Radar S-Band",
                "display": "📡 Radar S-Band",
                "range": "2700 - 2900 MHz",
                "type": "radar",
                "mode": "WIDE",
                "description": "Weather radar",
                "frequencies": {
                    "type": "range",
                    "start": 2700,
                    "end": 2900,
                    "step": 5
                }
            }
        ]
    
    # ------------------------------------------------------------------------
    # QUERY METHODS
    # ------------------------------------------------------------------------
    
    def get_band(self, index: int) -> dict:
        """Get band by index."""
        return self.bands_by_index.get(index)
    
    def get_all_bands(self) -> list:
        """Get all bands sorted by index."""
        return sorted(self.bands, key=lambda b: b['index'])
    
    def get_display_names(self) -> list:
        """Get list of (index, display_name) for combobox."""
        return [(band['index'], band['display']) for band in self.get_all_bands()]
    
    # ------------------------------------------------------------------------
    # FREQUENCY GENERATION
    # ------------------------------------------------------------------------
    
    def generate_frequencies(self, band: dict) -> list:
        """
        Generate frequency list for a band based on its configuration.
        
        Args:
            band: Band dictionary with 'frequencies' configuration
        
        Returns:
            List of frequencies in MHz
        """
        if band.get('unavailable', False):
            return []
        
        freq_config = band.get('frequencies', {})
        if not freq_config:
            return []
        
        freq_type = freq_config.get('type')
        
        if freq_type == 'range':
            start = freq_config['start']
            end = freq_config['end']
            step = freq_config['step']
            return [round(f, 3) for f in np.arange(start, end + step/2, step)]
        
        elif freq_type == 'list':
            return freq_config['values']
        
        elif freq_type == 'range_multi':
            frequencies = []
            for r in freq_config.get('ranges', []):
                start = r['start']
                end = r['end']
                step = r['step']
                frequencies.extend([round(f, 3) for f in np.arange(start, end + step/2, step)])
            frequencies.extend(freq_config.get('extra', []))
            return sorted(list(set(frequencies)))
        
        elif freq_type == 'generator':
            func_name = freq_config.get('function')
            if func_name == 'drone_24ghz':
                return self._generate_drone_24ghz()
            elif func_name == 'drone_58ghz':
                return self._generate_drone_58ghz()
        
        return []
    
    # ------------------------------------------------------------------------
    # FREQUENCY GENERATORS
    # ------------------------------------------------------------------------
    
    def _generate_drone_24ghz(self) -> list:
        """Generate frequencies for 2.4 GHz drone band."""
        frequencies = []
        # DJI channels
        frequencies.extend([2400 + i*20 for i in range(5)])
        # Autel channels
        frequencies.extend([2410, 2430, 2450, 2470])
        # WiFi channels
        frequencies.extend([2412, 2437, 2462])
        return sorted(list(set(frequencies)))
    
    def _generate_drone_58ghz(self) -> list:
        """Generate frequencies for 5.8 GHz drone band."""
        frequencies = []
        # DJI channels
        frequencies.extend([5735, 5755, 5775, 5795, 5815, 5835, 5855])
        # Autel channels
        frequencies.extend([5740, 5760, 5780, 5800, 5820, 5840, 5860])
        # Raceband
        frequencies.extend([5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917])
        # Band A/B
        frequencies.extend([5705, 5745, 5785, 5825, 5865])
        # Band E/F
        frequencies.extend([5645, 5665, 5685, 5885, 5905, 5925, 5945])
        return sorted(list(set(frequencies)))
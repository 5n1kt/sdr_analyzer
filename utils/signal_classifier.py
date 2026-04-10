# utils/signal_classifier.py
# -*- coding: utf-8 -*-

class SignalClassifier:
    """Clasifica señales por su ancho de banda y características"""
    
    # Rangos típicos por tipo de señal
    SIGNAL_TYPES = {
        'NARROW': {
            'name': '📻 Narrow',
            'min_bw_khz': 10,
            'max_bw_khz': 200,
            'description': 'Radio FM, comunicaciones',
            'color': '#00ff00'
        },
        'MEDIUM': {
            'name': '📺 Medium',
            'min_bw_khz': 200,
            'max_bw_khz': 2000,
            'description': 'DVB-T, TV digital',
            'color': '#ffff00'
        },
        'WIDE': {
            'name': '📡 Wide',
            'min_bw_khz': 2000,
            'max_bw_khz': 10000,
            'description': 'FPV, Wi-Fi, banda ancha',
            'color': '#ff8800'
        },
        'UNKNOWN': {
            'name': '❓ Desconocido',
            'min_bw_khz': 0,
            'max_bw_khz': float('inf'),
            'description': 'Señal no clasificada',
            'color': '#888888'
        }
    }
    
    @classmethod
    def classify(cls, bandwidth_hz):
        """Clasifica una señal por su ancho de banda en Hz"""
        bw_khz = bandwidth_hz / 1000
        
        for signal_type, info in cls.SIGNAL_TYPES.items():
            if info['min_bw_khz'] <= bw_khz <= info['max_bw_khz']:
                return signal_type, info
        
        return 'UNKNOWN', cls.SIGNAL_TYPES['UNKNOWN']
    
    @classmethod
    def get_type_info(cls, signal_type):
        """Obtiene información de un tipo de señal"""
        return cls.SIGNAL_TYPES.get(signal_type, cls.SIGNAL_TYPES['UNKNOWN'])
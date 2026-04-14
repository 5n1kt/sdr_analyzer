# -*- coding: utf-8 -*-

"""
Signal Classifier - Bandwidth-based Classification
===================================================
Classifies signals by their bandwidth and characteristics.

Classification types:
    - NARROW: 10-200 kHz (FM radio, communications)
    - MEDIUM: 200-2000 kHz (DVB-T, digital TV)
    - WIDE: 2-10 MHz (FPV, Wi-Fi, broadband)
    - UNKNOWN: Unclassified
"""


class SignalClassifier:
    """
    Classifies signals by bandwidth.
    
    Provides color coding and descriptions for each signal type.
    """
    
    # Signal type definitions
    SIGNAL_TYPES = {
        'NARROW': {
            'name': '📻 Narrow',
            'min_bw_khz': 10,
            'max_bw_khz': 200,
            'description': 'FM radio, communications',
            'color': '#00ff00'
        },
        'MEDIUM': {
            'name': '📺 Medium',
            'min_bw_khz': 200,
            'max_bw_khz': 2000,
            'description': 'DVB-T, digital TV',
            'color': '#ffff00'
        },
        'WIDE': {
            'name': '📡 Wide',
            'min_bw_khz': 2000,
            'max_bw_khz': 10000,
            'description': 'FPV, Wi-Fi, broadband',
            'color': '#ff8800'
        },
        'UNKNOWN': {
            'name': '❓ Unknown',
            'min_bw_khz': 0,
            'max_bw_khz': float('inf'),
            'description': 'Unclassified signal',
            'color': '#888888'
        }
    }
    
    @classmethod
    def classify(cls, bandwidth_hz: float) -> tuple:
        """
        Classify signal by bandwidth.
        
        Args:
            bandwidth_hz: Signal bandwidth in Hz
        
        Returns:
            Tuple (signal_type, type_info_dict)
        """
        bw_khz = bandwidth_hz / 1000
        
        for signal_type, info in cls.SIGNAL_TYPES.items():
            if info['min_bw_khz'] <= bw_khz <= info['max_bw_khz']:
                return signal_type, info
        
        return 'UNKNOWN', cls.SIGNAL_TYPES['UNKNOWN']
    
    @classmethod
    def get_type_info(cls, signal_type: str) -> dict:
        """
        Get information for a signal type.
        
        Args:
            signal_type: 'NARROW', 'MEDIUM', 'WIDE', or 'UNKNOWN'
        
        Returns:
            Dictionary with name, description, color, etc.
        """
        return cls.SIGNAL_TYPES.get(signal_type, cls.SIGNAL_TYPES['UNKNOWN'])
    
    @classmethod
    def get_color(cls, bandwidth_hz: float) -> str:
        """
        Get color for a bandwidth.
        
        Args:
            bandwidth_hz: Signal bandwidth in Hz
        
        Returns:
            Color hex string
        """
        _, info = cls.classify(bandwidth_hz)
        return info['color']
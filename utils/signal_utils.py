# utils/signal_utils.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import numpy as np
from scipy import signal
import logging


# =======================================================================
# UTILIDADES PARA PROCESAMIENTO DE SEÑALES
# =======================================================================
class SignalUtils:
    """Utilidades para procesamiento de señales"""
    
    # -----------------------------------------------------------------------
    # MÉTODOS ESTÁTICOS - VENTANAS
    # -----------------------------------------------------------------------
    @staticmethod
    def apply_window(data, window_type='hann'):
        """Aplica ventana a los datos"""
        windows = {
            'rectangular': np.ones(len(data)),
            'hann': np.hanning(len(data)),
            'hamming': np.hamming(len(data)),
            'blackman': np.blackman(len(data)),
            'kaiser': np.kaiser(len(data), 14)
        }
        
        window = windows.get(window_type.lower(), windows['hann'])
        return data * window
    
    # -----------------------------------------------------------------------
    # MÉTODOS ESTÁTICOS - FFT Y PSD
    # -----------------------------------------------------------------------
    @staticmethod
    def calculate_fft(iq_data, fft_size=1024, window='hann'):
        """Calcula FFT con parámetros configurables"""
        # Asegurar tamaño correcto
        if len(iq_data) < fft_size:
            # Zero-padding
            iq_data = np.pad(iq_data, (0, fft_size - len(iq_data)), 'constant')
        elif len(iq_data) > fft_size:
            # Truncar
            iq_data = iq_data[:fft_size]
        
        # Aplicar ventana
        iq_windowed = SignalUtils.apply_window(iq_data, window)
        
        # Calcular FFT
        fft_data = np.fft.fftshift(np.fft.fft(iq_windowed))
        
        # Convertir a dBm (asumiendo 50 ohms)
        power = np.abs(fft_data)**2 / 50  # Potencia en vatios
        power_mw = power * 1000  # Convertir a mW
        power_dbm = 10 * np.log10(power_mw + 1e-12)  # Evitar log(0)
        
        return power_dbm
    
    @staticmethod
    def calculate_psd(iq_data, sample_rate, fft_size=1024, window='hann'):
        """Calcula densidad espectral de potencia"""
        # Calcular FFT
        fft_mag = SignalUtils.calculate_fft(iq_data, fft_size, window)
        
        # Normalizar por resolución de frecuencia
        freq_resolution = sample_rate / fft_size
        psd = fft_mag - 10 * np.log10(freq_resolution)
        
        # Crear eje de frecuencia
        freq_axis = np.linspace(-sample_rate/2, sample_rate/2, fft_size)
        
        return freq_axis, psd
    
    # -----------------------------------------------------------------------
    # MÉTODOS ESTÁTICOS - DETECCIÓN
    # -----------------------------------------------------------------------
    @staticmethod
    def detect_peaks(psd, threshold=-50, min_distance=10):
        """Detecta picos en el espectro"""
        from scipy.signal import find_peaks
        
        peaks, properties = find_peaks(
            psd,
            height=threshold,
            distance=min_distance
        )
        
        return peaks, properties
    
    @staticmethod
    def calculate_snr(psd, signal_band, noise_band):
        """Calcula relación señal/ruido"""
        signal_power = np.mean(psd[signal_band])
        noise_power = np.mean(psd[noise_band])
        
        if noise_power > 0:
            snr = signal_power - noise_power  # En dB
        else:
            snr = float('inf')
        
        return snr
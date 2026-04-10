# bladerf_manager.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import numpy as np
from bladerf import _bladerf
import logging
import time
import threading


# =======================================================================
# GESTOR PRINCIPAL DE BLADERF
# =======================================================================
class BladeRFManager:
    """Gestor profesional para BladeRF 2.0 micro"""
    
    # -----------------------------------------------------------------------
    # CONSTANTES DE CLASE
    # -----------------------------------------------------------------------
    FLOOR_DB = -120.0
    BYTES_PER_SAMPLE = 4
    DEFAULT_SAMPLES_PER_BLOCK = 8192
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Estado del dispositivo
        self.sdr = None
        self.rx_ch = None
        self.is_initialized = False
        self.streaming = False
        self.lock = threading.Lock()
        
        # Parámetros de operación
        self.frequency = 100e6
        self.sample_rate = 2e6
        self.bandwidth = 1e6
        self.gain = 50
        self.gain_mode = _bladerf.GainMode.Manual
        
        # Configuración de buffer
        self.buffer_size = 8192
        self.num_buffers = 16
        self.num_transfers = 8
        self.bytes_per_sample = self.BYTES_PER_SAMPLE
        self.samples_per_block = self.DEFAULT_SAMPLES_PER_BLOCK
        
        # Rangos (se obtienen después de inicializar)
        self.sample_rate_range = None
        self.bandwidth_range = None
        self.freq_range = None
        self.gain_range = None
        self.gain_modes = None
    
    def __del__(self):
        """Destructor - asegura cerrar el dispositivo"""
        self.close()
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - INICIALIZACIÓN Y CONFIGURACIÓN
    # -----------------------------------------------------------------------
    def initialize(self):
        """Inicializa el dispositivo BladeRF"""
        with self.lock:
            try:
                devices = _bladerf.get_device_list()
                if not devices:
                    raise RuntimeError("No se encontró ningún BladeRF")
                
                self.logger.info(f"Dispositivos encontrados: {devices[0]}")
                
                self.sdr = _bladerf.BladeRF()
                self.logger.info(f"libbladeRF version: {_bladerf.version()}")
                self.logger.info(f"Firmware: {self.sdr.get_fw_version()}")
                self.logger.info(f"FPGA: {self.sdr.get_fpga_version()}")
                
                self.rx_ch = self.sdr.Channel(_bladerf.CHANNEL_RX(0))
                
                # Obtener rangos
                self.sample_rate_range = self.rx_ch.sample_rate_range
                self.bandwidth_range = self.rx_ch.bandwidth_range
                self.freq_range = self.rx_ch.frequency_range
                self.gain_range = self.sdr.get_gain_range(_bladerf.CHANNEL_RX(0))
                self.gain_modes = self.rx_ch.gain_modes
                
                self.logger.info(
                    f"Rango frecuencia: {self.freq_range.min/1e6:.0f}-"
                    f"{self.freq_range.max/1e6:.0f} MHz"
                )
                self.logger.info(
                    f"Rango sample rate: {self.sample_rate_range.min/1e6:.1f}-"
                    f"{self.sample_rate_range.max/1e6:.1f} MHz"
                )
                self.logger.info(
                    f"Rango ganancia: {self.gain_range.min}-{self.gain_range.max} dB"
                )
                
                # Configuración inicial
                self._apply_rf_settings()
                self._setup_sync_stream()
                
                self.is_initialized = True
                self.logger.info("BladeRF inicializado correctamente")
                return True
                
            except Exception as e:
                self.logger.error(f"Error inicializando BladeRF: {e}")
                raise
    
    def configure(self, params):
        """Configura parámetros del SDR de manera segura"""
        with self.lock:
            # Si SOLO está cambiando la frecuencia, usar el método rápido
            if len(params) == 1 and 'frequency' in params:
                return self.set_frequency_fast(params['frequency'])
            
            was_streaming = self.streaming
            
            try:
                # Detener stream si está activo
                if was_streaming:
                    self._stop_stream_nolock()
                
                # Actualizar parámetros
                if 'frequency' in params and params['frequency'] is not None:
                    self.frequency = params['frequency']
                    self.frequency = max(
                        self.freq_range.min, 
                        min(self.frequency, self.freq_range.max)
                    )
                
                if 'sample_rate' in params and params['sample_rate'] is not None:
                    self.sample_rate = params['sample_rate']
                    self.sample_rate = max(
                        self.sample_rate_range.min,
                        min(self.sample_rate, self.sample_rate_range.max)
                    )
                
                if 'bandwidth' in params and params['bandwidth'] is not None:
                    self.bandwidth = params['bandwidth']
                    self.bandwidth = max(
                        self.bandwidth_range.min,
                        min(self.bandwidth, self.bandwidth_range.max)
                    )
                
                if 'gain' in params:
                    self.gain = params['gain']
                    self.gain = max(
                        self.gain_range.min,
                        min(self.gain, self.gain_range.max)
                    )
                
                if 'gain_mode' in params:
                    self.gain_mode = params['gain_mode']
                
                # Aplicar configuración RF
                self._apply_rf_settings()
                
                # Reconfigurar stream
                self._setup_sync_stream()
                
                # Reanudar stream si estaba activo
                if was_streaming:
                    self._start_stream_nolock()
                
                return True
                    
            except Exception as e:
                self.logger.error(f"Error configurando BladeRF: {e}")
                return False
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - CONTROL DE STREAMING
    # -----------------------------------------------------------------------
    def start_stream(self):
        """Inicia streaming de manera segura"""
        with self.lock:
            self._start_stream_nolock()
    
    def stop_stream(self):
        """Detiene streaming de manera segura"""
        with self.lock:
            self._stop_stream_nolock()
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - RECEPCIÓN DE DATOS
    # -----------------------------------------------------------------------
    def receive_samples(self, num_samples=4096):
        """Recibe muestras IQ del dispositivo"""
        if not self.is_initialized:
            raise RuntimeError("BladeRF no inicializado")
        
        with self.lock:
            if not self.streaming:
                self._start_stream_nolock()
        
        try:
            bytes_needed = num_samples * self.bytes_per_sample
            buf = bytearray(bytes_needed)
            
            try:
                self.sdr.sync_rx(buf, num_samples)
            except _bladerf.TimeoutError:
                self.logger.error("Timeout en sync_rx. Reiniciando stream...")
                with self.lock:
                    self._stop_stream_nolock()
                    self._setup_sync_stream()
                    self._start_stream_nolock()
                # Reintentar una vez
                self.sdr.sync_rx(buf, num_samples)
            except _bladerf.DeviceError as e:
                self.logger.error(f"Error de dispositivo BladeRF: {e}")
                # Intentar reconectar
                self.close()
                time.sleep(1)
                self.initialize()
                raise RuntimeError(f"Dispositivo reiniciado por error: {e}")
            
            iq_data = self.bytes_to_complex(buf, num_samples)
            
            # Verificar saturación
            max_val = np.max(np.abs(iq_data))
            if max_val > 0.9:
                self.logger.warning(f"ADC cerca de saturación: {max_val:.2f}")
            
            return iq_data
            
        except Exception as e:
            self.logger.error(f"Error recibiendo muestras: {e}")
            raise
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - GETTERS/SETTERS
    # -----------------------------------------------------------------------
    def get_frequency(self):
        """Obtiene frecuencia actual"""
        with self.lock:
            return self.rx_ch.frequency if self.rx_ch else 0
    
    def set_frequency_fast(self, frequency_hz):
        """Cambiar frecuencia rápidamente sin reiniciar el stream"""
        with self.lock:
            try:
                if not self.is_initialized or self.rx_ch is None:
                    self.logger.error("BladeRF no inicializado")
                    return False
                
                # Validar rango
                frequency_hz = max(
                    self.freq_range.min, 
                    min(frequency_hz, self.freq_range.max)
                )
                
                self.logger.info(f"📡 Cambio rápido a: {frequency_hz/1e6:.3f} MHz")
                
                # Cambiar SOLO la frecuencia
                self.rx_ch.frequency = int(frequency_hz)
                self.frequency = frequency_hz
                
                self.logger.info(f"✅ Frecuencia cambiada a: {frequency_hz/1e6:.3f} MHz")
                return True
                
            except Exception as e:
                self.logger.error(f"Error en cambio rápido de frecuencia: {e}")
                return False
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - LIMPIEZA
    # -----------------------------------------------------------------------
    def close(self):
        """Cierra conexión con el dispositivo"""
        with self.lock:
            self._stop_stream_nolock()
            if self.rx_ch:
                try:
                    self.rx_ch.enable = False
                except:
                    pass
            if self.sdr:
                try:
                    self.sdr = None
                except:
                    pass
            self.is_initialized = False
            self.logger.info("BladeRF desconectado")
    
    # -----------------------------------------------------------------------
    # MÉTODOS ESTÁTICOS PÚBLICOS
    # -----------------------------------------------------------------------
    @staticmethod
    def bytes_to_complex(buffer, num_samples):
        """Convierte buffer de bytes a array de complejos"""
        samples = np.frombuffer(buffer, dtype=np.int16, count=num_samples*2)
        i_samples = samples[0::2].astype(np.float32)
        q_samples = samples[1::2].astype(np.float32)
        return (i_samples + 1j * q_samples) / 2048.0
    
    # -----------------------------------------------------------------------
    # MÉTODOS PRIVADOS (con lock asumido)
    # -----------------------------------------------------------------------
    def _apply_rf_settings(self):
        """Aplica configuración RF (llamar con lock)"""
        self.rx_ch.frequency = int(self.frequency)
        self.rx_ch.sample_rate = int(self.sample_rate)
        self.rx_ch.bandwidth = int(self.bandwidth)
        self.rx_ch.gain_mode = self.gain_mode
        self.rx_ch.gain = int(self.gain)
    
    def _setup_sync_stream(self):
        """Configura el stream síncrono (llamar con lock)"""
        self.sdr.sync_config(
            layout=_bladerf.ChannelLayout.RX_X1,
            fmt=_bladerf.Format.SC16_Q11,
            num_buffers=self.num_buffers,
            buffer_size=self.buffer_size,
            num_transfers=self.num_transfers,
            stream_timeout=3500
        )
        self.logger.info("Stream síncrono configurado")
    
    def _start_stream_nolock(self):
        """Inicia streaming (llamar con lock)"""
        self.rx_ch.enable = True
        self.streaming = True
        self.logger.info("Streaming iniciado")
    
    def _stop_stream_nolock(self):
        """Detiene streaming (llamar con lock)"""
        if self.rx_ch:
            try:
                self.rx_ch.enable = False
            except:
                pass
        self.streaming = False
        self.logger.info("Streaming detenido")
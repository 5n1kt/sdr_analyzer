# controller/frequency_controller.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import logging
from PyQt5.QtCore import QTimer


# =======================================================================
# CONTROLADOR DE FRECUENCIA
# =======================================================================
class FrequencyController:
    """Gestiona la frecuencia y sincronización de widgets"""
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, main_controller):
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.FrequencyController")
        
        # Variables para debounce
        self.pending_frequency = None
        self.frequency_timer = None
        
        # Inicializar timer
        self._setup_timer()
    
    def _setup_timer(self):
        """Configura el timer para debounce"""
        self.frequency_timer = QTimer()
        self.frequency_timer.setSingleShot(True)
        self.frequency_timer.setInterval(300)
        self.frequency_timer.timeout.connect(self._apply_frequency_change)
    
    # -----------------------------------------------------------------------
    # MANEJO DE FRECUENCIA
    # -----------------------------------------------------------------------
    def on_frequency_spinner_changed(self, freq_mhz):
        """Manejador con debounce para cambios del spinner"""
        try:
            self.logger.info(f"🎯 Spinner cambió a: {freq_mhz:.3f} MHz (debounce)")
            
            # Actualizar UI
            self._update_frequency_ui(freq_mhz)
            
            # Guardar pendiente y reiniciar timer
            self.pending_frequency = freq_mhz
            self.frequency_timer.start()
            
        except Exception as e:
            self.logger.error(f"Error en on_frequency_spinner_changed: {e}")
    
    def on_frequency_changed_from_plot(self, freq_mhz):
        """Manejador para cambios desde el plot (marcador)"""
        try:
            self.logger.info(f"🎯 Frecuencia desde plot: {freq_mhz:.3f} MHz")
            
            # Sincronizar todos los widgets
            self.sync_frequency_widgets(freq_mhz)
            
            # Actualizar rango
            self.main._update_plot_range(freq_mhz)
            
            # Aplicar al SDR si está corriendo
            if self.main.is_running and self.main.bladerf:
                self.pending_frequency = freq_mhz
                self.frequency_timer.start()
            
        except Exception as e:
            self.logger.error(f"Error en on_frequency_changed_from_plot: {e}")
    
    def on_double_spinbox_freq_changed(self):
        """Manejador para doubleSpinBox"""
        try:
            freq_mhz = self.main.doubleSpinBox_freq.value()
            self.logger.info(f"📻 Frecuencia desde doubleSpinBox: {freq_mhz:.3f} MHz")
            
            # Sincronizar widgets
            self.sync_frequency_widgets(freq_mhz)
            
            # Actualizar rango
            self.main._update_plot_range(freq_mhz)
            
            # Aplicar al SDR directamente
            if self.main.is_running and self.main.bladerf:
                self._apply_to_sdr(freq_mhz)
            
        except Exception as e:
            self.logger.error(f"Error en doubleSpinBox: {e}")
    
    # -----------------------------------------------------------------------
    # SINCRONIZACIÓN DE WIDGETS
    # -----------------------------------------------------------------------
    def sync_frequency_widgets(self, freq_mhz):
        """
        Sincroniza todos los widgets de frecuencia con un valor.
        """
        # DoubleSpinBox principal
        if hasattr(self.main, 'doubleSpinBox_freq'):
            self.main.doubleSpinBox_freq.blockSignals(True)
            self.main.doubleSpinBox_freq.setValue(freq_mhz)
            self.main.doubleSpinBox_freq.blockSignals(False)
        
        # RF widget
        if hasattr(self.main, 'rf_widget') and hasattr(self.main.rf_widget, 'doubleSpinBox_freq'):
            self.main.rf_widget.doubleSpinBox_freq.blockSignals(True)
            self.main.rf_widget.doubleSpinBox_freq.setValue(freq_mhz)
            self.main.rf_widget.doubleSpinBox_freq.blockSignals(False)
        
        # Frequency spinner
        if hasattr(self.main, 'frequency_spinner'):
            self.main.frequency_spinner.setFrequency(freq_mhz)
        
        # Marcador en el plot
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.set_frequency(freq_mhz)
        
        self.logger.debug(f"🔄 Widgets sincronizados a {freq_mhz:.3f} MHz")
    
    def _update_frequency_ui(self, freq_mhz):
        """Actualiza UI sin aplicar al hardware"""
        # DoubleSpinBox principal
        if hasattr(self.main, 'doubleSpinBox_freq'):
            self.main.doubleSpinBox_freq.blockSignals(True)
            self.main.doubleSpinBox_freq.setValue(freq_mhz)
            self.main.doubleSpinBox_freq.blockSignals(False)
        
        # RF widget
        if hasattr(self.main, 'rf_widget') and hasattr(self.main.rf_widget, 'doubleSpinBox_freq'):
            self.main.rf_widget.doubleSpinBox_freq.blockSignals(True)
            self.main.rf_widget.doubleSpinBox_freq.setValue(freq_mhz)
            self.main.rf_widget.doubleSpinBox_freq.blockSignals(False)
        
        # Marcador
        if hasattr(self.main, 'spectrum_plot'):
            self.main.spectrum_plot.set_frequency(freq_mhz)
            power = self.main.spectrum_plot._get_power_at_frequency(freq_mhz)
            if hasattr(self.main.spectrum_plot, 'freq_marker'):
                self.main.spectrum_plot.freq_marker.set_power(power)
        
        # Rango
        self.main._update_plot_range(freq_mhz)
    
    # -----------------------------------------------------------------------
    # APLICAR AL HARDWARE
    # -----------------------------------------------------------------------
    def _apply_frequency_change(self):
        """Aplica el cambio de frecuencia al SDR (después del debounce)"""
        if self.pending_frequency is None:
            return
        
        freq_mhz = self.pending_frequency
        self.logger.info(f"📡 Aplicando frecuencia al SDR: {freq_mhz:.3f} MHz")
        
        self._apply_to_sdr(freq_mhz)
        self.pending_frequency = None
    
    def _apply_to_sdr(self, freq_mhz):
        """Aplica frecuencia al SDR si está disponible"""
        if not (self.main.is_running and self.main.bladerf):
            return False
        
        if hasattr(self.main.bladerf, 'set_frequency_fast'):
            success = self.main.bladerf.set_frequency_fast(freq_mhz * 1e6)
            if success:
                self.logger.info(f"✅ Frecuencia SDR actualizada (rápido)")
                return True
            else:
                self.logger.error(f"❌ Error en cambio rápido")
        else:
            settings = {'frequency': freq_mhz * 1e6}
            success = self.main.bladerf.configure(settings)
            if success:
                self.logger.info(f"✅ Frecuencia SDR actualizada")
                return True
        
        return False

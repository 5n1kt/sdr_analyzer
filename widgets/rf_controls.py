# widgets/rf_controls.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
from PyQt5.QtWidgets import QDockWidget
from PyQt5.QtCore import pyqtSignal
from PyQt5.uic import loadUi
import logging


# =======================================================================
# WIDGET DE CONTROL RF
# =======================================================================
class RFControlsWidget(QDockWidget):
    """Widget de control de parámetros RF - BLOQUEO VISIBLE"""
    
    # -----------------------------------------------------------------------
    # SEÑALES
    # -----------------------------------------------------------------------
    settings_changed = pyqtSignal(dict)
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, bladerf_manager):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        # Referencias externas
        self.bladerf = bladerf_manager
        
        # Estado
        self.is_running = False
        self.pending_sample_rate = None
        self.pending_bandwidth = None
        
        # Cargar UI
        loadUi('ui/rf_controls_widget.ui', self)
        
        # Configurar UI
        self.setup_ui()
        
        # Conectar señales
        self.setup_connections()
    
    # -----------------------------------------------------------------------
    # CONFIGURACIÓN DE UI
    # -----------------------------------------------------------------------
    def setup_ui(self):
        """Configura elementos de UI"""
        # FRECUENCIA - siempre habilitada
        self.doubleSpinBox_freq.setDecimals(3)
        self.doubleSpinBox_freq.setSuffix(" MHz")
        self.doubleSpinBox_freq.setRange(70, 6000)
        self.doubleSpinBox_freq.setValue(100)
        
        # BLOQUEAR SEÑALES MIENTRAS CONFIGURAMOS
        self.comboBox_sample_rate.blockSignals(True)
        self.comboBox_bandwidth.blockSignals(True)
        
        # SAMPLE RATE - se bloquea durante captura
        rates = [2e6, 5e6, 10e6, 20e6, 40e6, 56e6]
        for rate in rates:
            self.comboBox_sample_rate.addItem(f"{rate/1e6:.1f} MSPS", rate)
        self.comboBox_sample_rate.setCurrentIndex(0)
        
        # BANDWIDTH - se bloquea durante captura
        bandwidths = [1.5e6, 2.5e6, 5e6, 10e6, 20e6, 28e6]
        for bw in bandwidths:
            self.comboBox_bandwidth.addItem(f"{bw/1e6:.1f} MHz", bw)
        self.comboBox_bandwidth.setCurrentIndex(0)
        
        # DESBLOQUEAR SEÑALES
        self.comboBox_sample_rate.blockSignals(False)
        self.comboBox_bandwidth.blockSignals(False)
        
        # GANANCIA - siempre habilitada
        self.horizontalSlider_gain.setRange(0, 73)
        self.horizontalSlider_gain.setValue(50)
        self.horizontalSlider_gain.valueChanged.connect(
            lambda v: self.label_gain_value.setText(f"{v} dB")
        )
        
        # MODO DE GANANCIA
        self.comboBox_gain_mode.addItems(["Manual", "Default", "Fast AGC", "Slow AGC", "Hybrid"])
        
        # AGC
        self.checkBox_agc.toggled.connect(self.on_agc_toggled)
    
    def setup_connections(self):
        """Conecta señales de los controles"""
        self.doubleSpinBox_freq.editingFinished.connect(self.on_frequency_changed)
        self.comboBox_sample_rate.currentIndexChanged.connect(self.on_sample_rate_changed)
        self.comboBox_bandwidth.currentIndexChanged.connect(self.on_bandwidth_changed)
        self.horizontalSlider_gain.valueChanged.connect(self.on_gain_changed)
        self.comboBox_gain_mode.currentIndexChanged.connect(self.on_gain_mode_changed)
        self.checkBox_agc.toggled.connect(self.on_agc_toggled)
        #self.pushButton_start_stop.clicked.connect(self.apply_settings)
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - CONTROL DE ESTADO
    # -----------------------------------------------------------------------
    def set_controls_enabled(self, enabled):
        """Habilita/deshabilita controles visualmente"""
        self.comboBox_sample_rate.setEnabled(enabled)
        self.comboBox_bandwidth.setEnabled(enabled)
    
    def on_capture_started(self):
        """Llamado cuando comienza la captura"""
        self.is_running = True
        self.set_controls_enabled(False)
        self.logger.info("🔒 Sample Rate y Bandwidth bloqueados")
    
    def on_capture_stopped(self):
        """Llamado cuando termina la captura"""
        self.is_running = False
        self.set_controls_enabled(True)
        self.logger.info("🔓 Sample Rate y Bandwidth desbloqueados")
        
        # Aplicar cambios pendientes
        settings = {}
        if self.pending_sample_rate:
            settings['sample_rate'] = self.pending_sample_rate
            self.logger.info(
                f"✅ Aplicando Sample Rate pendiente: "
                f"{self.pending_sample_rate/1e6:.1f} MSPS"
            )
            self.pending_sample_rate = None
        
        if self.pending_bandwidth:
            settings['bandwidth'] = self.pending_bandwidth
            self.logger.info(
                f"✅ Aplicando Bandwidth pendiente: "
                f"{self.pending_bandwidth/1e6:.1f} MHz"
            )
            self.pending_bandwidth = None
        
        if settings:
            self.settings_changed.emit(settings)
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - RESET A VALORES POR DEFECTO
    # -----------------------------------------------------------------------
    def reset_settings(self):
        """Resetea todos los parámetros RF a valores por defecto"""
        self.logger.info("🔄 Reseteando configuración RF a valores por defecto")
        
        self.blockSignals(True)
        
        # Frecuencia por defecto: 100 MHz
        self.doubleSpinBox_freq.setValue(100.0)
        
        # Sample rate por defecto: 2 MSPS (primer elemento)
        self.comboBox_sample_rate.setCurrentIndex(0)
        
        # Bandwidth por defecto: 1.5 MHz (primer elemento)
        self.comboBox_bandwidth.setCurrentIndex(0)
        
        # Ganancia por defecto: 50 dB
        self.horizontalSlider_gain.setValue(50)
        self.label_gain_value.setText("50 dB")
        
        # Modo de ganancia por defecto: Manual (índice 0)
        self.comboBox_gain_mode.setCurrentIndex(0)
        
        # AGC por defecto: Desactivado
        self.checkBox_agc.setChecked(False)
        
        # Limpiar cambios pendientes
        self.pending_sample_rate = None
        self.pending_bandwidth = None
        
        self.blockSignals(False)
        
        # Aplicar cambios
        self.apply_settings()
        
        self.logger.info("✅ Configuración RF reseteada")
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - SETTERS DE RANGOS
    # -----------------------------------------------------------------------
    def set_frequency_range(self, freq_range):
        """Establece el rango de frecuencia permitido"""
        min_mhz = freq_range.min / 1e6
        max_mhz = freq_range.max / 1e6
        step_mhz = freq_range.step / 1e6
        
        self.doubleSpinBox_freq.setRange(min_mhz, max_mhz)
        self.doubleSpinBox_freq.setSingleStep(step_mhz)
        
        self.logger.debug(f"📻 Rango frecuencia: {min_mhz:.0f}-{max_mhz:.0f} MHz")
    
    def set_gain_range(self, gain_range):
        """Establece el rango de ganancia permitido"""
        self.horizontalSlider_gain.setRange(
            int(gain_range.min), 
            int(gain_range.max)
        )
        self.logger.debug(f"📻 Rango ganancia: {gain_range.min}-{gain_range.max} dB")
    
    def set_sample_rate_range(self, sr_range):
        """Configura las opciones de sample rate según el rango del hardware"""
        # BLOQUEAR SEÑALES
        self.comboBox_sample_rate.blockSignals(True)
        self.comboBox_sample_rate.clear()
        
        rates = [2e6, 5e6, 10e6, 20e6, 40e6, 56e6]
        valid_rates = []
        
        for rate in rates:
            if sr_range.min <= rate <= sr_range.max:
                valid_rates.append(rate)
                self.comboBox_sample_rate.addItem(f"{rate/1e6:.1f} MSPS", rate)
        
        if self.comboBox_sample_rate.count() == 0:
            min_rate = sr_range.min
            self.comboBox_sample_rate.addItem(f"{min_rate/1e6:.1f} MSPS", min_rate)
        
        # Establecer índice por defecto (el más cercano a 2 MHz)
        target_rate = 2e6
        best_index = 0
        best_diff = float('inf')
        for i in range(self.comboBox_sample_rate.count()):
            rate = self.comboBox_sample_rate.itemData(i)
            if rate is not None:
                diff = abs(rate - target_rate)
                if diff < best_diff:
                    best_diff = diff
                    best_index = i
        self.comboBox_sample_rate.setCurrentIndex(best_index)
        
        # DESBLOQUEAR SEÑALES
        self.comboBox_sample_rate.blockSignals(False)
        
        self.logger.info(f"📻 Sample rates configurados: {[f'{r/1e6:.1f}' for r in valid_rates]}")

    def set_bandwidth_range(self, bw_range):
        """Configura las opciones de bandwidth según el rango del hardware"""
        # BLOQUEAR SEÑALES
        self.comboBox_bandwidth.blockSignals(True)
        self.comboBox_bandwidth.clear()
        
        bandwidths = [1.5e6, 2.5e6, 5e6, 10e6, 20e6, 28e6, 56e6]
        valid_bws = []
        
        for bw in bandwidths:
            if bw_range.min <= bw <= bw_range.max:
                valid_bws.append(bw)
                self.comboBox_bandwidth.addItem(f"{bw/1e6:.1f} MHz", bw)
        
        if self.comboBox_bandwidth.count() == 0:
            min_bw = bw_range.min
            self.comboBox_bandwidth.addItem(f"{min_bw/1e6:.1f} MHz", min_bw)
        
        # Establecer índice por defecto (el más cercano a 1.5 MHz)
        target_bw = 1.5e6
        best_index = 0
        best_diff = float('inf')
        for i in range(self.comboBox_bandwidth.count()):
            bw = self.comboBox_bandwidth.itemData(i)
            if bw is not None:
                diff = abs(bw - target_bw)
                if diff < best_diff:
                    best_diff = diff
                    best_index = i
        self.comboBox_bandwidth.setCurrentIndex(best_index)
        
        # DESBLOQUEAR SEÑALES
        self.comboBox_bandwidth.blockSignals(False)
        
        self.logger.info(f"📻 Bandwidths configurados: {[f'{b/1e6:.1f}' for b in valid_bws]}")
    
    def set_gain_modes(self, gain_modes):
        """
        Configura el combo box con los modos de ganancia soportados.
        Ordena por el valor numérico del modo (mode.value) si está disponible.
        """
        mode_names = {
            0: "Default",
            1: "Manual",
            2: "Fast AGC",
            3: "Slow AGC",
            4: "Hybrid"
        }
        self.comboBox_gain_mode.clear()

        # Intentar ordenar por el valor numérico. Si falla, intentar por nombre.
        try:
            # Asumimos que cada objeto en gain_modes tiene un atributo 'value'
            # o es directamente un entero. Ordenamos por ese valor.
            sorted_modes = sorted(gain_modes, key=lambda mode: mode.value if hasattr(mode, 'value') else mode)
        except TypeError:
            # Si la ordenación falla (p.ej., si no se puede acceder a 'value'),
            # ordenamos por su representación como string como fallback.
            self.logger.warning("No se pudo ordenar por valor numérico, ordenando por nombre.")
            sorted_modes = sorted(gain_modes, key=str)

        for mode in sorted_modes:
            # Intentar obtener un valor numérico para usarlo como clave en mode_names
            mode_value = mode.value if hasattr(mode, 'value') else mode
            display_name = mode_names.get(mode_value, str(mode))
            self.comboBox_gain_mode.addItem(display_name, userData=mode) # Guardamos el objeto original como userData
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - GETTERS
    # -----------------------------------------------------------------------
    def get_settings(self):
        """Obtiene configuración actual"""
        freq_mhz = self.doubleSpinBox_freq.value()
        freq_hz = freq_mhz * 1e6
        
        # CORREGIDO: Verificar que currentData() no sea None
        sr_hz = self.pending_sample_rate
        if sr_hz is None:
            sr_hz = self.comboBox_sample_rate.currentData()
            if sr_hz is None and self.comboBox_sample_rate.count() > 0:
                # Fallback: usar el primer item si currentData es None
                sr_hz = self.comboBox_sample_rate.itemData(0)
                self.logger.warning(f"⚠️ Usando sample rate por defecto: {sr_hz/1e6:.1f} MSPS")
        
        bw_hz = self.pending_bandwidth
        if bw_hz is None:
            bw_hz = self.comboBox_bandwidth.currentData()
            if bw_hz is None and self.comboBox_bandwidth.count() > 0:
                # Fallback: usar el primer item si currentData es None
                bw_hz = self.comboBox_bandwidth.itemData(0)
                self.logger.warning(f"⚠️ Usando bandwidth por defecto: {bw_hz/1e6:.1f} MHz")
        
        gain = self.horizontalSlider_gain.value()
        
        gain_mode_index = self.comboBox_gain_mode.currentIndex()
        gain_modes = [1, 0, 2, 3, 4]
        
        return {
            'frequency': freq_hz,
            'sample_rate': sr_hz,
            'bandwidth': bw_hz,
            'gain': gain,
            'gain_mode': gain_modes[gain_mode_index] if gain_mode_index < len(gain_modes) else 1,
            'agc': self.checkBox_agc.isChecked()
        }
    
    def get_pending_changes(self):
        """Retorna los cambios pendientes"""
        changes = {}
        if self.pending_sample_rate:
            changes['sample_rate'] = self.pending_sample_rate
        if self.pending_bandwidth:
            changes['bandwidth'] = self.pending_bandwidth
        return changes
    
    # -----------------------------------------------------------------------
    # SLOTS DE SEÑALES
    # -----------------------------------------------------------------------
    def on_frequency_changed(self):
        """Cambio de frecuencia - siempre inmediato"""
        settings = {'frequency': self.doubleSpinBox_freq.value() * 1e6}
        self.settings_changed.emit(settings)
        self.logger.debug(f"📻 Frecuencia cambiada: {self.doubleSpinBox_freq.value():.3f} MHz")
    
    def on_sample_rate_changed(self):
        """Cambio de sample rate - pendiente si está capturando"""
        sr_hz = self.comboBox_sample_rate.currentData()
        
        if sr_hz is None:
            self.logger.error("❌ Error: currentData() retornó None para sample rate")
            # Intentar recuperar del primer item
            if self.comboBox_sample_rate.count() > 0:
                sr_hz = self.comboBox_sample_rate.itemData(0)
                self.logger.warning(f"⚠️ Usando valor por defecto: {sr_hz/1e6:.1f} MSPS")
            else:
                return
        
        if self.is_running:
            self.pending_sample_rate = sr_hz
            self.logger.info(f"⏳ Sample Rate pendiente: {sr_hz/1e6:.1f} MSPS")
        else:
            self.pending_sample_rate = None
            settings = {'sample_rate': sr_hz}
            self.logger.debug(f"📻 Sample Rate aplicado: {sr_hz/1e6:.1f} MSPS")
            self.settings_changed.emit(settings)

    def on_bandwidth_changed(self):
        """Cambio de bandwidth - pendiente si está capturando"""
        # CORREGIDO: Verificar que currentData() no sea None
        bw_hz = self.comboBox_bandwidth.currentData()
        
        if bw_hz is None:
            self.logger.error("❌ Error: currentData() retornó None para bandwidth")
            return
        
        if self.is_running:
            self.pending_bandwidth = bw_hz
            self.logger.info(f"⏳ Bandwidth pendiente: {bw_hz/1e6:.1f} MHz")
        else:
            self.pending_bandwidth = None
            settings = {'bandwidth': bw_hz}
            self.logger.debug(f"📻 Bandwidth aplicado: {bw_hz/1e6:.1f} MHz")
            self.settings_changed.emit(settings)
    
    def on_gain_changed(self):
        """Cambio de ganancia - siempre inmediato"""
        gain = self.horizontalSlider_gain.value()
        settings = {'gain': gain}
        self.settings_changed.emit(settings)
        self.logger.debug(f"📻 Ganancia cambiada: {gain} dB")
    
    def on_gain_mode_changed(self):
        """Cambio de modo de ganancia - siempre inmediato"""
        gain_mode_index = self.comboBox_gain_mode.currentIndex()
        gain_modes = [1, 0, 2, 3, 4]  # Mapeo a valores de libbladeRF
        
        if gain_mode_index < len(gain_modes):
            settings = {'gain_mode': gain_modes[gain_mode_index]}
            self.settings_changed.emit(settings)
            self.logger.debug(f"📻 Modo de ganancia cambiado: {self.comboBox_gain_mode.currentText()}")
    
    def on_agc_toggled(self, checked):
        """Maneja toggle de AGC"""
        # Cuando AGC está activado, deshabilitar controles manuales de ganancia
        self.comboBox_gain_mode.setEnabled(not checked)
        self.horizontalSlider_gain.setEnabled(not checked)
        self.label_gain_value.setEnabled(not checked)
        
        settings = {'agc': checked}
        self.settings_changed.emit(settings)
        
        if checked:
            self.logger.info("📻 AGC activado")
        else:
            self.logger.info("📻 AGC desactivado")
    
    def apply_settings(self):
        """Aplica configuración actual (botón Aplicar)"""
        settings = self.get_settings()
        self.settings_changed.emit(settings)
        self.logger.info("📻 Configuración RF aplicada manualmente")
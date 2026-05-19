# -*- coding: utf-8 -*-

"""
TSCM Chart Widget - Visualización de actividad de señales
==========================================================
Dos gráficas con el mismo rango espectral:
1. Acumulativa (historial de detecciones)
2. Tiempo real (señales activas actuales)
"""

import logging
import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QColor
import pyqtgraph as pg


class TSCMChartWidget(QWidget):
    """
    Widget con dos gráficas TSCM que comparten el mismo rango espectral.
    """
    
    frequency_selected = pyqtSignal(float)
    range_changed = pyqtSignal(float, float)
    cleared = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # Datos
        self.historical_counts = {}
        self.current_detections = []
        self.freq_min = 0
        self.freq_max = 0
        self._updating_range = False
        
        # Configurar UI
        self.setup_ui()
        
        # Timer para decaer histórico
        self.decay_timer = QTimer()
        self.decay_timer.timeout.connect(self._decay_historical)
        self.decay_timer.start(10000)
        
        self.logger.info("✅ TSCMChartWidget inicializado")
    
    def setup_ui(self):
        """Configura la interfaz."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # ===== GRÁFICA 1: ACTIVIDAD ACUMULADA =====
        self.historical_plot = pg.PlotWidget()
        self.historical_plot.setLabel('bottom', 'Frecuencia', units='MHz')
        self.historical_plot.setLabel('left', 'Detecciones', units='')
        self.historical_plot.setTitle('<b>📈 ACTIVIDAD ACUMULADA</b>')
        self.historical_plot.setMinimumHeight(180)
        self.historical_plot.setBackground(QColor(25, 25, 35))
        self.historical_plot.showGrid(x=True, y=True, alpha=0.3)
        
        # Barras para histórico - se crean dinámicamente
        self.historical_bars = None
        
        self.historical_plot.sigRangeChanged.connect(self._on_range_changed)
        
        layout.addWidget(self.historical_plot)
        
        # Botones
        btn_layout = QHBoxLayout()
        self.clear_btn = QPushButton("🗑️ LIMPIAR HISTORIAL")
        self.clear_btn.setMaximumWidth(150)
        self.clear_btn.clicked.connect(self.clear_historical)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        
        self.range_label = QLabel("")
        self.range_label.setStyleSheet("color: #888888; font-size: 8pt;")
        btn_layout.addWidget(self.range_label)
        
        layout.addLayout(btn_layout)
        
        # Separador
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        
        # ===== GRÁFICA 2: TIEMPO REAL =====
        self.real_plot = pg.PlotWidget()
        self.real_plot.setLabel('bottom', 'Frecuencia', units='MHz')
        self.real_plot.setLabel('left', 'Potencia', units='dB')
        self.real_plot.setTitle('<b>⚡ ACTIVIDAD EN TIEMPO REAL</b>')
        self.real_plot.setMinimumHeight(200)
        self.real_plot.setBackground(QColor(25, 25, 35))
        self.real_plot.showGrid(x=True, y=True, alpha=0.3)
        self.real_plot.setYRange(-100, -20)
        
        self.real_bars = None
        
        self.real_plot.sigRangeChanged.connect(self._on_range_changed)
        
        layout.addWidget(self.real_plot)
        
        # ===== PANEL DE INFORMACIÓN =====
        self.info_frame = QFrame()
        self.info_frame.setFrameShape(QFrame.StyledPanel)
        self.info_frame.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
            }
        """)
        self.info_frame.setMinimumHeight(50)
        
        info_layout = QHBoxLayout(self.info_frame)
        info_layout.setContentsMargins(8, 4, 8, 4)
        
        self.selected_info = QLabel("📡 Haz clic en una barra para sintonizar")
        self.selected_info.setStyleSheet("color: #aaaaaa; font-size: 9pt;")
        info_layout.addWidget(self.selected_info)
        
        layout.addWidget(self.info_frame)
        
        # Conectar eventos de clic
        self.real_plot.scene().sigMouseClicked.connect(self._on_plot_click)
        self.historical_plot.scene().sigMouseClicked.connect(self._on_plot_click)
    
    def set_frequency_range(self, freq_min_mhz, freq_max_mhz):
        """Establece el rango de frecuencia para AMBAS gráficas."""
        if self._updating_range:
            return
        
        self._updating_range = True
        self.freq_min = freq_min_mhz
        self.freq_max = freq_max_mhz
        
        self.historical_plot.setXRange(freq_min_mhz, freq_max_mhz, padding=0)
        self.real_plot.setXRange(freq_min_mhz, freq_max_mhz, padding=0)
        
        self.range_label.setText(f"📡 Rango: {freq_min_mhz:.1f} - {freq_max_mhz:.1f} MHz")
        
        self._updating_range = False
    
    def _on_range_changed(self, plot, view_range):
        """Sincroniza el rango entre ambas gráficas."""
        if self._updating_range:
            return
        
        self._updating_range = True
        
        x_range = view_range[0]
        new_min = x_range[0]
        new_max = x_range[1]
        
        if plot == self.historical_plot:
            self.real_plot.setXRange(new_min, new_max, padding=0)
        else:
            self.historical_plot.setXRange(new_min, new_max, padding=0)
        
        self.freq_min = new_min
        self.freq_max = new_max
        self.range_label.setText(f"📡 Rango: {new_min:.1f} - {new_max:.1f} MHz")
        
        self.range_changed.emit(new_min, new_max)
        
        self._updating_range = False
    
    def update_detections(self, detections, freq_min_mhz, freq_max_mhz):
        """Actualiza las gráficas con nuevas detecciones."""
        if not detections:
            return
        
        self.current_detections = detections
        
        if freq_min_mhz != self.freq_min or freq_max_mhz != self.freq_max:
            self.set_frequency_range(freq_min_mhz, freq_max_mhz)
        
        # Acumular histórico (solo detecciones dentro del rango)
        for det in detections:
            freq = det.get('freq', 0)
            if freq > 0 and self.freq_min <= freq <= self.freq_max:
                self.historical_counts[freq] = self.historical_counts.get(freq, 0) + 1
        
        self._update_historical_plot()
        self._update_real_plot()
    
    def _update_historical_plot(self):
        """Actualiza gráfica acumulativa."""
        # Limpiar barras anteriores
        if self.historical_bars is not None:
            self.historical_plot.removeItem(self.historical_bars)
            self.historical_bars = None
        
        if not self.historical_counts:
            return
        
        # Preparar datos
        freqs = []
        counts = []
        
        for freq, count in sorted(self.historical_counts.items()):
            if self.freq_min <= freq <= self.freq_max:
                freqs.append(freq)
                counts.append(count)
        
        if not freqs:
            return
        
        # CORRECCIÓN: Usar diccionario de opciones para crear BarGraphItem
        opts = {
            'x': freqs,
            'height': counts,
            'width': 0.8,
            'brush': QColor(50, 150, 255, 180)
        }
        self.historical_bars = pg.BarGraphItem(**opts)
        self.historical_plot.addItem(self.historical_bars)
        
        # Ajustar Y
        if counts:
            self.historical_plot.setYRange(0, max(counts) + 2)
    
    def _update_real_plot(self):
        """Actualiza gráfica de tiempo real."""
        # Limpiar barras anteriores
        if self.real_bars is not None:
            self.real_plot.removeItem(self.real_bars)
            self.real_bars = None
        
        if not self.current_detections:
            return
        
        # Preparar datos
        freqs = []
        powers = []
        brushes = []
        
        for det in self.current_detections:
            freq = det.get('freq', 0)
            if self.freq_min <= freq <= self.freq_max:
                freqs.append(freq)
                power = det.get('power', -100)
                powers.append(power)
                
                # Color según potencia
                if power > -40:
                    brushes.append(QColor(255, 50, 50, 220))
                elif power > -60:
                    brushes.append(QColor(255, 200, 50, 220))
                elif power > -80:
                    brushes.append(QColor(50, 200, 50, 220))
                else:
                    brushes.append(QColor(80, 100, 255, 180))
        
        if not freqs:
            return
        
        # CORRECCIÓN: Usar diccionario de opciones para crear BarGraphItem
        opts = {
            'x': freqs,
            'height': powers,
            'width': 0.7,
            'brushes': brushes
        }
        self.real_bars = pg.BarGraphItem(**opts)
        self.real_plot.addItem(self.real_bars)
        
        if powers:
            max_power = max(powers)
            min_power = min(-100, max_power - 30)
            self.real_plot.setYRange(min_power, max_power + 10)
    
    def _on_plot_click(self, event):
        """Maneja clic en las gráficas."""
        plot = None
        if event.currentItem in self.real_plot.items():
            plot = self.real_plot
        elif event.currentItem in self.historical_plot.items():
            plot = self.historical_plot
        
        if plot is None:
            return
        
        pos = plot.plotItem.vb.mapSceneToView(event.scenePos())
        freq = pos.x()
        
        closest_det = None
        min_diff = 1.0
        
        for det in self.current_detections:
            diff = abs(det.get('freq', 0) - freq)
            if diff < min_diff:
                min_diff = diff
                closest_det = det
        
        if closest_det:
            self._show_detection_info(closest_det)
            self.frequency_selected.emit(closest_det.get('freq', 0))
    
    def _show_detection_info(self, det):
        """Muestra información detallada."""
        freq = det.get('freq', 0)
        power = det.get('power', -100)
        bw = det.get('bandwidth', 0)
        snr = det.get('snr', 0)
        sig_type = det.get('type', 'Desconocido')
        
        if power > -40:
            alert_level = "🔴 CRÍTICA"
        elif power > -60:
            alert_level = "🟡 ALTA"
        elif power > -80:
            alert_level = "🟢 MEDIA"
        else:
            alert_level = "⚪ BAJA"
        
        info_text = f"""
        <b>{sig_type}</b> &nbsp;&nbsp;|&nbsp;&nbsp;
        📍 <b>{freq:.4f}</b> MHz &nbsp;&nbsp;|&nbsp;&nbsp;
        📊 <b>{power:.1f}</b> dB &nbsp;&nbsp;|&nbsp;&nbsp;
        📏 <b>{bw:.2f}</b> MHz &nbsp;&nbsp;|&nbsp;&nbsp;
        📈 SNR: <b>{snr:.1f}</b> dB &nbsp;&nbsp;|&nbsp;&nbsp;
        {alert_level}
        """
        self.selected_info.setText(info_text)
        self.selected_info.setStyleSheet("color: #ffaa44; font-size: 9pt;")
    
    def _decay_historical(self):
        """Decae gradualmente el contador histórico."""
        decay_factor = 0.95
        to_remove = []
        
        for freq, count in self.historical_counts.items():
            new_count = int(count * decay_factor)
            if new_count < 1:
                to_remove.append(freq)
            else:
                self.historical_counts[freq] = new_count
        
        for freq in to_remove:
            del self.historical_counts[freq]
        
        if to_remove:
            self._update_historical_plot()
    
    def clear_historical(self):
        """Limpia el histórico."""
        self.historical_counts.clear()
        self._update_historical_plot()
        self.cleared.emit()
        self.logger.info("🗑️ Historial limpiado")
    
    def get_historical_data(self):
        """Retorna los datos históricos para exportación."""
        data = []
        for freq, count in self.historical_counts.items():
            data.append({
                'frequency_mhz': freq,
                'detection_count': count
            })
        return sorted(data, key=lambda x: x['frequency_mhz'])
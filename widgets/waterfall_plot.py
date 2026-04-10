# widgets/waterfall_plot.py
# -*- coding: utf-8 -*-
#
# CAMBIOS RESPECTO A LA VERSIÓN ANTERIOR
# ───────────────────────────────────────
# • __init__: añade self.last_alpha = 1.0
# • update_spectrum: añade parámetro alpha=1.0 y lo guarda en self.last_alpha
# • _delayed_update: aplica decay  α*spectrum + (1-α)*fila_anterior
#   cuando alpha < 1.0, lo que produce el efecto de persistencia visible.
#
# El resto del archivo es idéntico al original.

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QObject, QTimer, pyqtSignal
import logging


class WaterfallPlot(QObject):
    """Widget para waterfall trabajando en MHz"""

    updated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)

        # Configuración
        self.waterfall_height  = 128
        self.fft_size          = 1024
        self.waterfall_data    = None
        self.freq_min_mhz      = 0
        self.freq_max_mhz      = 0
        self.min_display_db    = -120
        self.max_display_db    = 0
        self.update_counter    = 0

        # Estado
        self.pending_update   = False
        self.last_spectrum    = None
        self.last_freq_axis   = None
        self.last_center_freq = None
        self.last_sample_rate = None
        self.last_alpha       = 1.0    # ← NUEVO: factor alpha de persistencia

        # Configurar plot
        self.plot_widget = pg.PlotWidget(labels={
            'left':   'Time',
            'bottom': 'Frequency [MHz]',
        })

        self.imageitem = pg.ImageItem()
        self.plot_widget.addItem(self.imageitem)

        self.plot_widget.setMouseEnabled(x=True, y=False)
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.hideButtons()

        # Timer para actualizaciones diferidas (≈30 fps)
        self.update_timer = QTimer()
        self.update_timer.setInterval(33)
        self.update_timer.timeout.connect(self._delayed_update)
        self.update_timer.start()

        self.reset_buffer()
        self.logger.info("✅ WaterfallPlot inicializado")

    # ------------------------------------------------------------------
    # MÉTODOS PÚBLICOS
    # ------------------------------------------------------------------

    def reset_buffer(self):
        """Reinicializar buffer"""
        self.waterfall_data = np.full(
            (self.waterfall_height, self.fft_size),
            self.min_display_db,
            dtype=np.float32,
        )
        if self.imageitem is not None:
            self._update_image()

    def resize_buffer(self, new_fft_size):
        if new_fft_size == self.fft_size:
            return
        self.logger.info(f"Redimensionando buffer: {self.fft_size} -> {new_fft_size}")
        self.fft_size = new_fft_size
        self.waterfall_data = np.full(
            (self.waterfall_height, self.fft_size),
            self.min_display_db,
            dtype=np.float32,
        )
        self._update_transform()
        self._update_image()

    def set_display_range(self, min_db, max_db):
        self.min_display_db = min_db
        self.max_display_db = max_db
        if self.imageitem is not None:
            self.imageitem.setLevels([min_db, max_db])
            self._update_image()

    def clear(self):
        if self.waterfall_data is not None:
            self.waterfall_data.fill(self.min_display_db)
            self._update_image()
            self.logger.debug("💧 Waterfall limpiado")

    def get_plot_widget(self):
        return self.plot_widget

    def get_image_item(self):
        return self.imageitem

    # ------------------------------------------------------------------
    # MÉTODOS DE ACTUALIZACIÓN
    # ------------------------------------------------------------------

    def update_spectrum(self, spectrum, freq_axis_mhz, center_freq_mhz,
                        sample_rate_mhz, alpha: float = 1.0):
        """
        Recibe nuevo espectro con eje en MHz.

        Parámetro alpha (novedad)
        ─────────────────────────
        alpha = 1.0  → sin persistencia: cada fila muestra el spectrum puro
        alpha < 1.0  → persistencia: nueva fila = α*spectrum + (1-α)*anterior
                       Viene de FFTController.update_spectrum y refleja el
                       valor del slider de persistencia del usuario.
        """
        self.last_spectrum    = spectrum
        self.last_freq_axis   = freq_axis_mhz
        self.last_center_freq = center_freq_mhz
        self.last_sample_rate = sample_rate_mhz
        self.last_alpha       = float(np.clip(alpha, 0.01, 1.0))  # ← guardar
        self.pending_update   = True

    def _delayed_update(self):
        """
        Actualización real con throttling.

        CORRECCIÓN DE PERSISTENCIA
        ──────────────────────────
        Antes:
            self.waterfall_data[-1, :] = spectrum
            → cada fila reemplazaba a la anterior sin decay.

        Ahora:
            Si alpha < 1.0, la nueva fila se mezcla con la fila que
            quedó en la posición [-2] tras el np.roll. Esto produce un
            efecto de "estela" descendente en el waterfall.
        """
        if not self.pending_update or self.last_spectrum is None:
            return

        try:
            spectrum    = self.last_spectrum
            center_freq = self.last_center_freq
            sample_rate = self.last_sample_rate
            alpha       = self.last_alpha

            # Adaptar tamaño de buffer si cambió el FFT
            if len(spectrum) != self.fft_size:
                self.fft_size = len(spectrum)
                self.reset_buffer()

            # Actualizar rango de frecuencia y transformación
            self.freq_min_mhz = center_freq - sample_rate / 2
            self.freq_max_mhz = center_freq + sample_rate / 2
            self._update_transform()

            # ── DESPLAZAR BUFFER: la fila [-1] sube a [-2] ────────────
            self.waterfall_data = np.roll(self.waterfall_data, -1, axis=0)

            # ── ESCRIBIR NUEVA FILA CON DECAY ─────────────────────────
            if alpha >= 1.0:
                # Sin persistencia: fila pura
                self.waterfall_data[-1, :] = spectrum
            else:
                # Con persistencia: mezcla con la fila anterior (ahora en [-2])
                # α=0.5 → 50% nuevo + 50% anterior → estela moderada
                # α=0.01 → casi todo el frame anterior → estela muy larga
                self.waterfall_data[-1, :] = (
                    alpha * spectrum
                    + (1.0 - alpha) * self.waterfall_data[-2, :]
                )

            self._update_image()
            self.pending_update = False

        except Exception as e:
            self.logger.error(f"Error en update diferido: {e}")
            self.pending_update = False

    def _update_image(self):
        if self.waterfall_data is not None and self.imageitem is not None:
            self.imageitem.setImage(self.waterfall_data.T, autoLevels=False)
            self.imageitem.setLevels([self.min_display_db, self.max_display_db])
            self.update_counter += 1
            self.updated.emit()

    def _update_transform(self):
        if self.fft_size > 1 and self.imageitem is not None:
            freq_width = self.freq_max_mhz - self.freq_min_mhz
            self.imageitem.setRect(
                self.freq_min_mhz, 0, freq_width, self.waterfall_height
            )
            self.plot_widget.setXRange(self.freq_min_mhz, self.freq_max_mhz)
            self.plot_widget.setYRange(0, self.waterfall_height)

    def set_colormap(self, colormap_name):
        """Mantenido por compatibilidad con ui_controller."""
        pass

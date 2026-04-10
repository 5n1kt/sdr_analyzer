# controller/playback_controller.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import os
import time
import logging
import traceback
from PyQt5.QtWidgets import QMessageBox, QApplication

from workers.iq_player import IQPlayer
from workers.shared_buffer import IQRingBuffer
from workers.fft_processor_zerocopy import FFTProcessorZeroCopy


# =======================================================================
# CONTROLADOR DE REPRODUCCIÓN
# =======================================================================
class PlaybackController:
    """Gestiona la reproducción de archivos IQ"""
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, main_controller):
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.PlaybackController")
    
    # -----------------------------------------------------------------------
    # MANEJO DE REPRODUCCIÓN
    # -----------------------------------------------------------------------
    def on_playback_requested(self, filename, play):
        """Manejador para solicitudes de reproducción"""
        if play:
            self.start_playback(filename)
        else:
            self.stop_playback()
    
    def start_playback(self, filename):
        """Inicia la reproducción de un archivo IQ"""
        try:
            # Detener reproducción anterior
            if self.main.is_playing_back:
                self.logger.info("⏹ Deteniendo reproducción anterior")
                self.stop_playback()
                QApplication.processEvents()
                time.sleep(0.3)
            
            self.logger.info(f"🎬 Iniciando reproducción: {filename}")
            
            # Verificar archivo
            if not self._verify_file(filename):
                return
            
            # Crear player
            self.main.player = IQPlayer()
            self._connect_player_signals()
            
            # Cargar archivo
            self.logger.info("📂 Cargando archivo...")
            if not self.main.player.load_file(filename):
                raise RuntimeError("No se pudo cargar el archivo")
            
            # Obtener configuración
            samples_per_block = self._get_samples_per_block()
            fft_settings = self._get_fft_settings()
            
            # Configurar player
            self.main.player.configure(
                samples_per_buffer=samples_per_block,
                speed=1.0,
                loop=False
            )
            
            # Actualizar UI con frecuencia del archivo
            self._update_ui_with_playback_info()
            
            # Crear pipeline de reproducción
            self._create_playback_pipeline(samples_per_block, fft_settings)
            
            # Iniciar reproducción
            self.logger.info("🚀 Iniciando FFTProcessor...")
            self.main.playback_fft_processor.start()
            
            self.logger.info("▶ Iniciando reproducción...")
            self.main.player.start_playback()
            
            # Actualizar estado
            self.main.is_playing_back = True
            self._update_ui_playback_state(True, filename)
            
            self.logger.info(f"✅ Reproducción iniciada correctamente")
            
        except Exception as e:
            self._handle_playback_error(e)
    
    def _verify_file(self, filename):
        """Verifica que el archivo existe"""
        if not os.path.exists(filename):
            self.logger.error(f"❌ Archivo no encontrado: {filename}")
            QMessageBox.critical(
                self.main, "Error", 
                f"No se encontró el archivo:\n{filename}"
            )
            return False
        return True
    
    def _connect_player_signals(self):
        """Conecta las señales del player"""
        p = self.main.player
        p.buffer_ready.connect(self._on_playback_buffer_ready)
        p.metadata_loaded.connect(self._on_playback_metadata)
        p.playback_finished.connect(self._on_playback_finished)
        p.playback_stopped.connect(self._on_playback_stopped)
        p.error_occurred.connect(self._on_playback_error)
        p.progress_updated.connect(self._on_playback_progress)
    
    def _get_samples_per_block(self):
        """Obtiene samples por bloque"""
        if self.main.bladerf:
            return getattr(self.main.bladerf, 'samples_per_block', 8192)
        return 8192
    
    def _get_fft_settings(self):
        """Obtiene configuración FFT actual"""
        if hasattr(self.main, 'fft_widget'):
            return self.main.fft_widget.get_settings()
        return {'fft_size': 1024}
    
    def _update_ui_with_playback_info(self):
        """Actualiza la UI con información del archivo"""
        p = self.main.player
        playback_freq = p.freq_mhz
        playback_sr = p.sample_rate
        
        self.logger.info(f"📡 Frecuencia archivo: {playback_freq:.1f} MHz")
        self.logger.info(f"📡 Sample Rate archivo: {playback_sr/1e6:.1f} MHz")
        
        # Actualizar widgets de frecuencia
        self.main.sync_frequency_widgets(playback_freq)
        
        # Actualizar rango del plot
        self.main._update_plot_range_with_sr(playback_freq, playback_sr)
    
    def _create_playback_pipeline(self, samples_per_block, fft_settings):
        """Crea el pipeline de reproducción"""
        self.logger.info("🔄 Creando pipeline de reproducción...")
        
        # Ring buffer
        self.main.playback_ring_buffer = IQRingBuffer(
            num_buffers=512,
            samples_per_buffer=samples_per_block,
            use_shared_memory=False
        )
        
        # FFT processor
        self.main.playback_fft_processor = FFTProcessorZeroCopy(
            self.main.playback_ring_buffer,
            sample_rate=self.main.player.sample_rate
        )
        
        # Configurar FFT
        self.main.playback_fft_processor.update_settings({
            'fft_size': fft_settings['fft_size'],
            'window': fft_settings.get('window', 'Hann'),
            'averaging': fft_settings.get('averaging', 1),
            'overlap': fft_settings.get('overlap', 50),
            'sample_rate': self.main.player.sample_rate
        })
        
        # Delegar la conexión al FFTController (incluye backpressure)
        self.main.fft_ctrl.connect_playback_fft_processor(       
            self.main.playback_fft_processor                       
        )   

        # Conectar señal
        #self.main.playback_fft_processor.fft_data_ready.connect(
        #    self.main.update_spectrum
        #)
    
    def _update_ui_playback_state(self, playing, filename=None):
        """Actualiza UI según estado de reproducción"""
        if playing and filename:
            file_size_mb = os.path.getsize(filename) / 1e6
            duration = self.main.player.metadata.get('duration', 0)
            self.main.statusbar.showMessage(
                f"▶ Reproduciendo: {os.path.basename(filename)} | "
                f"{file_size_mb:.1f} MB | {duration:.1f} s"
            )
        else:
            self.main.statusbar.showMessage("Reproducción detenida")
        
        # Actualizar IQ Manager
        if hasattr(self.main, 'iq_manager'):
            self.main.iq_manager.set_playback_playing(playing)
    
    def _handle_playback_error(self, error):
        """Maneja errores de reproducción"""
        self.logger.error(f"❌ Error iniciando reproducción: {error}")
        traceback.print_exc()
        
        self.stop_playback()
        
        QMessageBox.critical(
            self.main, "Error de Reproducción",
            f"No se pudo iniciar la reproducción:\n{str(error)}"
        )
    
    def stop_playback(self):
        """Detiene la reproducción"""
        try:
            if self.main.player:
                self.logger.info("⏹ Deteniendo reproducción")
                self.main.player.stop_playback()
                self.main.player.wait(2000)
                self.main.player.close()
                self.main.player = None
            
            if self.main.playback_fft_processor:
                self.main.playback_fft_processor.stop()
                self.main.playback_fft_processor = None
            
            self.main.playback_ring_buffer = None
            self.main.is_playing_back = False
            
            # Actualizar UI
            self._update_ui_playback_state(False)
            
            # Desbloquear controles
            if hasattr(self.main, 'fft_widget'):
                self.main.fft_widget.on_capture_stopped()
            if hasattr(self.main, 'rf_widget'):
                self.main.rf_widget.on_capture_stopped()
            
            # Limpiar waterfall
            if hasattr(self.main, 'waterfall'):
                self.main.waterfall.clear()
            
            # Restaurar rango por defecto
            self.main._update_plot_range(100.0)
            
        except Exception as e:
            self.logger.error(f"Error deteniendo reproducción: {e}")
    
    # -----------------------------------------------------------------------
    # SLOTS DEL PLAYER
    # -----------------------------------------------------------------------
    def _on_playback_buffer_ready(self, iq_data):
        """Slot cuando el player tiene un buffer listo"""
        try:
            if not self.main.playback_ring_buffer:
                return
            
            write_buffer = self.main.playback_ring_buffer.get_write_buffer()
            
            if write_buffer is None:
                self.logger.warning("⚠️ Ring buffer lleno en reproducción")
                return
            
            min_samples = min(len(write_buffer), len(iq_data))
            write_buffer[:min_samples] = iq_data[:min_samples]
            self.main.playback_ring_buffer.commit_write()
            
        except Exception as e:
            self.logger.error(f"Error en playback buffer ready: {e}")
    
    def _on_playback_metadata(self, metadata):
        """Muestra metadata del archivo"""
        self.logger.info(f"📋 Metadata del archivo:")
        self.logger.info(f"   Frecuencia: {metadata['frequency']} MHz")
        self.logger.info(f"   Sample Rate: {metadata['sample_rate']/1e6:.1f} MHz")
        self.logger.info(f"   Duración: {metadata['duration']:.1f} s")
    
    def _on_playback_finished(self):
        """Manejador cuando termina la reproducción"""
        self.logger.info("🏁 Reproducción finalizada automáticamente")
        
        if hasattr(self.main, 'iq_manager'):
            self.main.iq_manager.set_playback_playing(False)
            self.main.iq_manager.set_playback_state(True)
        
        self.stop_playback()
    
    def _on_playback_stopped(self):
        """Manejador cuando se detiene la reproducción"""
        self.logger.info("⏹ Reproducción detenida (señal recibida)")
        if self.main.is_playing_back:
            self.stop_playback()
    
    def _on_playback_error(self, error_msg):
        """Manejador de errores en reproducción"""
        self.logger.error(f"❌ Error en reproducción: {error_msg}")
        self.main.statusbar.showMessage(f"Error: {error_msg}")
        self.stop_playback()
    
    def _on_playback_progress(self, position, total):
        """Actualiza progreso de reproducción"""
        # Puedes conectar esto a una barra de progreso
        pass

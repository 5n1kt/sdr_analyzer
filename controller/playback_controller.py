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
            
        self._saved_rf_config = None
    # -----------------------------------------------------------------------
    # MANEJO DE REPRODUCCIÓN
    # -----------------------------------------------------------------------
    def on_playback_requested(self, filename, play):
        """Manejador para solicitudes de reproducción"""
        if play:
            self.start_playback(filename)
        else:
            self.stop_playback()
    
    '''def start_playback(self, filename):
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
            # ===== OBTENER CONFIGURACIÓN ACTUAL DEL WIDGET =====
            speed = 1.0
            loop = False
            if hasattr(self.main, 'iq_manager'):
                # Velocidad actual del spinBox
                speed = float(self.main.iq_manager.spinBox_play_speed.value())
                # Estado actual del botón de loop
                loop = self.main.iq_manager.pushButton_play_loop.isChecked()
                self.logger.info(f"⚙️ Configuración desde widget: speed={speed}x, loop={loop}")
            # ===================================================
            

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

            # Configurar player CON LOS VALORES OBTENIDOS
            self.main.player.configure(
                samples_per_buffer=samples_per_block,
                speed=speed,  # <-- Usar velocidad del widget
                loop=loop      # <-- Usar estado del loop
            )

            #speed = 1.0  # Por defecto
            if hasattr(self.main, 'iq_manager'):
                # Usar el valor del spinBox o el pendiente
                speed = float(self.main.iq_manager.spinBox_play_speed.value())
                self.logger.info(f"⏩ Velocidad solicitada: {speed}x")
            
            # Configurar player
            self.main.player.configure(
                samples_per_buffer=samples_per_block,
                speed=speed,
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

            self.main.is_playing_back = True
            self.logger.info(f"   ✅ is_playing_back = {self.main.is_playing_back}")

            self.main.player.start_playback()
            
            # Actualizar estado
            #self.main.is_playing_back = True
            self._update_ui_playback_state(True, filename)
            
            self.logger.info(f"✅ Reproducción iniciada correctamente")
            
        except Exception as e:
            self._handle_playback_error(e)'''
    
    # controller/playback_controller.py

    def start_playback(self, filename):
        """Inicia la reproducción de un archivo IQ - CON ESTRATEGIA A"""
        try:
            # ===== PASO 1: VERIFICAR Y DETENER RECEPCIÓN ACTIVA =====
            if self.main.is_running:
                self.logger.info("📻 Recepción activa detectada - Deteniendo antes de reproducir")
                
                # Guardar configuración RF actual para restaurar después
                self._saved_rf_config = {
                    'frequency': self.main.bladerf.frequency if self.main.bladerf else 100e6,
                    'sample_rate': self.main.bladerf.sample_rate if self.main.bladerf else 2e6,
                    'bandwidth': self.main.bladerf.bandwidth if self.main.bladerf else 1e6,
                    'gain': self.main.bladerf.gain if self.main.bladerf else 50,
                    'gain_mode': self.main.bladerf.gain_mode if self.main.bladerf else 'Manual'
                }
                self.logger.info(f"💾 Configuración RF guardada: {self._saved_rf_config['frequency']/1e6:.1f} MHz")
                
                # Detener recepción
                self.main.rf_ctrl.stop_rx()
                
                # Pequeña pausa para asegurar limpieza
                import time
                time.sleep(0.3)
            
            # ===== PASO 2: DETENER REPRODUCCIÓN ANTERIOR =====
            if self.main.is_playing_back:
                self.logger.info("⏹ Deteniendo reproducción anterior")
                self.stop_playback()
                time.sleep(0.3)
            
            self.logger.info(f"🎬 Iniciando reproducción: {filename}")
            
            # ===== PASO 3: VERIFICAR ARCHIVO =====
            if not self._verify_file(filename):
                return
            
            # ===== PASO 4: OBTENER CONFIGURACIÓN DEL WIDGET =====
            speed = 1.0
            loop = False
            if hasattr(self.main, 'iq_manager'):
                speed = float(self.main.iq_manager.spinBox_play_speed.value())
                loop = self.main.iq_manager.pushButton_play_loop.isChecked()
                self.logger.info(f"⚙️ Configuración desde widget: speed={speed}x, loop={loop}")
            
            # ===== PASO 5: CREAR Y CONFIGURAR PLAYER =====
            self.main.player = IQPlayer()
            self._connect_player_signals()
            
            self.logger.info("📂 Cargando archivo...")
            if not self.main.player.load_file(filename):
                raise RuntimeError("No se pudo cargar el archivo")
            
            samples_per_block = self._get_samples_per_block()
            fft_settings = self._get_fft_settings()
            
            self.main.player.configure(
                samples_per_buffer=samples_per_block,
                speed=speed,
                loop=loop
            )
            
            # ===== PASO 6: ACTUALIZAR UI CON INFO DEL ARCHIVO =====
            self._update_ui_with_playback_info()
            
            # ===== PASO 7: CREAR PIPELINE DE REPRODUCCIÓN =====
            self._create_playback_pipeline(samples_per_block, fft_settings)
            
            # ===== PASO 8: INICIAR REPRODUCCIÓN =====
            self.logger.info("🚀 Iniciando FFTProcessor...")
            self.main.playback_fft_processor.start()
            
            self.logger.info("▶ Iniciando reproducción...")
            self.main.is_playing_back = True
            self.main.player.start_playback()
            
            # ===== PASO 9: ACTUALIZAR UI =====
            self._update_ui_playback_state(True, filename)
            
            # Mensaje claro en barra de estado
            self.main.statusbar.showMessage(
                f"🎬 MODO REPRODUCCIÓN: {os.path.basename(filename)} | "
                f"Velocidad: {speed}x | Loop: {'ON' if loop else 'OFF'}", 
                5000
            )
            
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
    
    def pause_playback(self):
        """Pausa la reproducción actual."""
        if self.main.player and self.main.is_playing_back:
            self.logger.info("⏸ Pausando reproducción")
            self.main.player.pause_playback()
            # La UI se actualizará a través de la señal playback_paused

    def resume_playback(self):
        """Reanuda la reproducción pausada."""
        if self.main.player and self.main.is_playing_back:
            self.logger.info("▶ Reanudando reproducción")
            self.main.player.resume_playback()
            # La UI se actualizará a través de la señal playback_started

    def set_loop_mode(self, enabled: bool):
        """Activa o desactiva el modo loop."""
        if self.main.player:
            self.main.player.loop = enabled
            self.logger.info(f"🔄 Modo loop: {'activado' if enabled else 'desactivado'}")
    
    def _connect_player_signals(self):
        """Conecta las señales del player"""
        p = self.main.player
        p.buffer_ready.connect(self._on_playback_buffer_ready)
        p.metadata_loaded.connect(self._on_playback_metadata)
        p.playback_finished.connect(self._on_playback_finished)
        p.playback_stopped.connect(self._on_playback_stopped)
        p.error_occurred.connect(self._on_playback_error)
        p.progress_updated.connect(self._on_playback_progress)
        p.playback_started.connect(self._on_playback_started)
        p.playback_paused.connect(self._on_playback_paused)
    
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
    
    '''def _update_ui_playback_state(self, playing, filename=None):
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
            self.main.iq_manager.set_playback_playing(playing)'''
    
    # controller/playback_controller.py

    def _update_ui_playback_state(self, playing, filename=None):
        """Actualiza UI según estado de reproducción."""
        if playing and filename:
            file_size_mb = os.path.getsize(filename) / 1e6
            duration = self.main.player.metadata.get('duration', 0)
            self.main.statusbar.showMessage(
                f"▶ Reproduciendo: {os.path.basename(filename)} | "
                f"{file_size_mb:.1f} MB | {duration:.1f} s"
            )
            
            # Actualizar indicador de modo
            if hasattr(self.main, 'iq_manager'):
                self.main.iq_manager.update_mode_indicator("play")
        else:
            self.main.statusbar.showMessage("Reproducción detenida")
            
            # Volver a indicador LIVE si no hay recepción activa
            if hasattr(self.main, 'iq_manager'):
                if self.main.is_running:
                    self.main.iq_manager.update_mode_indicator("live")
                else:
                    self.main.iq_manager.update_mode_indicator("live")  # O "IDLE" si prefieres
    
    def _handle_playback_error(self, error):
        """Maneja errores de reproducción"""
        self.logger.error(f"❌ Error iniciando reproducción: {error}")
        traceback.print_exc()
        
        self.stop_playback()
        
        QMessageBox.critical(
            self.main, "Error de Reproducción",
            f"No se pudo iniciar la reproducción:\n{str(error)}"
        )
    
   
    
    # controller/playback_controller.py

    '''def stop_playback(self):
        """Detiene la reproducción (VERSIÓN MEJORADA CON LOGS)."""
        self.logger.info("=" * 50)
        self.logger.info("🛑 PlaybackController.stop_playback() LLAMADO")
        
        try:
            # Detener player
            if self.main.player:
                self.logger.info("   ⏹ Deteniendo player...")
                self.main.player.stop_playback()
                self.logger.info("   ⏳ Esperando a que el hilo del player termine...")
                if not self.main.player.wait(2000):
                    self.logger.warning("      ⚠️ Timeout esperando al player")
                self.main.player.close()
                self.main.player = None
                self.logger.info("   ✅ Player detenido y eliminado")
            else:
                self.logger.info("   ⚠️ No había player activo")
            
            # Detener FFT processor
            if self.main.playback_fft_processor:
                self.logger.info("   ⏹ Deteniendo FFT processor de reproducción...")
                self.main.playback_fft_processor.stop()
                self.main.playback_fft_processor = None
                self.logger.info("   ✅ FFT processor detenido")
            
            # Liberar buffer
            self.main.playback_ring_buffer = None
            self.logger.info("   ✅ Buffer liberado")
            
            # Actualizar estado
            self.main.is_playing_back = False
            self.logger.info(f"   ✅ is_playing_back = {self.main.is_playing_back}")
            
            # --- ACTUALIZAR UI ---
            self.logger.info("   🖥️ Actualizando UI...")
            self._update_ui_playback_state(False)
            
            if hasattr(self.main, 'iq_manager'):
                self.main.iq_manager.set_playback_playing(False)
                self.main.iq_manager.set_playback_state(True)
                self.main.iq_manager.pushButton_play_pause.setText("⏸ PAUSE")
                self.logger.info("   ✅ UI del IQ Manager actualizada")
            
            # Limpiar waterfall
            if hasattr(self.main, 'waterfall'):
                self.main.waterfall.clear()
                self.logger.info("   💧 Waterfall limpiado")
            
            # Restaurar rango por defecto
            self.main._update_plot_range(100.0)
            
            self.logger.info("✅ Reproducción detenida correctamente")
            self.logger.info("=" * 50)
            
        except Exception as e:
            self.logger.error(f"❌ Error deteniendo reproducción: {e}")
            import traceback
            traceback.print_exc()
            self.logger.info("=" * 50)'''
    
    # controller/playback_controller.py

    def stop_playback(self, restore_rx=True):
        """Detiene la reproducción y opcionalmente restaura configuración RF."""
        self.logger.info("=" * 50)
        self.logger.info("🛑 PlaybackController.stop_playback() LLAMADO")
        
        try:
            # Detener player
            if self.main.player:
                self.logger.info("   ⏹ Deteniendo player...")
                self.main.player.stop_playback()
                if not self.main.player.wait(2000):
                    self.logger.warning("      ⚠️ Timeout esperando al player")
                self.main.player.close()
                self.main.player = None
                self.logger.info("   ✅ Player detenido")
            
            # Detener FFT processor
            if self.main.playback_fft_processor:
                self.logger.info("   ⏹ Deteniendo FFT processor...")
                self.main.playback_fft_processor.stop()
                self.main.playback_fft_processor = None
                self.logger.info("   ✅ FFT processor detenido")
            
            # Liberar buffer
            self.main.playback_ring_buffer = None
            self.logger.info("   ✅ Buffer liberado")
            
            # Actualizar estado
            self.main.is_playing_back = False
            
            # ===== RESTAURAR CONFIGURACIÓN RF SI SE SOLICITA =====
            if restore_rx and hasattr(self, '_saved_rf_config') and self._saved_rf_config:
                self.logger.info("   🔄 Restaurando configuración RF...")
                self.restore_rx_config()
            # ====================================================
            
            # Actualizar UI
            self._update_ui_playback_state(False)
            
            if hasattr(self.main, 'iq_manager'):
                self.main.iq_manager.set_playback_playing(False)
                self.main.iq_manager.set_playback_state(True)
                self.main.iq_manager.pushButton_play_pause.setText("⏸ PAUSE")
            
            # Limpiar waterfall
            if hasattr(self.main, 'waterfall'):
                self.main.waterfall.clear()
            
            # Mensaje en barra de estado
            self.main.statusbar.showMessage("⏹ Reproducción detenida", 3000)
            
            self.logger.info("✅ Reproducción detenida correctamente")
            
        except Exception as e:
            self.logger.error(f"❌ Error deteniendo reproducción: {e}")
            import traceback
            traceback.print_exc()
        
        self.logger.info("=" * 50)
    
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
        
        #self.stop_playback()
        # Detener reproducción Y restaurar configuración RF
        self.stop_playback(restore_rx=True)
    
    

    def _on_playback_stopped(self):
        """Manejador cuando se detiene la reproducción (señal del player)."""
        self.logger.info("🔊 Señal playback_stopped recibida del player")
        
        # Solo actuar si no estamos ya en medio de una parada
        if self.main.is_playing_back:
            self.logger.info("   → is_playing_back=True, llamando a stop_playback()")
            self.stop_playback()
        else:
            self.logger.info("   → is_playing_back=False, ignorando (ya detenido)")
    
    def _on_playback_error(self, error_msg):
        """Manejador de errores en reproducción"""
        self.logger.error(f"❌ Error en reproducción: {error_msg}")
        self.main.statusbar.showMessage(f"Error: {error_msg}")
        self.stop_playback()
    
    def _on_playback_progress(self, position, total):
        """Actualiza progreso de reproducción en el slider."""
        # position y total vienen del player
        if total > 0 and hasattr(self.main, 'iq_manager'):
            ratio = position / total
            # Actualizar slider en el hilo principal de Qt
            self.main.iq_manager.horizontalSlider_play.setValue(int(ratio * 1000))

    def _on_playback_started(self):
        """Señal del player: reproducción iniciada/reanudada."""
        self.logger.info("🔊 Señal playback_started recibida")
        if hasattr(self.main, 'iq_manager'):
            self.main.iq_manager.set_playback_playing(True)
            # Asegurar que el texto del botón de pausa sea el correcto
            self.main.iq_manager.pushButton_play_pause.setText("⏸ PAUSE")

    def _on_playback_paused(self):
        """Señal del player: reproducción pausada."""
        self.logger.info("🔊 Señal playback_paused recibida")
        if hasattr(self.main, 'iq_manager'):
            # No detenemos el slider, solo cambiamos el estado de la UI
            self.main.iq_manager.label_play_status_icon.setText("⏸")
            self.main.iq_manager.label_play_status_text.setText("PAUSADO")
            self.main.iq_manager.pushButton_play_pause.setText("▶ RESUME")
            # El botón de play debe seguir deshabilitado y el de stop habilitado
            self.main.iq_manager.pushButton_play_play.setEnabled(False)
            self.main.iq_manager.pushButton_play_stop.setEnabled(True)



    def restore_rx_config(self):
        """Restaura la configuración RF guardada al volver a modo recepción."""
        if not hasattr(self, '_saved_rf_config') or not self._saved_rf_config:
            self.logger.info("ℹ️ No hay configuración RF guardada, usando valores por defecto")
            return
        
        self.logger.info("🔄 Restaurando configuración RF guardada...")
        
        # Aplicar configuración guardada
        if hasattr(self.main, 'rf_ctrl'):
            self.main.rf_ctrl.update_rf_settings(self._saved_rf_config)
            self.logger.info(f"✅ Configuración RF restaurada: {self._saved_rf_config['frequency']/1e6:.1f} MHz")
            
            # Limpiar configuración guardada
            self._saved_rf_config = None
        else:
            self.logger.error("❌ No se puede restaurar: rf_ctrl no disponible")
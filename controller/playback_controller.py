# controller/playback_controller.py - VERSIÓN CORREGIDA

import os
import time
import logging
import traceback
from PyQt5.QtWidgets import QMessageBox, QApplication
from PyQt5.QtCore import QThread, pyqtSignal

from workers.iq_player import IQPlayer
from workers.shared_buffer import IQRingBuffer
from workers.fft_processor_zerocopy import FFTProcessorZeroCopy


# =======================================================================
# HILO AUXILIAR — CARGA ASÍNCRONA DE ARCHIVO IQ (CORREGIDO)
# =======================================================================
class FileLoaderThread(QThread):
    """
    Carga el archivo IQ en un hilo separado para no bloquear la GUI.
    """
    load_finished = pyqtSignal(bool, object)  # (success, player_instance)

    def __init__(self, filename):
        super().__init__()
        self.filename = filename
        self.player = None  # Se crea dentro del hilo
        self.success = False

    def run(self):
        """Carga el archivo en el hilo secundario"""
        try:
            # Crear player dentro del hilo
            self.player = IQPlayer()
            self.success = self.player.load_file(self.filename)
            self.load_finished.emit(self.success, self.player)
        except Exception as e:
            logging.getLogger(__name__).error(f"Error en FileLoaderThread: {e}")
            self.load_finished.emit(False, None)


# =======================================================================
# CONTROLADOR DE REPRODUCCIÓN (CORREGIDO)
# =======================================================================
class PlaybackController:
    """Gestiona la reproducción de archivos IQ"""
    
    def __init__(self, main_controller):
        self.main = main_controller
        self.logger = logging.getLogger(f"{__name__}.PlaybackController")
        
        self._saved_rf_config = None
        self._is_loading = False
        self._metadata_callback = None
        
        self._pending_speed = 1.0
        self._pending_loop = False
        self._pending_filename = None
        self._pending_fft_size = 1024
        self._pending_samples_per_block = 8192

     # ===== MÉTODO FALTANTE =====
    def on_playback_requested(self, filename, play):
        """
        Manejador para solicitudes de reproducción.
        Llamado desde IQManagerWidget cuando se presiona play/stop.
        
        Args:
            filename (str): Ruta del archivo a reproducir
            play (bool): True para iniciar, False para detener
        """
        if play:
            self.logger.info(f"▶ Solicitud de reproducción: {filename}")
            self.start_playback(filename)
        else:
            self.logger.info("⏹ Solicitud de detención de reproducción")
            self.stop_playback()

    
    # controller/playback_controller.py

    def start_playback(self, filename):
        """Inicia la reproducción de un archivo IQ — carga asíncrona sin bloqueo."""
        # Evitar cargas múltiples
        if self._is_loading:
            self.logger.warning("⚠️ Ya hay una carga en progreso, ignorando...")
            return
        
        try:
            self.logger.info("=" * 60)
            self.logger.info(f"🎬 PlaybackController.start_playback: {filename}")
            
            # ===== LIMPIAR METADATA ANTERIOR INMEDIATAMENTE =====
            if hasattr(self.main, 'iq_manager') and self.main.iq_manager:
                self.logger.info("🗑️ Limpiando metadata anterior en UI...")
                self.main.iq_manager.clear_metadata_display()
                # Forzar actualización de la UI
                QApplication.processEvents()
                self.logger.info("✅ Metadata anterior limpiada")
            else:
                self.logger.warning("⚠️ iq_manager no disponible para limpiar metadata")
            
            # ===== PASO 1: VERIFICAR Y DETENER RECEPCIÓN ACTIVA =====
            if self.main.is_running:
                self.logger.info("📻 Recepción activa detectada - Deteniendo antes de reproducir")
                self._saved_rf_config = {
                    'frequency':  self.main.bladerf.frequency  if self.main.bladerf else 100e6,
                    'sample_rate': self.main.bladerf.sample_rate if self.main.bladerf else 2e6,
                    'bandwidth':  self.main.bladerf.bandwidth   if self.main.bladerf else 1e6,
                    'gain':       self.main.bladerf.gain        if self.main.bladerf else 50,
                    'gain_mode':  self.main.bladerf.gain_mode   if self.main.bladerf else 'Manual'
                }
                self.logger.info(f"💾 Configuración RF guardada: {self._saved_rf_config['frequency']/1e6:.1f} MHz")
                self.main.rf_ctrl.stop_rx()
                QApplication.processEvents()
                time.sleep(0.1)

            # ===== PASO 2: DETENER REPRODUCCIÓN ANTERIOR =====
            if self.main.is_playing_back:
                self.logger.info("⏹ Deteniendo reproducción anterior")
                self.stop_playback()
                QApplication.processEvents()
                time.sleep(0.1)

            # ===== PASO 3: VERIFICAR ARCHIVO =====
            if not os.path.exists(filename):
                self.logger.error(f"❌ Archivo no encontrado: {filename}")
                QMessageBox.critical(self.main, "Error", f"No se encontró el archivo:\n{filename}")
                # Restaurar estado en UI
                if hasattr(self.main, 'iq_manager') and self.main.iq_manager:
                    self.main.iq_manager.label_play_metadata.setText("Archivo no encontrado")
                return

            self.logger.info(f"🎬 Iniciando reproducción: {filename}")

            # ===== PASO 4: OBTENER CONFIGURACIÓN =====
            speed = 1.0
            loop = False
            if hasattr(self.main, 'iq_manager'):
                speed = float(self.main.iq_manager.spinBox_play_speed.value())
                loop = self.main.iq_manager.pushButton_play_loop.isChecked()
                self.logger.info(f"⚙️ Configuración: speed={speed}x, loop={loop}")

            # ===== PASO 5: GUARDAR CONFIGURACIÓN PARA DESPUÉS =====
            self._pending_speed = speed
            self._pending_loop = loop
            self._pending_filename = filename
            self._pending_fft_size = self._get_fft_size()
            self._pending_samples_per_block = self._get_samples_per_block()

            # ===== PASO 6: INICIAR CARGA ASÍNCRONA =====
            self._is_loading = True
            self.main.statusbar.showMessage("📂 Cargando archivo IQ... por favor espera")
            QApplication.processEvents()

            # Crear hilo de carga
            self._file_loader = FileLoaderThread(filename)
            self._file_loader.load_finished.connect(self._on_file_loaded)
            self._file_loader.start()
            
            self.logger.info("=" * 60)

        except Exception as e:
            self._is_loading = False
            self._handle_playback_error(e)


    '''def _on_file_loaded(self, success, player):
        """Continúa la reproducción después de que el archivo terminó de cargar."""
        self._is_loading = False
        
        try:
            if not success or player is None:
                raise RuntimeError("No se pudo cargar el archivo")
            
            self.logger.info("=" * 60)
            self.logger.info("📂 Archivo cargado exitosamente")
            
            # ===== ASIGNAR EL PLAYER CARGADO =====
            self.main.player = player
            
            # ===== CONECTAR SEÑALES ANTES DE CUALQUIER OPERACIÓN =====
            self._connect_player_signals()
            
            # ===== LA METADATA YA DEBERÍA HABER SIDO EMITIDA =====
            # Pero si no, forzamos actualización
            if hasattr(self.main.player, 'metadata') and self.main.player.metadata:
                self.logger.info("📡 Actualizando UI con metadata del archivo")
                # Llamar directamente al método del widget
                if hasattr(self.main, 'iq_manager') and self.main.iq_manager:
                    self.main.iq_manager.update_metadata_display(self.main.player.metadata)
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
            else:
                self.logger.warning("⚠️ No hay metadata disponible en el player")
            
            # Configurar el player (NO iniciar reproducción todavía)
            self.main.player.configure(
                samples_per_buffer=self._pending_samples_per_block,
                speed=self._pending_speed,
                loop=self._pending_loop
            )

            # ===== ACTUALIZAR RANGO DEL PLOT =====
            self._update_ui_with_playback_info()

            # ===== CREAR PIPELINE DE REPRODUCCIÓN =====
            self._create_playback_pipeline(self._pending_samples_per_block, self._pending_fft_size)

            # NOTA: NO iniciamos reproducción automáticamente
            # El usuario debe presionar PLAY para iniciar
            
            # ===== ACTUALIZAR UI =====
            self._update_ui_playback_state(False, self._pending_filename)  # Estado = cargado pero no reproduciendo
            
            self.logger.info("✅ Archivo cargado y listo para reproducir")
            self.logger.info("=" * 60)

        except Exception as e:
            self._handle_playback_error(e)'''
    
    def _on_file_loaded(self, success, player):
        """Continúa la reproducción después de que el archivo terminó de cargar."""
        self._is_loading = False
        
        try:
            if not success or player is None:
                raise RuntimeError("No se pudo cargar el archivo")
            
            self.logger.info("=" * 60)
            self.logger.info("📂 Archivo cargado exitosamente")
            
            # ===== ASIGNAR EL PLAYER CARGADO =====
            self.main.player = player
            
            # ===== CONECTAR SEÑALES =====
            self._connect_player_signals()
            
            # ===== LA METADATA YA DEBERÍA HABER SIDO EMITIDA =====
            # Pero si no, forzamos actualización
            if hasattr(self.main.player, 'metadata') and self.main.player.metadata:
                self.logger.info("📡 Actualizando UI con metadata del archivo")
                self._on_playback_metadata(self.main.player.metadata)
            else:
                self.logger.warning("⚠️ No hay metadata disponible en el player")
            
            # Configurar el player
            self.main.player.configure(
                samples_per_buffer=self._pending_samples_per_block,
                speed=self._pending_speed,
                loop=self._pending_loop
            )

            # ===== ACTUALIZAR RANGO DEL PLOT =====
            self._update_ui_with_playback_info()

            # ===== CREAR PIPELINE DE REPRODUCCIÓN =====
            self._create_playback_pipeline(self._pending_samples_per_block, self._pending_fft_size)

            # ===== INICIAR REPRODUCCIÓN =====
            self.logger.info("🚀 Iniciando FFTProcessor...")
            self.main.playback_fft_processor.start()

            self.logger.info("▶ Iniciando reproducción...")
            self.main.is_playing_back = True
            self.main.player.start_playback()

            # ===== ACTUALIZAR UI =====
            self._update_ui_playback_state(True, self._pending_filename)
            
            self.logger.info("✅ Reproducción iniciada correctamente")
            self.logger.info("=" * 60)

        except Exception as e:
            self._handle_playback_error(e)

    '''def _on_playback_metadata(self, metadata):
        """Manejador cuando se carga metadata del archivo."""
        self.logger.info("=" * 60)
        self.logger.info("📋 _on_playback_metadata EJECUTADO EN PLAYBACKCONTROLLER")
        self.logger.info(f"   Metadata: {metadata}")
        self.logger.info("=" * 60)
        
        # Actualizar UI inmediatamente con repaint forzado
        if hasattr(self.main, 'iq_manager') and self.main.iq_manager:
            self.logger.info("   Actualizando IQManagerWidget...")
            # Llamar directamente y forzar procesamiento de eventos
            self.main.iq_manager.update_metadata_display(metadata)
            from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()  # Forzar actualización inmediata
        else:
            self.logger.error("❌ iq_manager no disponible")'''
    
    def _on_playback_metadata(self, metadata):
        """Manejador cuando se carga metadata del archivo."""
        self.logger.info("=" * 60)
        self.logger.info("📋 _on_playback_metadata EJECUTADO EN PLAYBACKCONTROLLER")
        self.logger.info(f"   Metadata: {metadata}")
        self.logger.info("=" * 60)
        
        # Actualizar UI inmediatamente
        if hasattr(self.main, 'iq_manager') and self.main.iq_manager:
            self.logger.info("   Actualizando IQManagerWidget...")
            self.main.iq_manager.update_metadata_display(metadata)
        else:
            self.logger.error("❌ iq_manager no disponible")

    
    def _get_fft_size(self):
        """Obtiene tamaño FFT actual"""
        if hasattr(self.main, 'fft_widget'):
            return self.main.fft_widget.get_settings().get('fft_size', 1024)
        return 1024

    def _get_samples_per_block(self):
        """Obtiene samples por bloque"""
        if self.main.bladerf:
            return getattr(self.main.bladerf, 'samples_per_block', 8192)
        return 8192

    def _connect_player_signals(self):
        """Conecta las señales del player."""
        if self.main.player is None:
            self.logger.warning("⚠️ No se pueden conectar señales: player es None")
            return
        
        p = self.main.player
        
        self.logger.info("🔌 Conectando señales del player...")
        self.logger.info(f"   Player tiene metadata_loaded: {hasattr(p, 'metadata_loaded')}")
        
        # Conectar señal de metadata
        try:
            p.metadata_loaded.connect(self._on_playback_metadata)
            self.logger.info("✅ metadata_loaded conectado a _on_playback_metadata")
        except Exception as e:
            self.logger.error(f"❌ Error conectando metadata_loaded: {e}")
        
        # Conectar otras señales
        p.buffer_ready.connect(self._on_playback_buffer_ready)
        p.playback_finished.connect(self._on_playback_finished)
        p.playback_stopped.connect(self._on_playback_stopped)
        p.error_occurred.connect(self._on_playback_error)
        p.progress_updated.connect(self._on_playback_progress)
        p.playback_started.connect(self._on_playback_started)
        p.playback_paused.connect(self._on_playback_paused)
        
        self.logger.info("✅ Todas las señales del player conectadas correctamente")

    def _update_ui_with_playback_info(self):
        """Actualiza la UI con información del archivo"""
        if self.main.player is None:
            self.logger.warning("⚠️ No se puede actualizar UI: player es None")
            return
        
        p = self.main.player
        playback_freq = p.freq_mhz
        playback_sr = p.sample_rate
        
        self.logger.info(f"📡 Frecuencia archivo: {playback_freq:.1f} MHz")
        self.logger.info(f"📡 Sample Rate archivo: {playback_sr/1e6:.1f} MHz")
        
        # Actualizar widgets de frecuencia
        self.main.sync_frequency_widgets(playback_freq)
        
        # Actualizar rango del plot
        self.main._update_plot_range_with_sr(playback_freq, playback_sr)

    def _create_playback_pipeline(self, samples_per_block, fft_size):
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
            'fft_size': fft_size,
            'window': 'Hann',
            'averaging': 1,
            'overlap': 50,
            'sample_rate': self.main.player.sample_rate
        })
        
        # Conectar FFT processor
        self.main.fft_ctrl.connect_playback_fft_processor(self.main.playback_fft_processor)

    def _update_ui_playback_state(self, playing, filename=None):
        """Actualiza UI según estado de reproducción."""
        if playing and filename and self.main.player is not None:
            try:
                file_size_mb = os.path.getsize(filename) / 1e6
                duration = 0
                if hasattr(self.main.player, 'metadata') and self.main.player.metadata:
                    duration = self.main.player.metadata.get('duration', 0)
                
                self.main.statusbar.showMessage(
                    f"▶ Reproduciendo: {os.path.basename(filename)} | "
                    f"{file_size_mb:.1f} MB | {duration:.1f} s"
                )
                
                if hasattr(self.main, 'iq_manager'):
                    self.main.iq_manager.update_mode_indicator("play")
            except Exception as e:
                self.logger.warning(f"Error actualizando UI: {e}")
        else:
            self.main.statusbar.showMessage("Reproducción detenida")
            if hasattr(self.main, 'iq_manager'):
                self.main.iq_manager.update_mode_indicator("live")

    def _handle_playback_error(self, error):
        """Maneja errores de reproducción"""
        self.logger.error(f"❌ Error en reproducción: {error}")
        traceback.print_exc()
        
        self.stop_playback()
        
        QMessageBox.critical(
            self.main, "Error de Reproducción",
            f"No se pudo iniciar la reproducción:\n{str(error)}"
        )

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
            
            # Restaurar configuración RF si se solicita
            if restore_rx and hasattr(self, '_saved_rf_config') and self._saved_rf_config:
                self.logger.info("   🔄 Restaurando configuración RF...")
                self.restore_rx_config()
            
            # Actualizar UI
            self._update_ui_playback_state(False)
            
            if hasattr(self.main, 'iq_manager'):
                self.main.iq_manager.set_playback_playing(False)
                self.main.iq_manager.set_playback_state(True)
                self.main.iq_manager.pushButton_play_pause.setText("⏸ PAUSE")
            
            # Limpiar waterfall
            if hasattr(self.main, 'waterfall'):
                self.main.waterfall.clear()
            
            self.main.statusbar.showMessage("⏹ Reproducción detenida", 3000)
            self.logger.info("✅ Reproducción detenida correctamente")
            
        except Exception as e:
            self.logger.error(f"❌ Error deteniendo reproducción: {e}")
            traceback.print_exc()
        
        self.logger.info("=" * 50)

    def restore_rx_config(self):
        """Restaura la configuración RF guardada al volver a modo recepción."""
        if not hasattr(self, '_saved_rf_config') or not self._saved_rf_config:
            self.logger.info("ℹ️ No hay configuración RF guardada")
            return
        
        self.logger.info("🔄 Restaurando configuración RF guardada...")
        
        if hasattr(self.main, 'rf_ctrl'):
            self.main.rf_ctrl.update_rf_settings(self._saved_rf_config)
            self.logger.info(f"✅ Configuración RF restaurada: {self._saved_rf_config['frequency']/1e6:.1f} MHz")
            self._saved_rf_config = None

    # ===== SLOTS DEL PLAYER =====
    
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


    
    def set_metadata_callback(self, callback):
        """Registra un callback para recibir metadata."""
        self._metadata_callback = callback
        self.logger.info("✅ Callback de metadata registrado")



    def _on_playback_finished(self):
        """Manejador cuando el player termina el archivo naturalmente."""
        self.logger.info("🏁 Reproducción finalizada automáticamente")
        
        if hasattr(self.main, 'iq_manager'):
            mgr = self.main.iq_manager
            mgr.set_playback_playing(False)
            mgr.set_playback_state(True)
            mgr.label_play_status_text.setText("FINALIZADO")
        
        self.main.is_playing_back = False
        self.stop_playback(restore_rx=True)

    def _on_playback_stopped(self):
        """Manejador de la señal playback_stopped del player."""
        self.logger.info("🔊 Señal playback_stopped recibida del player")
        
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



    def _on_playback_progress(self, position_bytes, total_bytes):
        """
        Slot de progress_updated del player.
        Actualiza el slider de progreso y las etiquetas de tiempo.
        """
        if total_bytes <= 0:
            return
        
        if not hasattr(self.main, 'iq_manager') or self.main.iq_manager is None:
            return
        
        mgr = self.main.iq_manager
        
        # Calcular ratio (0.0 a 1.0)
        ratio = position_bytes / total_bytes
        # Convertir a rango 0-1000 para el slider
        slider_value = int(ratio * 1000)
        
        # Actualizar slider sin emitir señales para evitar loops
        mgr.horizontalSlider_play.blockSignals(True)
        mgr.horizontalSlider_play.setValue(slider_value)
        mgr.horizontalSlider_play.blockSignals(False)
        
        # ===== ACTUALIZAR ETIQUETAS DE TIEMPO DIRECTAMENTE =====
        try:
            if self.main.player is None:
                return
            
            sr = self.main.player.sample_rate
            if sr <= 0:
                sr = 2e6
            
            speed = getattr(self.main.player, 'speed', 1.0)
            
            # Calcular tiempos (4 bytes por muestra compleja)
            total_seconds = total_bytes / (sr * 4)
            current_seconds = position_bytes / (sr * 4)
            
            # Tiempo efectivo considerando velocidad
            current_effective = current_seconds / speed if speed > 0 else current_seconds
            total_effective = total_seconds / speed if speed > 0 else total_seconds
            
            # Actualizar label de estado
            mgr.label_play_status_text.setText(
                f"REPRODUCIENDO  {current_effective:.1f}s / {total_effective:.1f}s ({speed:.0f}x)"
            )
            
            # Actualizar duración total
            if hasattr(mgr, 'label_play_duration'):
                mgr.label_play_duration.setText(f"{total_effective:.1f} s")
                
        except Exception as e:
            self.logger.debug(f"Error actualizando etiquetas de tiempo: {e}")

    
        

    def _update_time_labels(self, position_bytes, total_bytes, mgr):
        """
        Actualiza las etiquetas de tiempo con cálculo correcto.
        """
        try:
            if self.main.player is None:
                return
            
            sr = self.main.player.sample_rate
            if sr <= 0:
                sr = 2e6
            
            speed = getattr(self.main.player, 'speed', 1.0)
            
            # CORRECCIÓN: 4 bytes por muestra compleja
            total_seconds = total_bytes / (sr * 4)
            current_seconds = position_bytes / (sr * 4)
            
            # Log para verificar valores
            if not hasattr(self, '_last_debug_log'):
                self._last_debug_log = 0
            import time
            now = time.time()
            if now - self._last_debug_log > 3:
                self.logger.debug(
                    f"⏱️ Tiempos: total_bytes={total_bytes}, sr={sr/1e6:.1f}MHz, "
                    f"total_sec={total_seconds:.1f}, current_sec={current_seconds:.1f}"
                )
                self._last_debug_log = now
            
            # Tiempo efectivo considerando velocidad
            current_effective = current_seconds / speed if speed > 0 else current_seconds
            total_effective = total_seconds / speed if speed > 0 else total_seconds
            
            # Actualizar label de estado
            mgr.label_play_status_text.setText(
                f"REPRODUCIENDO  {current_effective:.1f}s / {total_effective:.1f}s ({speed:.0f}x)"
            )
            
            # Actualizar duración total
            if hasattr(mgr, 'label_play_duration'):
                mgr.label_play_duration.setText(f"{total_effective:.1f} s")
                
        except Exception as e:
            self.logger.debug(f"Error actualizando etiquetas: {e}")


    
    def _on_playback_started(self):
        """Señal del player: reproducción iniciada/reanudada."""
        self.logger.info("🔊 Señal playback_started recibida")
        if hasattr(self.main, 'iq_manager'):
            mgr = self.main.iq_manager
            mgr.set_playback_playing(True)
            mgr.pushButton_play_pause.setText("⏸ PAUSE")
            mgr.label_play_status_text.setText("REPRODUCIENDO")
            # Iniciar timer de actualización de slider (respaldo)
            #mgr.playback_progress_timer.start()

    def _on_playback_paused(self):
        """Señal del player: reproducción pausada."""
        self.logger.info("🔊 Señal playback_paused recibida")
        if hasattr(self.main, 'iq_manager'):
            self.main.iq_manager.label_play_status_icon.setText("⏸")
            self.main.iq_manager.label_play_status_text.setText("PAUSADO")
            self.main.iq_manager.pushButton_play_pause.setText("▶ RESUME")
            self.main.iq_manager.pushButton_play_play.setEnabled(False)
            self.main.iq_manager.pushButton_play_stop.setEnabled(True)

    def pause_playback(self):
        """Pausa la reproducción actual."""
        if self.main.player and self.main.is_playing_back:
            self.logger.info("⏸ Pausando reproducción")
            self.main.player.pause_playback()

    def resume_playback(self):
        """Reanuda la reproducción pausada."""
        if self.main.player and self.main.is_playing_back:
            self.logger.info("▶ Reanudando reproducción")
            self.main.player.resume_playback()

    def set_loop_mode(self, enabled: bool):
        """Activa o desactiva el modo loop."""
        if self.main.player:
            self.main.player.loop = enabled
            self.logger.info(f"🔄 Modo loop: {'activado' if enabled else 'desactivado'}")




    def seek(self, position_bytes):
        """
        Salta a una posición específica en el archivo.
        
        Args:
            position_bytes: Posición en bytes (debe estar alineada a buffer)
        """
        if self.main.player is None:
            self.logger.warning("⚠️ No se puede hacer seek: player no disponible")
            return
        
        if not self.main.is_playing_back:
            # Si no está reproduciendo, igual podemos hacer seek para preparar
            self.logger.info("🎚️ Seek en modo pausa")
            self.main.player.seek(position_bytes)
            # Actualizar UI
            if hasattr(self.main, 'iq_manager'):
                ratio = position_bytes / self.main.player.total_bytes if self.main.player.total_bytes > 0 else 0
                self.main.iq_manager.horizontalSlider_play.setValue(int(ratio * 1000))
        else:
            # Si está reproduciendo, delegar al player (que manejará la pausa temporal)
            self.logger.info(f"🎚️ Seek durante reproducción a {position_bytes} bytes")
            self.main.player.seek(position_bytes)
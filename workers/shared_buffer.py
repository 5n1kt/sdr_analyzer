# workers/shared_buffer.py
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import numpy as np
import threading
import logging
from multiprocessing import shared_memory, Lock


# =======================================================================
# RING BUFFER CIRCULAR THREAD-SAFE
# =======================================================================
class IQRingBuffer:
    """
    Buffer circular thread-safe para muestras IQ.
    Versión con soporte para memoria compartida (multiprocessing).
    """
    
    # -----------------------------------------------------------------------
    # CONSTANTES DE ESTADO
    # -----------------------------------------------------------------------
    BUFFER_FREE = 0
    BUFFER_FILLING = 1
    BUFFER_READY = 2
    BUFFER_READING = 3
    
    # -----------------------------------------------------------------------
    # MÉTODOS MÁGICOS
    # -----------------------------------------------------------------------
    def __init__(self, num_buffers: int = 4, samples_per_buffer: int = 16384,
                 use_shared_memory: bool = False, shm_name: str = None):
        """
        Inicializa el ring buffer.
        
        Args:
            num_buffers: Número de buffers en el ring
            samples_per_buffer: Muestras por buffer (complejas)
            use_shared_memory: Si True, usa memoria compartida para multiprocessing
            shm_name: Nombre de la memoria compartida existente
        """
        self.logger = logging.getLogger(__name__)
        
        self.num_buffers = num_buffers
        self.samples_per_buffer = samples_per_buffer
        self.bytes_per_buffer = samples_per_buffer * 8  # complex64 = 8 bytes
        self.use_shared_memory = use_shared_memory
        self.shm_name = shm_name
        self.shm = None
        
        # Inicializar según modo
        if use_shared_memory:
            self._init_shared_memory()
        else:
            self._init_thread_memory()
        
        # Punteros y estados (comunes a ambos modos)
        self.buffer_states = [self.BUFFER_FREE] * num_buffers
        self.write_index = 0
        self.read_index = 0
        self.available_count = 0
        
        # Eventos para espera eficiente (solo en modo threads)
        if not use_shared_memory:
            self.data_available = threading.Event()
            self.buffer_freed = threading.Event()
        
        # Estadísticas
        self.total_buffers_written = 0
        self.total_buffers_read = 0
        self.overflow_count = 0
        
        self.logger.info(
            f"✅ RingBuffer creado: {num_buffers}x{samples_per_buffer} muestras"
        )
        if use_shared_memory:
            self.logger.info(f"   Modo: MEMORIA COMPARTIDA")
    
    def __del__(self):
        """Destructor - asegura liberar memoria"""
        self.close()
    
    # -----------------------------------------------------------------------
    # MÉTODOS DE INICIALIZACIÓN PRIVADOS
    # -----------------------------------------------------------------------
    def _init_shared_memory(self):
        """Inicializa buffers en memoria compartida"""
        total_bytes = self.num_buffers * self.bytes_per_buffer
        
        if self.shm_name is None:
            # Crear nueva memoria compartida
            self.shm = shared_memory.SharedMemory(create=True, size=total_bytes)
            self.shm_name = self.shm.name
            self.logger.info(
                f"🔄 Memoria compartida creada: {self.shm_name} "
                f"({total_bytes/1e6:.1f} MB)"
            )
        else:
            # Conectar a memoria compartida existente
            self.shm = shared_memory.SharedMemory(name=self.shm_name)
            self.logger.info(f"🔄 Conectado a memoria compartida: {self.shm_name}")
        
        # Crear buffers como vistas de la memoria compartida
        self.buffers = []
        for i in range(self.num_buffers):
            offset = i * self.bytes_per_buffer
            buffer = np.ndarray(
                (self.samples_per_buffer,),
                dtype=np.complex64,
                buffer=self.shm.buf[offset:offset + self.bytes_per_buffer]
            )
            self.buffers.append(buffer)
        
        # Lock para multiprocessing
        self.lock = Lock()
    
    def _init_thread_memory(self):
        """Inicializa buffers en memoria regular (solo threads)"""
        self.buffers = []
        for i in range(self.num_buffers):
            buffer = np.empty(self.samples_per_buffer, dtype=np.complex64)
            self.buffers.append(buffer)
        
        # Lock para threads
        self.lock = threading.Lock()
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - INFORMACIÓN
    # -----------------------------------------------------------------------
    def get_shared_memory_info(self):
        """Retorna información para conectar desde otro proceso"""
        if not self.use_shared_memory:
            raise RuntimeError("Ring buffer no está en modo memoria compartida")
        return {
            'shm_name': self.shm_name,
            'num_buffers': self.num_buffers,
            'samples_per_buffer': self.samples_per_buffer,
            'dtype': np.complex64
        }
    
    def get_stats(self):
        """Retorna estadísticas del buffer."""
        with self.lock:
            return {
                'total_written': self.total_buffers_written,
                'total_read': self.total_buffers_read,
                'overflow': self.overflow_count,
                'available': self.available_count,
                'states': self.buffer_states.copy()
            }
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - OPERACIONES DE ESCRITURA
    # -----------------------------------------------------------------------
    def get_write_buffer(self):
        """Obtiene un buffer para escritura."""
        with self.lock:
            if self.buffer_states[self.write_index] == self.BUFFER_FREE:
                buffer = self.buffers[self.write_index]
                self.buffer_states[self.write_index] = self.BUFFER_FILLING
                return buffer
            
            for _ in range(self.num_buffers):
                self.write_index = (self.write_index + 1) % self.num_buffers
                if self.buffer_states[self.write_index] == self.BUFFER_FREE:
                    buffer = self.buffers[self.write_index]
                    self.buffer_states[self.write_index] = self.BUFFER_FILLING
                    return buffer
            
            self.overflow_count += 1
            if self.overflow_count % 100 == 0:
                self.logger.warning(f"⚠️ Ring buffer overflow: {self.overflow_count}")
            return None
    
    def commit_write(self):
        """Marca el buffer actual como listo para lectura."""
        with self.lock:
            if self.buffer_states[self.write_index] != self.BUFFER_FILLING:
                return False
            
            self.buffer_states[self.write_index] = self.BUFFER_READY
            self.available_count += 1
            self.total_buffers_written += 1
            
            self.write_index = (self.write_index + 1) % self.num_buffers
            
            if not self.use_shared_memory:
                self.data_available.set()
            
            return True
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - OPERACIONES DE LECTURA
    # -----------------------------------------------------------------------
    def get_read_buffer(self, timeout_ms: int = 1000):
        """Obtiene el siguiente buffer para lectura."""
        if not self.use_shared_memory:
            if self.available_count == 0:
                self.data_available.wait(timeout_ms / 1000.0)
                self.data_available.clear()
        
        with self.lock:
            if self.available_count == 0:
                return None
            
            start_idx = self.read_index
            for i in range(self.num_buffers):
                idx = (start_idx + i) % self.num_buffers
                if self.buffer_states[idx] == self.BUFFER_READY:
                    self.buffer_states[idx] = self.BUFFER_READING
                    self.read_index = (idx + 1) % self.num_buffers
                    return (self.buffers[idx], idx)
            
            return None
    
    def release_read(self, buffer_index: int):
        """Libera un buffer después de lectura."""
        with self.lock:
            if self.buffer_states[buffer_index] != self.BUFFER_READING:
                return False
            
            self.buffer_states[buffer_index] = self.BUFFER_FREE
            self.available_count -= 1
            self.total_buffers_read += 1
            
            if not self.use_shared_memory:
                self.buffer_freed.set()
            
            return True
    
    # -----------------------------------------------------------------------
    # MÉTODOS PÚBLICOS - MANTENIMIENTO
    # -----------------------------------------------------------------------
    def reset(self):
        """Reinicia el buffer a estado inicial."""
        with self.lock:
            self.buffer_states = [self.BUFFER_FREE] * self.num_buffers
            self.write_index = 0
            self.read_index = 0
            self.available_count = 0
            if not self.use_shared_memory:
                self.data_available.clear()
            self.logger.info("🔄 Ring buffer reset")
    
    def close(self):
        """Cierra la memoria compartida si está en uso."""
        if self.use_shared_memory and hasattr(self, 'shm') and self.shm:
            try:
                self.shm.close()
                self.shm.unlink()
                self.logger.info(f"🗑️ Memoria compartida liberada: {self.shm_name}")
            except:
                pass
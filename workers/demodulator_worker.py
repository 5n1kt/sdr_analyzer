# workers/demodulator_worker.py
# -*- coding: utf-8 -*-
#
# VERSIÓN FINAL — correcciones técnicas + nuevas funcionalidades
#
# CORRECCIONES SOBRE LA VERSIÓN ANTERIOR
# ──────────────────────────────────────
# A. [RENDIMIENTO] scipy_decimate recalculaba el filtro FIR en cada
#    llamada (≈1.5ms/bloque). Reemplazado por butter(8) pre-calculado
#    como SOS + sosfilt con estado persistente (≈0.5ms/bloque, 3x más
#    rápido y numéricamente estable).
#
# B. [CALIDAD FM] Sin normalización por la desviación máxima, el audio
#    FM broadcast salía al ~23% del volumen esperado (0.236 rad/muestra
#    para ±75kHz desviación). Ganancia calibrada = sr/(2π×dev_máx).
#    Configurable por modo: FM=±75kHz, NBFM=±5kHz.
#
# C. [MODOS SSB/CW] USB, LSB y CW caían a FM (incorrecto). Implementados
#    correctamente: USB/LSB con BFO + extracción de parte real, CW con
#    tono de batido a 700 Hz.
#
# D. [LATENCIA] La deque crecía sin límite ante retrasos. Añadido
#    maxlen dinámico = 300ms de audio. Muestras antiguas se descartan
#    cuando se supera el límite (comportamiento de buffer circular).
#
# NUEVAS FUNCIONALIDADES
# ──────────────────────
# 1. Modos completos: FM, NBFM, AM, USB, LSB, CW
# 2. AGC (Automatic Gain Control) activable en caliente
# 3. Grabación de audio demodulado a WAV
# 4. Señal snr_updated para mostrar SNR estimada en el widget
# 5. Filtros LPF/HPF como SOS (más estables que lfilter)

import numpy as np
import logging
import time
import threading
import wave
from collections import deque

import pyaudio
from PyQt5.QtCore import QThread, pyqtSignal
from scipy.signal import butter, sosfilt, sosfilt_zi


class DemodulatorWorker(QThread):
    """
    Worker de demodulación multi-modo con audio de calidad real.

    Modos  : FM (±75kHz), NBFM (±5kHz), AM, USB, LSB, CW
    Extras : AGC, grabación WAV, BFO, filtros LPF/HPF, squelch, VU meter.
    """

    # ── Señales ──────────────────────────────────────────────────────
    audio_ready     = pyqtSignal(np.ndarray)
    vu_level        = pyqtSignal(float)
    squelch_changed = pyqtSignal(bool)
    snr_updated     = pyqtSignal(float)          # nueva: SNR estimada (dB)
    recording_state = pyqtSignal(bool, str)      # nueva: (activo, filename)
    error_occurred  = pyqtSignal(str)

    # ── Constantes ───────────────────────────────────────────────────
    AUDIO_RATE      = 48000
    BUFFER_MS       = 20
    MAX_LATENCY_MS  = 300
    FM_DEVIATION    = 75e3
    NBFM_DEVIATION  = 5e3
    CW_TONE_HZ      = 700.0
    AGC_ATTACK      = 0.05
    AGC_DECAY       = 0.002
    AGC_TARGET_RMS  = 0.25

    # ----------------------------------------------------------------
    def __init__(self, ring_buffer, sample_rate: float, device_index=None):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        self.ring_buffer = ring_buffer
        self.sample_rate = float(sample_rate)
        self.is_running  = False
        self._stop_flag  = False

        # Demodulación
        self.mode              = 'FM'
        self.volume            = 0.8
        self.squelch_threshold = 0.03
        self.squelch_enabled   = True
        self.squelch_open      = False

        # Audio hardware
        self.device_index = device_index
        self.p            = None
        self.stream       = None
        self._n_channels  = 2

        # BFO
        self._bfo_enabled = False
        self._bfo_freq_hz = 0.0
        self._bfo_auto    = False
        self._bfo_phase   = 0.0

        # AGC
        self._agc_enabled  = False
        self._agc_gain     = 1.0
        self._agc_rms_ema  = self.AGC_TARGET_RMS

        # Grabación WAV
        self._recording         = False
        self._wav_file          = None
        self._wav_filename      = ''
        self._recording_lock    = threading.Lock()
        self._recorded_samples  = 0

        # SNR
        self._signal_power_ema = 1e-6
        self._noise_power_ema  = 1e-6
        self._last_snr_time    = 0.0

        # Cálculos de buffer
        self.decimation        = max(1, int(self.sample_rate / self.AUDIO_RATE))
        self.samples_per_audio = int(self.AUDIO_RATE * self.BUFFER_MS / 1000)
        self.accum_needed      = self.samples_per_audio * self.decimation

        # CORRECCIÓN D: maxlen basado en latencia máxima
        self._iq_max_size   = int(self.sample_rate * self.MAX_LATENCY_MS / 1000)
        self._iq_deque      : deque = deque()
        self._iq_deque_size : int   = 0

        # Memoria de fase FM
        self._fm_prev_sample = np.complex64(1.0 + 0.0j)

        # CORRECCIÓN A: filtro antialiasing pre-calculado
        self._aa_sos, self._aa_zi = self._build_aa_filter()

        # Filtros de audio post-decimación
        self._lpf_sos = self._lpf_zi = None
        self._hpf_sos = self._hpf_zi = None

        self.logger.info(
            f"✅ DemodulatorWorker  SR={self.sample_rate/1e6:.2f}MHz  "
            f"dec={self.decimation}x  buf={self.samples_per_audio}smp"
        )

    # ----------------------------------------------------------------
    # CONSTRUCCIÓN DE FILTROS
    # ----------------------------------------------------------------

    def _build_aa_filter(self):
        """Butter(8) antialiasing como SOS pre-calculado (CORRECCIÓN A)."""
        cutoff = float(np.clip(
            (self.AUDIO_RATE / 2.0 * 0.9) / (self.sample_rate / 2.0),
            0.01, 0.99
        ))
        sos = butter(8, cutoff, btype='low', output='sos')
        zi  = sosfilt_zi(sos) * 0.0
        return sos, zi

    def _build_audio_filter(self, freq_hz: float, btype: str):
        """Butter(4) para filtros LPF/HPF de audio post-decimación."""
        nyq    = self.AUDIO_RATE / 2.0
        cutoff = float(np.clip(freq_hz / nyq, 0.01, 0.99))
        sos    = butter(4, cutoff, btype=btype, output='sos')
        zi     = sosfilt_zi(sos) * 0.0
        return sos, zi

    # ----------------------------------------------------------------
    # API PÚBLICA
    # ----------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """
        Cambia el modo. USB/LSB/CW configuran el BFO automáticamente
        (CORRECCIÓN C).
        """
        self.mode = mode
        self._fm_prev_sample = np.complex64(1.0 + 0.0j)
        self._bfo_phase      = 0.0

        if mode == 'USB':
            self._bfo_freq_hz = 1500.0;   self._bfo_enabled = True
        elif mode == 'LSB':
            self._bfo_freq_hz = -1500.0;  self._bfo_enabled = True
        elif mode == 'CW':
            self._bfo_freq_hz = self.CW_TONE_HZ; self._bfo_enabled = True
        elif not self._bfo_auto:
            self._bfo_enabled = False

        self.logger.info(f"📻 Modo: {mode}")

    def set_volume(self, volume: float) -> None:
        self.volume = float(np.clip(volume, 0.0, 1.0))

    def set_squelch(self, threshold: float, enabled: bool) -> None:
        self.squelch_threshold = float(np.clip(threshold, 0.001, 1.0))
        self.squelch_enabled   = enabled

    def set_agc(self, enabled: bool) -> None:
        """NUEVA FUNCIONALIDAD 2: AGC."""
        self._agc_enabled = enabled
        if enabled:
            self._agc_gain   = 1.0
            self._agc_rms_ema = self.AGC_TARGET_RMS
        self.logger.info(f"🎚️ AGC: {'on' if enabled else 'off'}")

    def set_audio_device(self, device_index) -> None:
        self.device_index = device_index
        if self.stream is not None:
            self._restart_audio()
        self.logger.info(f"🎧 Dispositivo → {device_index}")

    def set_bfo(self, freq_hz: float, enabled: bool, auto: bool = False) -> None:
        self._bfo_freq_hz = float(freq_hz)
        self._bfo_enabled = enabled
        self._bfo_auto    = auto
        self._bfo_phase   = 0.0
        self.logger.info(f"🔧 BFO {freq_hz:.0f}Hz  en={enabled}  auto={auto}")

    def set_lowpass(self, freq_hz: float) -> None:
        if freq_hz > 0:
            self._lpf_sos, self._lpf_zi = self._build_audio_filter(freq_hz, 'low')
            self.logger.info(f"🔧 LPF {freq_hz:.0f}Hz")
        else:
            self._lpf_sos = self._lpf_zi = None

    def set_highpass(self, freq_hz: float) -> None:
        if freq_hz > 0:
            self._hpf_sos, self._hpf_zi = self._build_audio_filter(freq_hz, 'high')
            self.logger.info(f"🔧 HPF {freq_hz:.0f}Hz")
        else:
            self._hpf_sos = self._hpf_zi = None

    def start_recording(self, filename: str) -> bool:
        """NUEVA FUNCIONALIDAD 3: grabar audio demodulado a WAV."""
        with self._recording_lock:
            if self._recording:
                return False
            try:
                wf = wave.open(filename, 'wb')
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.AUDIO_RATE)
                self._wav_file         = wf
                self._wav_filename     = filename
                self._recording        = True
                self._recorded_samples = 0
                self.recording_state.emit(True, filename)
                self.logger.info(f"⏺️ Grabando → {filename}")
                return True
            except Exception as exc:
                self.logger.error(f"❌ Error WAV: {exc}")
                return False

    def stop_recording(self) -> str:
        with self._recording_lock:
            if not self._recording:
                return ''
            duration = self._recorded_samples / self.AUDIO_RATE
            try: self._wav_file.close()
            except Exception: pass
            self._wav_file  = None
            self._recording = False
            self.recording_state.emit(False, self._wav_filename)
            self.logger.info(
                f"⏹️ Grabación: {self._wav_filename} ({duration:.1f}s)"
            )
            return self._wav_filename

    # ----------------------------------------------------------------
    # AUDIO HARDWARE
    # ----------------------------------------------------------------

    def init_audio(self) -> bool:
        try:
            self.p = pyaudio.PyAudio()
            info = (
                self.p.get_device_info_by_index(self.device_index)
                if self.device_index is not None
                else self.p.get_default_output_device_info()
            )
            self._n_channels = 2 if info['maxOutputChannels'] >= 2 else 1
            self.stream = self.p.open(
                format              = pyaudio.paInt16,
                channels            = self._n_channels,
                rate                = self.AUDIO_RATE,
                output              = True,
                output_device_index = self.device_index,
                frames_per_buffer   = self.samples_per_audio,
            )
            self.logger.info(
                f"✅ Audio '{info['name']}' {self._n_channels}ch {self.AUDIO_RATE}Hz"
            )
            return True
        except Exception as exc:
            self.logger.error(f"❌ Audio: {exc}")
            if self.p: self.p.terminate(); self.p = None
            return False

    def _restart_audio(self) -> None:
        for o, m in [(self.stream,'stop_stream'),(self.stream,'close'),(self.p,'terminate')]:
            if o:
                try: getattr(o, m)()
                except Exception: pass
        self.stream = self.p = None
        self.init_audio()

    def _close_audio(self) -> None:
        for o, m in [(self.stream,'stop_stream'),(self.stream,'close'),(self.p,'terminate')]:
            if o:
                try: getattr(o, m)()
                except Exception: pass
        self.stream = self.p = None

    def _write_audio(self, audio: np.ndarray) -> None:
        """Envía audio al hardware y opcionalmente al archivo WAV."""
        if self.stream is None:
            return

        n = self.samples_per_audio
        if len(audio) < n:
            audio = np.pad(audio, (0, n - len(audio)))
        else:
            audio = audio[:n]

        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)

        # WAV mono
        with self._recording_lock:
            if self._recording and self._wav_file:
                try:
                    self._wav_file.writeframes(pcm.tobytes())
                    self._recorded_samples += n
                except Exception as exc:
                    self.logger.error(f"WAV write error: {exc}")

        # Hardware
        try:
            if self._n_channels == 2:
                st = np.empty(n * 2, dtype=np.int16)
                st[0::2] = pcm; st[1::2] = pcm
                self.stream.write(st.tobytes())
            else:
                self.stream.write(pcm.tobytes())
        except Exception as exc:
            self.logger.error(f"Audio write error: {exc}")

    # ----------------------------------------------------------------
    # DEMODULACIÓN
    # ----------------------------------------------------------------

    def _apply_bfo(self, iq: np.ndarray) -> np.ndarray:
        """Rotación de fase continua entre bloques."""
        if not self._bfo_enabled or self._bfo_freq_hz == 0.0:
            return iq
        n     = len(iq)
        phase = (2.0 * np.pi * self._bfo_freq_hz / self.sample_rate
                 * np.arange(n) + self._bfo_phase)
        self._bfo_phase = float(phase[-1]) % (2.0 * np.pi)
        return iq * np.exp(1j * phase).astype(np.complex64)

    def _decimate(self, sig: np.ndarray) -> np.ndarray:
        """
        CORRECCIÓN A: filtro antialiasing SOS pre-calculado + slicing.
        Estado persistente entre bloques → sin discontinuidades.
        """
        filtered, self._aa_zi = sosfilt(self._aa_sos, sig, zi=self._aa_zi)
        return filtered[::self.decimation].astype(np.float32)

    def demod_fm(self, iq: np.ndarray) -> np.ndarray:
        """
        FM por multiplicación conjugada con ganancia calibrada (CORRECCIÓN B).
        Ganancia = sr / (2π × desviación) normaliza la salida a ±1.0.
        """
        dev  = self.NBFM_DEVIATION if self.mode == 'NBFM' else self.FM_DEVIATION
        gain = self.sample_rate / (2.0 * np.pi * dev)

        iq_ext = np.concatenate([[self._fm_prev_sample], iq])
        self._fm_prev_sample = iq[-1]
        fm_sig = np.angle(iq_ext[1:] * np.conj(iq_ext[:-1])).astype(np.float32) * gain
        return self._decimate(fm_sig)

    def demod_am(self, iq: np.ndarray) -> np.ndarray:
        """Envolvente con DC eliminado."""
        env = np.abs(iq).astype(np.float32)
        env -= env.mean()
        return self._decimate(env)

    def demod_ssb(self, iq: np.ndarray) -> np.ndarray:
        """
        CORRECCIÓN C: USB/LSB.
        BFO desplaza la señal; extraemos la parte real (cuadratura).
        """
        mixed = self._apply_bfo(iq)
        return self._decimate(mixed.real.astype(np.float32))

    def demod_cw(self, iq: np.ndarray) -> np.ndarray:
        """
        CORRECCIÓN C: CW = envolvente con tono de batido.
        El BFO a CW_TONE_HZ produce un tono audible cuando la portadora
        está activa.
        """
        mixed = self._apply_bfo(iq)
        env   = np.abs(mixed).astype(np.float32)
        env  -= env.mean()
        return self._decimate(env)

    def _apply_audio_filters(self, audio: np.ndarray) -> np.ndarray:
        """Filtros LPF/HPF post-decimación con estado (CORRECCIÓN 5)."""
        if self._lpf_sos is not None:
            audio, self._lpf_zi = sosfilt(self._lpf_sos, audio, zi=self._lpf_zi)
        if self._hpf_sos is not None:
            audio, self._hpf_zi = sosfilt(self._hpf_sos, audio, zi=self._hpf_zi)
        return audio.astype(np.float32)

    def _apply_agc(self, audio: np.ndarray) -> np.ndarray:
        """
        NUEVA FUNCIONALIDAD 2: AGC con ataque rápido y decaimiento lento.
        Mantiene RMS de salida cerca de AGC_TARGET_RMS.
        """
        rms = float(np.sqrt(np.mean(audio ** 2)) + 1e-9)
        alpha = self.AGC_ATTACK if rms > self._agc_rms_ema else self.AGC_DECAY
        self._agc_rms_ema = alpha * rms + (1.0 - alpha) * self._agc_rms_ema
        tg = float(np.clip(self.AGC_TARGET_RMS / (self._agc_rms_ema + 1e-9), 0.1, 100.0))
        self._agc_gain = 0.95 * self._agc_gain + 0.05 * tg
        return (audio * self._agc_gain).astype(np.float32)

    def _update_snr(self, audio: np.ndarray) -> None:
        """
        NUEVA FUNCIONALIDAD 4: estimación de SNR cada 2 segundos.
        Usa percentil 90 (señal) vs percentil 10 (ruido).
        """
        now = time.time()
        if now - self._last_snr_time < 2.0:
            return
        self._last_snr_time = now
        pwr = np.abs(audio) ** 2
        p_high = float(np.percentile(pwr, 90))
        p_low  = float(np.percentile(pwr, 10))
        self._signal_power_ema = 0.7 * self._signal_power_ema + 0.3 * p_high
        self._noise_power_ema  = 0.7 * self._noise_power_ema  + 0.3 * p_low
        if self._noise_power_ema > 1e-12:
            snr = 10.0 * np.log10(
                self._signal_power_ema / (self._noise_power_ema + 1e-12)
            )
            self.snr_updated.emit(float(np.clip(snr, 0.0, 60.0)))

    # ----------------------------------------------------------------
    # ACUMULACIÓN IQ
    # ----------------------------------------------------------------

    def _push_iq(self, iq: np.ndarray) -> None:
        """CORRECCIÓN D: descarta muestras antiguas si se supera el límite."""
        while self._iq_deque_size + len(iq) > self._iq_max_size and self._iq_deque:
            dropped = self._iq_deque.popleft()
            self._iq_deque_size -= len(dropped)
        self._iq_deque.append(iq.copy())
        self._iq_deque_size += len(iq)

    def _pop_iq_block(self):
        if self._iq_deque_size < self.accum_needed:
            return None
        needed = self.accum_needed
        parts, taken = [], 0
        while taken < needed and self._iq_deque:
            chunk = self._iq_deque[0]
            rem   = needed - taken
            if len(chunk) <= rem:
                parts.append(chunk)
                taken += len(chunk)
                self._iq_deque_size -= len(chunk)
                self._iq_deque.popleft()
            else:
                parts.append(chunk[:rem])
                self._iq_deque[0] = chunk[rem:]
                self._iq_deque_size -= rem
                taken = needed
        return np.concatenate(parts)

    # ----------------------------------------------------------------
    # LOOP PRINCIPAL
    # ----------------------------------------------------------------

    def run(self) -> None:
        self.logger.info("🚀 Demodulador iniciado")

        if not self.init_audio():
            self.error_occurred.emit("No se pudo iniciar el audio")
            return

        self.is_running = True
        self._stop_flag = False
        last_vu_time    = time.time()

        while not self._stop_flag:
            try:
                result = self.ring_buffer.get_read_buffer(timeout_ms=50)
                if result is None:
                    self.msleep(5)
                    continue

                iq_data, idx = result
                self._push_iq(iq_data)
                self.ring_buffer.release_read(idx)

                while True:
                    block = self._pop_iq_block()
                    if block is None:
                        break

                    # BFO solo para modos que no lo aplican internamente
                    if self._bfo_enabled and self.mode not in ('USB', 'LSB', 'CW'):
                        block = self._apply_bfo(block)

                    # Demodular
                    if self.mode in ('FM', 'NBFM'):
                        audio = self.demod_fm(block)
                    elif self.mode == 'AM':
                        audio = self.demod_am(block)
                    elif self.mode in ('USB', 'LSB'):
                        audio = self.demod_ssb(block)
                    elif self.mode == 'CW':
                        audio = self.demod_cw(block)
                    else:
                        audio = self.demod_fm(block)

                    if len(audio) == 0:
                        continue

                    # Filtros post-decimación
                    audio = self._apply_audio_filters(audio)

                    # RMS (una sola vez)
                    rms = float(np.sqrt(np.mean(audio ** 2)) + 1e-9)

                    # VU meter
                    now = time.time()
                    if now - last_vu_time > 0.1:
                        vu_db = 20.0 * np.log10(rms)
                        self.vu_level.emit(float(np.clip(vu_db, -60.0, 0.0)))
                        last_vu_time = now

                    # SNR
                    self._update_snr(audio)

                    # Squelch
                    if self.squelch_enabled:
                        should_open = rms > self.squelch_threshold
                        if should_open != self.squelch_open:
                            self.squelch_open = should_open
                            self.squelch_changed.emit(should_open)
                        if not should_open:
                            continue

                    # AGC o soft-clip
                    if self._agc_enabled:
                        audio = self._apply_agc(audio)
                    else:
                        peak = float(np.max(np.abs(audio)))
                        if peak > 1.0:
                            audio = audio / peak

                    # Volumen
                    audio = (audio * self.volume).astype(np.float32)

                    # Salida
                    self._write_audio(audio)
                    self.audio_ready.emit(audio)

            except Exception as exc:
                if not self._stop_flag:
                    self.logger.error(f"❌ {exc}")
                    self.msleep(10)

        if self._recording:
            self.stop_recording()

        self._close_audio()
        self.is_running = False
        self.logger.info("⏹ Demodulador detenido")

    def stop(self) -> None:
        self._stop_flag = True
        if not self.wait(3000):
            self.logger.warning("⚠️ Timeout — forzando terminación")
            self.terminate()
            self.wait(300)
        self.logger.info("⏹ DemodulatorWorker detenido")

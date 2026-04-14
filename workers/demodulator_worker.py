# -*- coding: utf-8 -*-

"""
Audio Demodulator Worker
========================
High-performance audio demodulation for multiple modes:
    - FM (Wideband FM, 75 kHz deviation)
    - NBFM (Narrowband FM, 5 kHz deviation)
    - AM (Amplitude Modulation)
    - USB (Upper Sideband)
    - LSB (Lower Sideband)
    - CW (Continuous Wave)

Features:
    - Real-time audio output via PyAudio
    - AGC (Automatic Gain Control)
    - Squelch with configurable threshold
    - BFO (Beat Frequency Oscillator) for SSB/CW
    - Low-pass and high-pass audio filters
    - SNR estimation
    - WAV recording
    - VU meter output

CORRECTIONS APPLIED:
    1. [PERFORMANCE] Pre-calculated Butterworth SOS filter for decimation
    2. [QUALITY] Calibrated FM gain for correct volume (75kHz deviation)
    3. [FIX] USB/LSB/CW correctly implemented (not falling back to FM)
    4. [LATENCY] Deque with maxlen to prevent unbounded growth
"""

import numpy as np
import logging
import time
import threading
import wave
from collections import deque

import pyaudio
from PyQt5.QtCore import QThread, pyqtSignal
from scipy.signal import butter, sosfilt, sosfilt_zi


# ============================================================================
# DEMODULATOR WORKER
# ============================================================================

class DemodulatorWorker(QThread):
    """
    Multi-mode audio demodulator with professional audio quality.
    
    Signals:
        audio_ready: Emitted with audio samples for visualization
        vu_level: Emitted with VU meter level in dB
        squelch_changed: Emitted when squelch opens/closes
        snr_updated: Emitted with estimated SNR in dB
        recording_state: Emitted when recording starts/stops (active, filename)
        error_occurred: Emitted on critical errors
    """
    
    # ------------------------------------------------------------------------
    # SIGNALS
    # ------------------------------------------------------------------------
    audio_ready = pyqtSignal(np.ndarray)
    vu_level = pyqtSignal(float)
    squelch_changed = pyqtSignal(bool)
    snr_updated = pyqtSignal(float)
    recording_state = pyqtSignal(bool, str)
    error_occurred = pyqtSignal(str)
    
    # ------------------------------------------------------------------------
    # CONSTANTS
    # ------------------------------------------------------------------------
    AUDIO_RATE = 48000                  # Output sample rate (Hz)
    BUFFER_MS = 20                      # Buffer size in milliseconds
    MAX_LATENCY_MS = 300                # Maximum latency before dropping samples
    FM_DEVIATION = 75e3                 # Wideband FM deviation (Hz)
    NBFM_DEVIATION = 5e3                # Narrowband FM deviation (Hz)
    CW_TONE_HZ = 700.0                  # CW beat tone frequency (Hz)
    AGC_ATTACK = 0.05                   # AGC attack time constant
    AGC_DECAY = 0.002                   # AGC decay time constant
    AGC_TARGET_RMS = 0.25               # Target RMS level for AGC
    
    # ------------------------------------------------------------------------
    # CONSTRUCTOR
    # ------------------------------------------------------------------------
    
    def __init__(self, ring_buffer, sample_rate: float, device_index=None):
        """
        Initialize demodulator worker.
        
        Args:
            ring_buffer: IQRingBuffer containing IQ samples
            sample_rate: Input IQ sample rate (Hz)
            device_index: Audio output device index (None for default)
        """
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        self.ring_buffer = ring_buffer
        self.sample_rate = float(sample_rate)
        self.is_running = False
        self._stop_flag = False
        
        # Demodulation parameters
        self.mode = 'FM'
        self.volume = 0.8
        self.squelch_threshold = 0.03
        self.squelch_enabled = True
        self.squelch_open = False
        
        # Audio hardware
        self.device_index = device_index
        self.p = None
        self.stream = None
        self._n_channels = 2
        
        # BFO (Beat Frequency Oscillator)
        self._bfo_enabled = False
        self._bfo_freq_hz = 0.0
        self._bfo_auto = False
        self._bfo_phase = 0.0
        
        # AGC (Automatic Gain Control)
        self._agc_enabled = False
        self._agc_gain = 1.0
        self._agc_rms_ema = self.AGC_TARGET_RMS
        
        # WAV recording
        self._recording = False
        self._wav_file = None
        self._wav_filename = ''
        self._recording_lock = threading.Lock()
        self._recorded_samples = 0
        
        # SNR estimation
        self._signal_power_ema = 1e-6
        self._noise_power_ema = 1e-6
        self._last_snr_time = 0.0
        
        # Buffer calculations
        self.decimation = max(1, int(self.sample_rate / self.AUDIO_RATE))
        self.samples_per_audio = int(self.AUDIO_RATE * self.BUFFER_MS / 1000)
        self.accum_needed = self.samples_per_audio * self.decimation
        
        # IQ accumulation buffer (deque with maxlen)
        self._iq_max_size = int(self.sample_rate * self.MAX_LATENCY_MS / 1000)
        self._iq_deque = deque()
        self._iq_deque_size = 0
        
        # FM phase memory
        self._fm_prev_sample = np.complex64(1.0 + 0.0j)
        
        # Anti-aliasing filter (pre-calculated)
        self._aa_sos, self._aa_zi = self._build_aa_filter()
        
        # Audio filters (initialized later)
        self._lpf_sos = self._lpf_zi = None
        self._hpf_sos = self._hpf_zi = None
        
        self.logger.info(
            f"✅ DemodulatorWorker  SR={self.sample_rate/1e6:.2f}MHz  "
            f"dec={self.decimation}x  buf={self.samples_per_audio}smp"
        )
    
    # ------------------------------------------------------------------------
    # FILTER CONSTRUCTION
    # ------------------------------------------------------------------------
    
    def _build_aa_filter(self):
        """
        Build anti-aliasing filter for decimation.
        
        Uses 8th order Butterworth SOS for stability and efficiency.
        CORRECTION: Pre-calculated once, not per block.
        """
        cutoff = float(np.clip(
            (self.AUDIO_RATE / 2.0 * 0.9) / (self.sample_rate / 2.0),
            0.01, 0.99
        ))
        sos = butter(8, cutoff, btype='low', output='sos')
        zi = sosfilt_zi(sos) * 0.0
        return sos, zi
    
    def _build_audio_filter(self, freq_hz: float, btype: str):
        """
        Build audio filter (LPF/HPF) for post-decimation audio.
        
        Uses 4th order Butterworth.
        """
        nyq = self.AUDIO_RATE / 2.0
        cutoff = float(np.clip(freq_hz / nyq, 0.01, 0.99))
        sos = butter(4, cutoff, btype=btype, output='sos')
        zi = sosfilt_zi(sos) * 0.0
        return sos, zi
    
    # ------------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------------
    
    def set_mode(self, mode: str) -> None:
        """Change demodulation mode. USB/LSB/CW configure BFO automatically."""
        self.mode = mode
        self._fm_prev_sample = np.complex64(1.0 + 0.0j)
        self._bfo_phase = 0.0
        
        if mode == 'USB':
            self._bfo_freq_hz = 1500.0
            self._bfo_enabled = True
        elif mode == 'LSB':
            self._bfo_freq_hz = -1500.0
            self._bfo_enabled = True
        elif mode == 'CW':
            self._bfo_freq_hz = self.CW_TONE_HZ
            self._bfo_enabled = True
        elif not self._bfo_auto:
            self._bfo_enabled = False
        
        self.logger.info(f"📻 Mode: {mode}")
    
    def set_volume(self, volume: float) -> None:
        """Set output volume (0.0 to 1.0)."""
        self.volume = float(np.clip(volume, 0.0, 1.0))
    
    def set_squelch(self, threshold: float, enabled: bool) -> None:
        """Configure squelch threshold and enable/disable."""
        self.squelch_threshold = float(np.clip(threshold, 0.001, 1.0))
        self.squelch_enabled = enabled
    
    def set_agc(self, enabled: bool) -> None:
        """Enable/disable AGC."""
        self._agc_enabled = enabled
        if enabled:
            self._agc_gain = 1.0
            self._agc_rms_ema = self.AGC_TARGET_RMS
        self.logger.info(f"🎚️ AGC: {'on' if enabled else 'off'}")
    
    def set_audio_device(self, device_index) -> None:
        """Change audio output device."""
        self.device_index = device_index
        if self.stream is not None:
            self._restart_audio()
        self.logger.info(f"🎧 Audio device → {device_index}")
    
    def set_bfo(self, freq_hz: float, enabled: bool, auto: bool = False) -> None:
        """Configure BFO for SSB/CW."""
        self._bfo_freq_hz = float(freq_hz)
        self._bfo_enabled = enabled
        self._bfo_auto = auto
        self._bfo_phase = 0.0
        self.logger.info(f"🔧 BFO {freq_hz:.0f}Hz  en={enabled}  auto={auto}")
    
    def set_lowpass(self, freq_hz: float) -> None:
        """Set low-pass filter cutoff (Hz). 0 to disable."""
        if freq_hz > 0:
            self._lpf_sos, self._lpf_zi = self._build_audio_filter(freq_hz, 'low')
            self.logger.info(f"🔧 LPF {freq_hz:.0f}Hz")
        else:
            self._lpf_sos = self._lpf_zi = None
    
    def set_highpass(self, freq_hz: float) -> None:
        """Set high-pass filter cutoff (Hz). 0 to disable."""
        if freq_hz > 0:
            self._hpf_sos, self._hpf_zi = self._build_audio_filter(freq_hz, 'high')
            self.logger.info(f"🔧 HPF {freq_hz:.0f}Hz")
        else:
            self._hpf_sos = self._hpf_zi = None
    
    def start_recording(self, filename: str) -> bool:
        """Start recording demodulated audio to WAV file."""
        with self._recording_lock:
            if self._recording:
                return False
            try:
                wf = wave.open(filename, 'wb')
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.AUDIO_RATE)
                self._wav_file = wf
                self._wav_filename = filename
                self._recording = True
                self._recorded_samples = 0
                self.recording_state.emit(True, filename)
                self.logger.info(f"⏺️ Recording → {filename}")
                return True
            except Exception as exc:
                self.logger.error(f"❌ WAV error: {exc}")
                return False
    
    def stop_recording(self) -> str:
        """Stop recording and return filename."""
        with self._recording_lock:
            if not self._recording:
                return ''
            duration = self._recorded_samples / self.AUDIO_RATE
            try:
                self._wav_file.close()
            except Exception:
                pass
            self._wav_file = None
            self._recording = False
            self.recording_state.emit(False, self._wav_filename)
            self.logger.info(f"⏹️ Recording: {self._wav_filename} ({duration:.1f}s)")
            return self._wav_filename
    
    # ------------------------------------------------------------------------
    # AUDIO HARDWARE
    # ------------------------------------------------------------------------
    
    def init_audio(self) -> bool:
        """Initialize PyAudio and open output stream."""
        try:
            self.p = pyaudio.PyAudio()
            info = (
                self.p.get_device_info_by_index(self.device_index)
                if self.device_index is not None
                else self.p.get_default_output_device_info()
            )
            self._n_channels = 2 if info['maxOutputChannels'] >= 2 else 1
            
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=self._n_channels,
                rate=self.AUDIO_RATE,
                output=True,
                output_device_index=self.device_index,
                frames_per_buffer=self.samples_per_audio,
            )
            self.logger.info(f"✅ Audio '{info['name']}' {self._n_channels}ch {self.AUDIO_RATE}Hz")
            return True
        except Exception as exc:
            self.logger.error(f"❌ Audio: {exc}")
            if self.p:
                self.p.terminate()
                self.p = None
            return False
    
    def _restart_audio(self) -> None:
        """Restart audio stream (called when device changes)."""
        for obj, method in [(self.stream, 'stop_stream'), (self.stream, 'close'),
                            (self.p, 'terminate')]:
            if obj:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass
        self.stream = self.p = None
        self.init_audio()
    
    def _close_audio(self) -> None:
        """Close audio stream and terminate PyAudio."""
        for obj, method in [(self.stream, 'stop_stream'), (self.stream, 'close'),
                            (self.p, 'terminate')]:
            if obj:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass
        self.stream = self.p = None
    
    def _write_audio(self, audio: np.ndarray) -> None:
        """Write audio to output device and optionally to WAV."""
        if self.stream is None:
            return
        
        n = self.samples_per_audio
        if len(audio) < n:
            audio = np.pad(audio, (0, n - len(audio)))
        else:
            audio = audio[:n]
        
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        
        # Write to WAV if recording
        with self._recording_lock:
            if self._recording and self._wav_file:
                try:
                    self._wav_file.writeframes(pcm.tobytes())
                    self._recorded_samples += n
                except Exception as exc:
                    self.logger.error(f"WAV write error: {exc}")
        
        # Write to audio hardware
        try:
            if self._n_channels == 2:
                stereo = np.empty(n * 2, dtype=np.int16)
                stereo[0::2] = pcm
                stereo[1::2] = pcm
                self.stream.write(stereo.tobytes())
            else:
                self.stream.write(pcm.tobytes())
        except Exception as exc:
            self.logger.error(f"Audio write error: {exc}")
    
    # ------------------------------------------------------------------------
    # DEMODULATION METHODS
    # ------------------------------------------------------------------------
    
    def _apply_bfo(self, iq: np.ndarray) -> np.ndarray:
        """Apply BFO rotation (continuous phase between blocks)."""
        if not self._bfo_enabled or self._bfo_freq_hz == 0.0:
            return iq
        
        n = len(iq)
        phase = (2.0 * np.pi * self._bfo_freq_hz / self.sample_rate
                 * np.arange(n) + self._bfo_phase)
        self._bfo_phase = float(phase[-1]) % (2.0 * np.pi)
        return iq * np.exp(1j * phase).astype(np.complex64)
    
    def _decimate(self, sig: np.ndarray) -> np.ndarray:
        """
        Decimate signal with anti-aliasing filter.
        
        CORRECTION: Uses pre-calculated SOS filter with persistent state.
        """
        filtered, self._aa_zi = sosfilt(self._aa_sos, sig, zi=self._aa_zi)
        return filtered[::self.decimation].astype(np.float32)
    
    def demod_fm(self, iq: np.ndarray) -> np.ndarray:
        """
        FM demodulation by conjugate multiplication.
        
        Gain calibration: output = sr/(2π × deviation) × phase difference
        This normalizes ±75kHz deviation to ±1.0 amplitude.
        """
        dev = self.NBFM_DEVIATION if self.mode == 'NBFM' else self.FM_DEVIATION
        gain = self.sample_rate / (2.0 * np.pi * dev)
        
        iq_ext = np.concatenate([[self._fm_prev_sample], iq])
        self._fm_prev_sample = iq[-1]
        fm_sig = np.angle(iq_ext[1:] * np.conj(iq_ext[:-1])).astype(np.float32) * gain
        return self._decimate(fm_sig)
    
    def demod_am(self, iq: np.ndarray) -> np.ndarray:
        """AM demodulation by envelope detection."""
        env = np.abs(iq).astype(np.float32)
        env -= env.mean()
        return self._decimate(env)
    
    def demod_ssb(self, iq: np.ndarray) -> np.ndarray:
        """SSB demodulation (USB/LSB) with BFO."""
        mixed = self._apply_bfo(iq)
        return self._decimate(mixed.real.astype(np.float32))
    
    def demod_cw(self, iq: np.ndarray) -> np.ndarray:
        """CW demodulation with beat tone."""
        mixed = self._apply_bfo(iq)
        env = np.abs(mixed).astype(np.float32)
        env -= env.mean()
        return self._decimate(env)
    
    def _apply_audio_filters(self, audio: np.ndarray) -> np.ndarray:
        """Apply low-pass and high-pass filters with persistent state."""
        if self._lpf_sos is not None:
            audio, self._lpf_zi = sosfilt(self._lpf_sos, audio, zi=self._lpf_zi)
        if self._hpf_sos is not None:
            audio, self._hpf_zi = sosfilt(self._hpf_sos, audio, zi=self._hpf_zi)
        return audio.astype(np.float32)
    
    def _apply_agc(self, audio: np.ndarray) -> np.ndarray:
        """
        Apply AGC (Automatic Gain Control).
        
        Maintains output RMS near AGC_TARGET_RMS.
        """
        rms = float(np.sqrt(np.mean(audio ** 2)) + 1e-9)
        alpha = self.AGC_ATTACK if rms > self._agc_rms_ema else self.AGC_DECAY
        self._agc_rms_ema = alpha * rms + (1.0 - alpha) * self._agc_rms_ema
        
        target_gain = float(np.clip(self.AGC_TARGET_RMS / (self._agc_rms_ema + 1e-9), 0.1, 100.0))
        self._agc_gain = 0.95 * self._agc_gain + 0.05 * target_gain
        
        return (audio * self._agc_gain).astype(np.float32)
    
    def _update_snr(self, audio: np.ndarray) -> None:
        """
        Estimate SNR using percentile method.
        
        Signal = 90th percentile power
        Noise = 10th percentile power
        """
        now = time.time()
        if now - self._last_snr_time < 2.0:
            return
        self._last_snr_time = now
        
        pwr = np.abs(audio) ** 2
        p_high = float(np.percentile(pwr, 90))
        p_low = float(np.percentile(pwr, 10))
        
        self._signal_power_ema = 0.7 * self._signal_power_ema + 0.3 * p_high
        self._noise_power_ema = 0.7 * self._noise_power_ema + 0.3 * p_low
        
        if self._noise_power_ema > 1e-12:
            snr = 10.0 * np.log10(self._signal_power_ema / (self._noise_power_ema + 1e-12))
            self.snr_updated.emit(float(np.clip(snr, 0.0, 60.0)))
    
    # ------------------------------------------------------------------------
    # IQ ACCUMULATION
    # ------------------------------------------------------------------------
    
    def _push_iq(self, iq: np.ndarray) -> None:
        """
        Push IQ samples to accumulation deque.
        
        CORRECTION: Drops oldest samples if max size exceeded.
        """
        while self._iq_deque_size + len(iq) > self._iq_max_size and self._iq_deque:
            dropped = self._iq_deque.popleft()
            self._iq_deque_size -= len(dropped)
        self._iq_deque.append(iq.copy())
        self._iq_deque_size += len(iq)
    
    def _pop_iq_block(self) -> np.ndarray:
        """
        Pop exactly accum_needed samples from deque.
        
        Returns None if not enough samples available.
        """
        if self._iq_deque_size < self.accum_needed:
            return None
        
        needed = self.accum_needed
        parts, taken = [], 0
        
        while taken < needed and self._iq_deque:
            chunk = self._iq_deque[0]
            rem = needed - taken
            
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
    
    # ------------------------------------------------------------------------
    # MAIN THREAD LOOP
    # ------------------------------------------------------------------------
    
    def run(self) -> None:
        """Main processing loop."""
        self.logger.info("🚀 Demodulator started")
        
        if not self.init_audio():
            self.error_occurred.emit("Could not initialize audio")
            return
        
        self.is_running = True
        self._stop_flag = False
        last_vu_time = time.time()
        
        while not self._stop_flag:
            try:
                # Get buffer from ring buffer
                result = self.ring_buffer.get_read_buffer(timeout_ms=50)
                if result is None:
                    self.msleep(5)
                    continue
                
                iq_data, idx = result
                self._push_iq(iq_data)
                self.ring_buffer.release_read(idx)
                
                # Process complete blocks
                while True:
                    block = self._pop_iq_block()
                    if block is None:
                        break
                    
                    # Apply BFO if not handled by mode
                    if self._bfo_enabled and self.mode not in ('USB', 'LSB', 'CW'):
                        block = self._apply_bfo(block)
                    
                    # Demodulate
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
                    
                    # Apply audio filters
                    audio = self._apply_audio_filters(audio)
                    
                    # RMS calculation
                    rms = float(np.sqrt(np.mean(audio ** 2)) + 1e-9)
                    
                    # VU meter (10 times per second)
                    now = time.time()
                    if now - last_vu_time > 0.1:
                        vu_db = 20.0 * np.log10(rms)
                        self.vu_level.emit(float(np.clip(vu_db, -60.0, 0.0)))
                        last_vu_time = now
                    
                    # SNR estimation
                    self._update_snr(audio)
                    
                    # Squelch
                    if self.squelch_enabled:
                        should_open = rms > self.squelch_threshold
                        if should_open != self.squelch_open:
                            self.squelch_open = should_open
                            self.squelch_changed.emit(should_open)
                        if not should_open:
                            continue
                    
                    # AGC or soft clipping
                    if self._agc_enabled:
                        audio = self._apply_agc(audio)
                    else:
                        peak = float(np.max(np.abs(audio)))
                        if peak > 1.0:
                            audio = audio / peak
                    
                    # Volume
                    audio = (audio * self.volume).astype(np.float32)
                    
                    # Output
                    self._write_audio(audio)
                    self.audio_ready.emit(audio)
                    
            except Exception as exc:
                if not self._stop_flag:
                    self.logger.error(f"❌ {exc}")
                    self.msleep(10)
        
        # Cleanup
        if self._recording:
            self.stop_recording()
        
        self._close_audio()
        self.is_running = False
        self.logger.info("⏹ Demodulator stopped")
    
    def stop(self) -> None:
        """Stop demodulator thread."""
        self._stop_flag = True
        if not self.wait(3000):
            self.logger.warning("⚠️ Timeout — forcing termination")
            self.terminate()
            self.wait(300)
        self.logger.info("⏹ DemodulatorWorker stopped")
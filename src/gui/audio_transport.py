"""One shared, streaming transport for aligned canonical stem WAV files."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import QIODevice, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices


class StemMixDevice(QIODevice):
    """Pull-mode float PCM source whose audible membership can change in place."""
    def __init__(self, paths: dict[str, Path], parent: QObject | None = None, *, buffered: bool = False,
                 sample_format=QAudioFormat.SampleFormat.Float):
        super().__init__(parent)
        self._lock = threading.RLock()
        # The sink callback must never wait for soundfile/NumPy rendering.  Keep
        # queued bytes behind their own very short-lived lock.
        self._ring_lock = threading.Lock()
        self._files = {key: sf.SoundFile(path) for key, path in paths.items()}
        infos = [(item.samplerate, item.channels, len(item)) for item in self._files.values()]
        if not infos or len({item[:2] for item in infos}) != 1 or max(x[2] for x in infos) - min(x[2] for x in infos) > 1:
            raise ValueError("Stem audio dimensions are not aligned.")
        self.sample_rate, self.channels = infos[0][:2]
        self.total_frames = min(item[2] for item in infos)
        self.frame_position = 0
        self._pending = bytearray()
        self._buffered = buffered
        self._sample_format = sample_format
        self._sample_bytes = {QAudioFormat.SampleFormat.Float: 4, QAudioFormat.SampleFormat.Int16: 2,
                              QAudioFormat.SampleFormat.Int32: 4}[sample_format]
        self._audible = tuple(paths)
        self._transition_from = self._audible
        self._transition_frames = 0
        self._peaks = {key: 1.0 for key in paths}
        self._ring = bytearray(); self._ring_target = 32768; self._producer_eof = False; self._closing = False
        self.underrun_count = 0; self.read_calls = 0; self.max_read_seconds = 0.0
        self.max_request_gap_seconds = 0.0; self.max_render_seconds = 0.0; self._last_request = None
        self.open(QIODevice.OpenModeFlag.ReadOnly)
        self._producer = None
        if buffered:
            self._producer = threading.Thread(target=self._produce, name="MusicReviverAudioProducer", daemon=True)
            self._producer.start()

    def set_audible(self, ids: tuple[str, ...]) -> None:
        with self._lock:
            value = tuple(key for key in ids if key in self._files)
            if value != self._audible:
                self._transition_from = self._audible; self._audible = value
                self._transition_frames = round(self.sample_rate * .005)

    def set_peaks(self, peaks: dict[str, float]) -> None:
        with self._lock: self._peaks.update(peaks)

    def configure_prefetch(self, byte_count: int) -> None:
        with self._ring_lock: self._ring_target = max(32768, int(byte_count))

    def wait_until_prefetched(self, timeout: float = 1.0) -> bool:
        deadline=time.perf_counter()+timeout
        while time.perf_counter()<deadline:
            with self._ring_lock:
                queued = len(self._ring); target = self._ring_target
            with self._lock:
                remaining = (self.total_frames-self.frame_position)*self.channels*self._sample_bytes
                at_end = self.frame_position >= self.total_frames
            if queued >= min(target, remaining + queued): return True
            if at_end: return bool(queued)
            time.sleep(.002)
        return False

    def seek_frame(self, frame: int) -> None:
        with self._lock:
            self._pending.clear()
            with self._ring_lock:
                self._ring.clear()
                self._producer_eof = False
            self.frame_position = max(0, min(self.total_frames, int(frame)))
            for source in self._files.values(): source.seek(self.frame_position)

    def readData(self, maxlen: int) -> bytes:
        if maxlen <= 0: return b""
        started = time.perf_counter()
        now = time.perf_counter(); self.read_calls += 1
        if self._last_request is not None: self.max_request_gap_seconds = max(self.max_request_gap_seconds, now-self._last_request)
        self._last_request = now
        if self._buffered:
            with self._ring_lock:
                if not self._ring and self._producer_eof: return b""
                count = min(maxlen, len(self._ring)); result = bytes(self._ring[:count]); del self._ring[:count]
            if count < maxlen:
                self.underrun_count += 1; result += bytes(maxlen-count)
            self.max_read_seconds = max(self.max_read_seconds, time.perf_counter()-started)
            return result
        with self._lock:
            frame_bytes = self._sample_bytes * self.channels
            while len(self._pending) < maxlen and self.frame_position < self.total_frames:
                frames = min((maxlen - len(self._pending) + frame_bytes - 1) // frame_bytes,
                             self.total_frames - self.frame_position)
                self._pending.extend(self._render(frames))
            result = bytes(self._pending[:maxlen])
            del self._pending[:len(result)]
            self.max_read_seconds = max(self.max_read_seconds, time.perf_counter()-started)
            return result

    def _render(self, frames: int) -> bytes:
        started=time.perf_counter(); audible=self._audible; previous=self._transition_from
        arrays={key:source.read(frames,dtype="float32",always_2d=True) for key,source in self._files.items()}
        mixed=np.zeros((frames,self.channels),np.float32)
        for key in audible:
            data=arrays[key]; mixed[:len(data)] += data
        mixed *= self.safety_gain(audible)
        if self._transition_frames and previous != audible:
            old=np.zeros_like(mixed)
            for key in previous:
                data=arrays[key]; old[:len(data)] += data
            old *= self.safety_gain(previous); count=min(frames,self._transition_frames)
            alpha=np.linspace(0,1,count,endpoint=True,dtype=np.float32)[:,None]; mixed[:count]=old[:count]*(1-alpha)+mixed[:count]*alpha
            self._transition_frames -= count
            if not self._transition_frames:self._transition_from=audible
        self.frame_position += frames; self.max_render_seconds=max(self.max_render_seconds,time.perf_counter()-started)
        if self._sample_format == QAudioFormat.SampleFormat.Float:return mixed.astype("<f4",copy=False).tobytes()
        clipped=np.clip(mixed,-1,1)
        if self._sample_format == QAudioFormat.SampleFormat.Int16:return np.rint(clipped*32767).astype("<i2").tobytes()
        return np.rint(clipped*2147483647).astype("<i4").tobytes()

    def _produce(self):
        while True:
            with self._lock:
                if self._closing:return
                with self._ring_lock:
                    queued = len(self._ring); target = self._ring_target
                if queued >= target or self.frame_position >= self.total_frames:
                    need=False
                else:
                    frames=min(2048,self.total_frames-self.frame_position)
                    rendered = self._render(frames)
                    with self._ring_lock:
                        self._ring.extend(rendered)
                        self._producer_eof = self.frame_position >= self.total_frames
                    need=True
            if not need: time.sleep(.002)

    def safety_gain(self, audible: tuple[str, ...] | None = None) -> float:
        audible = self._audible if audible is None else audible
        bound = sum(self._peaks.get(key, 1.0) for key in audible)
        return min(1.0, .944060876 / bound) if bound > 0 else 1.0

    def writeData(self, data): return 0
    def bytesAvailable(self):
        if self._buffered:
            with self._ring_lock: queued=len(self._ring)
        else: queued=len(self._pending)
        return queued + max(0, (self.total_frames - self.frame_position) * self.channels * self._sample_bytes) + super().bytesAvailable()

    def close_sources(self):
        with self._lock:
            self._closing = True
            for source in self._files.values(): source.close()
        if self._producer:self._producer.join(timeout=2)
        self.close()


class NullAudioSink(QObject):
    """Logical sink for headless review; it never initializes native audio."""

    def __init__(self, fmt: QAudioFormat, parent: QObject | None = None):
        super().__init__(parent)
        self._buffer_size = round(fmt.bytesForDuration(250_000))
        self._elapsed_us = 0
        self._started_at: float | None = None

    def setBufferSize(self, value: int) -> None: self._buffer_size = int(value)
    def bufferSize(self) -> int: return self._buffer_size
    def start(self, device: QIODevice) -> None:
        if self._started_at is None: self._started_at = time.monotonic()
    def suspend(self) -> None:
        if self._started_at is not None:
            self._elapsed_us += round((time.monotonic() - self._started_at) * 1_000_000)
            self._started_at = None
    def resume(self) -> None:
        if self._started_at is None: self._started_at = time.monotonic()
    def stop(self) -> None:
        self._elapsed_us = 0
        self._started_at = None
    def processedUSecs(self) -> int:
        running = 0 if self._started_at is None else round((time.monotonic() - self._started_at) * 1_000_000)
        return self._elapsed_us + running


def headless_audio_requested() -> bool:
    """Return true for Qt platforms intentionally running without native output."""
    app = QGuiApplication.instance()
    return bool(app and app.platformName().lower() in {"offscreen", "minimal"})


def create_stem_transport(paths: dict[str, Path], parent=None):
    """Create a review transport without probing native audio in headless Qt."""
    sink_factory = NullAudioSink if headless_audio_requested() else QAudioSink
    return StemMixTransport(paths, parent, sink_factory=sink_factory)


class StemMixTransport(QObject):
    """GUI-thread audio transport with a stable playhead and one QAudioSink."""
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    playingChanged = Signal(bool)
    audioError = Signal(str)

    def __init__(self, paths: dict[str, Path], parent=None, sink_factory=QAudioSink,
                 *, output_device_provider=None, defer_output: bool | None = None):
        super().__init__(parent)
        self._paths = dict(paths)
        self._sink_factory = sink_factory
        self._output_device_provider = output_device_provider
        self._defer_output = sink_factory is QAudioSink if defer_output is None else defer_output
        self.output_device = None
        fmt = QAudioFormat(); fmt.setSampleRate(48000); fmt.setChannelCount(2); fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        self.device = StemMixDevice(paths, self, buffered=True, sample_format=fmt.sampleFormat())
        # A real Qt sink is deliberately deferred until Play. Merely opening a
        # project must never enumerate ALSA/PulseAudio/PipeWire devices.
        self.sink = None if self._defer_output else sink_factory(fmt, self)
        self.format = fmt
        self.buffer_duration_ms = 250
        if self.sink is not None: self._configure_sink()
        self.last_error = QAudio.Error.NoError
        self._playing = False; self._paused = False; self._anchor_frame = 0
        self.timer = QTimer(self); self.timer.setInterval(40); self.timer.timeout.connect(self._tick)
        self.durationChanged.emit(self.duration_ms)

    @property
    def duration_ms(self): return round(self.device.total_frames * 1000 / self.device.sample_rate)
    @property
    def position_ms(self):
        if (self._playing or self._paused) and self.sink is not None:
            return min(self.duration_ms, round(self._anchor_frame * 1000 / self.device.sample_rate + self.sink.processedUSecs() / 1000))
        return round(self._anchor_frame * 1000 / self.device.sample_rate)
    @property
    def is_playing(self): return self._playing

    def set_audible(self, ids): self.device.set_audible(tuple(ids))
    def set_peaks(self, peaks): self.device.set_peaks(peaks)
    def _configure_sink(self):
        self.sink.setBufferSize(round(self.format.bytesForDuration(self.buffer_duration_ms*1000)))
        self.device.configure_prefetch(self.sink.bufferSize())
        if hasattr(self.sink, "stateChanged"): self.sink.stateChanged.connect(self._sink_state_changed)
    def _ensure_sink(self) -> bool:
        if self.sink is not None: return True
        try:
            provider = self._output_device_provider or QMediaDevices.defaultAudioOutput
            output_device = provider()
            if output_device.isNull():
                raise RuntimeError("No audio output device is available.")
            fmt = QAudioFormat(); fmt.setSampleRate(48000); fmt.setChannelCount(2); fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
            if not output_device.isFormatSupported(fmt):
                fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
                if not output_device.isFormatSupported(fmt):
                    raise RuntimeError("No audio output device supports 48 kHz stereo playback.")
            if fmt.sampleFormat() != self.format.sampleFormat():
                position = self.position_ms; audible = self.device._audible; peaks = dict(self.device._peaks)
                self.device.close_sources()
                self.device = StemMixDevice(self._paths, self, buffered=True, sample_format=fmt.sampleFormat())
                self.device.set_peaks(peaks); self.device.set_audible(audible)
                self.device.seek_frame(round(position * self.device.sample_rate / 1000))
            self.output_device = output_device; self.format = fmt
            self.sink = self._sink_factory(output_device, fmt, self)
            self._configure_sink()
            return True
        except Exception as exc:
            message = str(exc) or "No audio output device is available."
            self.audioError.emit(message)
            return False
    def play_pause(self):
        if self._playing:
            self.sink.suspend(); self._playing = False; self._paused = True; self.timer.stop(); self.playingChanged.emit(False); self.positionChanged.emit(self.position_ms); return
        if not self._ensure_sink(): return
        if self._paused:
            self.sink.resume()
        else:
            self.device.wait_until_prefetched(); self.sink.start(self.device)
        self._playing = True; self._paused = False; self.timer.start(); self.playingChanged.emit(True)
    def stop(self):
        if self.sink is not None: self.sink.stop()
        self._playing = self._paused = False; self.timer.stop(); self.device.seek_frame(0); self._anchor_frame = 0
        self.playingChanged.emit(False); self.positionChanged.emit(0)
    def seek_ms(self, value):
        was_playing = self._playing
        if self.sink is not None: self.sink.stop()
        self.timer.stop(); self._playing = self._paused = False
        frame = round(max(0, min(self.duration_ms, int(value))) * self.device.sample_rate / 1000)
        self.device.seek_frame(frame); self._anchor_frame = frame
        if was_playing:
            self.device.wait_until_prefetched(); self.sink.start(self.device); self._playing = True; self.timer.start()
        else: self._paused = False
        self.playingChanged.emit(self._playing); self.positionChanged.emit(int(value))
    @Slot()
    def _tick(self):
        position = self.position_ms; self.positionChanged.emit(position)
        if position >= self.duration_ms: self.stop()
    @Slot(object)
    def _sink_state_changed(self, state):
        error = self.sink.error()
        self.last_error = error
        if error.value != QAudio.Error.NoError.value:
            self.audioError.emit(error.name)
    def close(self):
        if self.sink is not None: self.sink.stop()
        self.timer.stop(); self.device.close_sources()

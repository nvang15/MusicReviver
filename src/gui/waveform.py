"""Cached waveform envelopes and a reusable shared-playhead widget."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QWidget

@dataclass(frozen=True)
class WaveformEnvelope:
    low: np.ndarray
    high: np.ndarray
    frames: int
    sample_rate: int
    peak: float

def waveform_cache_key(path: Path, bins: int) -> str:
    stat = path.stat(); raw = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{bins}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]

def extract_waveform(path: Path, cache_directory: Path, bins: int = 1200) -> tuple[WaveformEnvelope, bool]:
    cache_directory.mkdir(parents=True, exist_ok=True); cache = cache_directory / f"{waveform_cache_key(path, bins)}.npz"
    if cache.is_file():
        with np.load(cache) as data:
            return WaveformEnvelope(data["low"], data["high"], int(data["frames"]), int(data["rate"]), float(data["peak"])), True
    info = sf.info(path); block = max(1, (info.frames + bins - 1) // bins); lows, highs, peak = [], [], 0.0
    with sf.SoundFile(path) as source:
        while True:
            audio = source.read(block, dtype="float32", always_2d=True)
            if not len(audio): break
            mono_low, mono_high = float(audio.min()), float(audio.max()); lows.append(mono_low); highs.append(mono_high)
            peak = max(peak, abs(mono_low), abs(mono_high))
    low, high = np.asarray(lows, dtype=np.float32), np.asarray(highs, dtype=np.float32)
    temporary = cache.with_suffix(".tmp.npz"); np.savez_compressed(temporary, low=low, high=high, frames=info.frames, rate=info.samplerate, peak=peak); temporary.replace(cache)
    return WaveformEnvelope(low, high, info.frames, info.samplerate, peak), False

def combine_envelopes(items: list[WaveformEnvelope]) -> WaveformEnvelope | None:
    if not items: return None
    size = min(len(item.low) for item in items); low = sum((item.low[:size] for item in items), np.zeros(size, np.float32)); high = sum((item.high[:size] for item in items), np.zeros(size, np.float32))
    peak = max(float(np.max(np.abs(low))), float(np.max(np.abs(high))), 1e-9); scale = min(1.0, .944060876 / peak)
    return WaveformEnvelope(low * scale, high * scale, min(i.frames for i in items), items[0].sample_rate, peak * scale)

class WaveformWidget(QWidget):
    seekRequested = Signal(int)
    def __init__(self, *, large=False, parent=None):
        super().__init__(parent); self.envelope = None; self.duration_ms = 0; self.position_ms = 0; self.dimmed = False; self.setMinimumHeight(100 if large else 44); self.setCursor(Qt.CursorShape.PointingHandCursor)
    def set_envelope(self, envelope): self.envelope = envelope; self.update()
    def set_duration(self, value): self.duration_ms = max(0, int(value)); self.update()
    def set_position(self, value): self.position_ms = max(0, int(value)); self.update()
    def _seek(self, x):
        if self.duration_ms and self.width(): self.seekRequested.emit(round(max(0, min(self.width(), x)) / self.width() * self.duration_ms))
    def mousePressEvent(self, event): self._seek(event.position().x())
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton: self._seek(event.position().x())
    def paintEvent(self, event):
        painter = QPainter(self); painter.fillRect(self.rect(), QColor("#25282c")); painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor("#41464d"), 1))
        for fraction in (0, .2, .4, .6, .8, 1):
            x = round(fraction * (self.width()-1)); painter.drawLine(x, 0, x, self.height())
        if self.envelope is not None and len(self.envelope.low):
            low, high = self.envelope.low, self.envelope.high; peak = max(float(np.max(np.abs(low))), float(np.max(np.abs(high))), 1e-6); mid = self.height()/2; scale = self.height()*.43/peak
            polygon = [QPointF(i*(self.width()-1)/max(1,len(high)-1), mid-high[i]*scale) for i in range(len(high))]
            polygon += [QPointF(i*(self.width()-1)/max(1,len(low)-1), mid-low[i]*scale) for i in range(len(low)-1,-1,-1)]
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor("#63313a" if self.dimmed else "#8f2337")); painter.drawPolygon(QPolygonF(polygon))
        if self.duration_ms:
            x = round(min(1, self.position_ms/self.duration_ms)*(self.width()-1)); painter.setPen(QPen(QColor("#e05570"), 2)); painter.drawLine(x, 0, x, self.height())

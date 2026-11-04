"""Measurement and aligned attenuation-only preview/group rendering."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import numpy as np
import soundfile as sf

CEILING = 10 ** (-0.5 / 20)

@dataclass(frozen=True)
class InactiveMeasurement:
    rms_dbfs: float
    peak_dbfs: float
    active_fraction: float
    likely_inactive: bool

@dataclass(frozen=True)
class MixRenderResult:
    path: Path
    attenuation_db: float
    cache_hit: bool = False

def measure_activity(path: Path) -> InactiveMeasurement:
    audio, _ = sf.read(path, dtype="float32", always_2d=True)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))) if audio.size else 0.0
    frame = 2400
    values = [float(np.sqrt(np.mean(np.square(audio[i:i+frame], dtype=np.float64))))
              for i in range(0, len(audio), frame)]
    active = sum(value > 10 ** (-55 / 20) for value in values) / max(1, len(values))
    db = lambda value: 20 * np.log10(max(value, 1e-12))
    # Conservative: both very low overall energy and little activity are required.
    return InactiveMeasurement(float(db(rms)), float(db(peak)), active, rms < 10**(-50/20) and active < .05)

def render_mix(paths: tuple[Path, ...], destination: Path, *, use_cache: bool = False) -> MixRenderResult:
    if not paths: raise ValueError("Choose at least one stem.")
    signature = hashlib.sha256("|".join(f"{p.resolve()}:{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in paths).encode()).hexdigest()[:16]
    target = destination / f"preview-{signature}.wav" if use_cache else destination
    if use_cache and target.is_file(): return MixRenderResult(target, 0.0, True)
    arrays, rates = [], set()
    for path in paths:
        audio, rate = sf.read(path, dtype="float32", always_2d=True); arrays.append(audio); rates.add(rate)
    if len(rates) != 1 or len({a.shape[1] for a in arrays}) != 1: raise ValueError("Stem audio dimensions do not match.")
    frames = max(len(a) for a in arrays)
    if max(len(a) for a in arrays) - min(len(a) for a in arrays) > 1: raise ValueError("Stem durations are not aligned.")
    mixed = np.zeros((frames, arrays[0].shape[1]), dtype=np.float64)
    for audio in arrays: mixed[:len(audio)] += audio
    peak = float(np.max(np.abs(mixed)))
    gain = min(1.0, CEILING / peak) if peak else 1.0
    attenuation = float(20 * np.log10(gain)) if gain < 1 else 0.0
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name("." + target.name + ".tmp.wav")
    sf.write(temporary, mixed * gain, rates.pop(), format="WAV", subtype="PCM_24")
    temporary.replace(target)
    return MixRenderResult(target, attenuation)

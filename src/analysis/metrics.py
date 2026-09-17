"""Numerically safe signal measurements and conservative estimates."""

from __future__ import annotations

import warnings as python_warnings

import librosa
import numpy as np
import pyloudnorm as pyln

BANDS: tuple[tuple[str, float, float], ...] = (
    ("sub", 20.0, 60.0),
    ("bass", 60.0, 250.0),
    ("low_mid", 250.0, 500.0),
    ("mid", 500.0, 2000.0),
    ("upper_mid", 2000.0, 6000.0),
    ("high", 6000.0, 12000.0),
    ("air", 12000.0, 20000.0),
)
EPSILON = np.finfo(np.float64).tiny
SILENCE_THRESHOLD_DBFS = -60.0
CLIPPING_THRESHOLD = 10.0 ** (-0.1 / 20.0)


def amplitude_to_db(value: float) -> float | None:
    """Convert a positive full-scale amplitude to dBFS."""
    return float(20.0 * np.log10(value)) if value > 0.0 and np.isfinite(value) else None


def mono_mix(audio: np.ndarray) -> np.ndarray:
    """Produce one mono working copy only for metrics that do not need stereo."""
    return np.mean(audio, axis=1, dtype=np.float64)


def frame_rms(mono: np.ndarray, sample_rate: int) -> np.ndarray:
    """Return 50 ms RMS frames at a 25 ms hop, padding very short audio."""
    frame_length = max(1, round(sample_rate * 0.050))
    hop = max(1, round(sample_rate * 0.025))
    if mono.size < frame_length:
        padded = np.pad(mono, (0, frame_length - mono.size))
        return np.array([np.sqrt(np.mean(np.square(padded), dtype=np.float64))])
    starts = np.arange(0, mono.size - frame_length + 1, hop)
    return np.array([
        np.sqrt(np.mean(np.square(mono[start:start + frame_length]), dtype=np.float64))
        for start in starts
    ])


def dynamic_and_noise_metrics(rms_frames: np.ndarray) -> tuple[float, float | None, float | None]:
    """Calculate silence, noise-floor estimate, and active-frame RMS range.

    Dynamic range is the 95th minus 10th percentile RMS level among frames above
    -60 dBFS. The estimated noise floor is the 10th percentile of non-silent frame
    levels; it is a conservative program-content estimate, not isolated noise.
    """
    db = np.full(rms_frames.shape, -np.inf, dtype=np.float64)
    positive = rms_frames > 0.0
    db[positive] = 20.0 * np.log10(rms_frames[positive])
    active = db > SILENCE_THRESHOLD_DBFS
    silence_fraction = float(1.0 - np.mean(active)) if db.size else 1.0
    active_db = db[active]
    if active_db.size == 0:
        return silence_fraction, None, None
    noise = float(np.percentile(active_db, 10.0))
    dynamic = float(np.percentile(active_db, 95.0) - np.percentile(active_db, 10.0))
    return silence_fraction, noise, dynamic


def spectral_metrics(mono: np.ndarray, sample_rate: int) -> tuple[float | None, float | None, float | None, dict[str, float]]:
    """Measure power-weighted spectrum summaries and normalized band energies."""
    empty_bands = {name: 0.0 for name, _, _ in BANDS}
    if mono.size == 0 or not np.any(mono):
        return None, None, None, empty_bands
    n_fft = min(4096, max(256, 2 ** int(np.floor(np.log2(max(256, mono.size))))))
    hop = n_fft // 2
    working = mono if mono.size >= n_fft else np.pad(mono, (0, n_fft - mono.size))
    starts = range(0, working.size - n_fft + 1, hop)
    power = np.zeros(n_fft // 2 + 1, dtype=np.float64)
    window = np.hanning(n_fft)
    frame_count = 0
    for start in starts:
        spectrum = np.fft.rfft(working[start:start + n_fft] * window)
        power += np.square(np.abs(spectrum))
        frame_count += 1
    power /= max(frame_count, 1)
    total = float(np.sum(power))
    if total <= EPSILON:
        return None, None, None, empty_bands
    frequencies = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    centroid = float(np.sum(frequencies * power) / total)
    bandwidth = float(np.sqrt(np.sum(np.square(frequencies - centroid) * power) / total))
    cumulative = np.cumsum(power)
    rolloff_index = min(int(np.searchsorted(cumulative, 0.85 * total)), frequencies.size - 1)
    rolloff = float(frequencies[rolloff_index])
    nyquist = sample_rate / 2.0
    band_energy: dict[str, float] = {}
    for name, low, high in BANDS:
        upper = min(high, nyquist)
        mask = (frequencies >= low) & (frequencies < upper) if upper > low else np.zeros_like(frequencies, dtype=bool)
        band_energy[name] = float(np.sum(power[mask]) / total)
    return centroid, bandwidth, rolloff, band_energy


def integrated_loudness(audio: np.ndarray, sample_rate: int) -> float | None:
    """Return BS.1770 integrated loudness when duration and signal permit it."""
    if audio.shape[0] / sample_rate < 0.4 or not np.any(audio):
        return None
    try:
        value = float(pyln.Meter(sample_rate).integrated_loudness(audio))
    except (ValueError, RuntimeError, ZeroDivisionError):
        return None
    return value if np.isfinite(value) else None


def estimate_tempo(mono: np.ndarray, sample_rate: int) -> float | None:
    """Estimate full-mix tempo with librosa's onset/beat tracker."""
    if mono.size / sample_rate < 2.0 or not np.any(mono):
        return None
    try:
        with python_warnings.catch_warnings():
            python_warnings.simplefilter("ignore")
            tempo, _ = librosa.beat.beat_track(y=mono, sr=sample_rate)
        value = float(np.asarray(tempo).reshape(-1)[0])
    except (ValueError, IndexError):
        return None
    return value if np.isfinite(value) and value > 0.0 else None


def estimate_key(mono: np.ndarray, sample_rate: int) -> tuple[str, str, float] | None:
    """Estimate key by correlating mean chroma with major/minor key profiles."""
    if mono.size / sample_rate < 1.0 or not np.any(mono):
        return None
    try:
        chroma = np.mean(librosa.feature.chroma_stft(y=mono, sr=sample_rate), axis=1)
    except ValueError:
        return None
    if not np.any(chroma) or not np.all(np.isfinite(chroma)):
        return None
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    candidates: list[tuple[float, int, str]] = []
    for tonic in range(12):
        for mode, profile in (("major", major), ("minor", minor)):
            correlation = float(np.corrcoef(chroma, np.roll(profile, tonic))[0, 1])
            if np.isfinite(correlation):
                candidates.append((correlation, tonic, mode))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    best, second = candidates[0], candidates[1]
    confidence = float(np.clip((best[0] - second[0]) / 0.25, 0.0, 1.0))
    return (("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")[best[1]], best[2], confidence)

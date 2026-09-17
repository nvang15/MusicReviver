"""Portable, deterministic mastering DSP."""

from __future__ import annotations

import numpy as np
from scipy.signal import sosfilt, sosfilt_zi


def broad_eq(audio: np.ndarray, sample_rate: int, *, frequency_hz: float,
             gain_db: float, q: float) -> np.ndarray:
    """Apply an RBJ peaking biquad; planner limits it to broad, low-gain cuts."""
    amplitude = 10.0 ** (gain_db / 40.0)
    omega = 2.0 * np.pi * frequency_hz / sample_rate
    alpha = np.sin(omega) / (2.0 * q)
    b = np.array([1 + alpha * amplitude, -2 * np.cos(omega), 1 - alpha * amplitude])
    a = np.array([1 + alpha / amplitude, -2 * np.cos(omega), 1 - alpha / amplitude])
    sos = np.array([[b[0] / a[0], b[1] / a[0], b[2] / a[0], 1.0, a[1] / a[0], a[2] / a[0]]])
    output = np.empty_like(audio, dtype=np.float64)
    for channel in range(audio.shape[1]):
        zi = sosfilt_zi(sos) * audio[0, channel]
        output[:, channel], _ = sosfilt(sos, audio[:, channel], zi=zi)
    return output


def linked_compressor(audio: np.ndarray, sample_rate: int, *, threshold_dbfs: float,
                      ratio: float, attack_ms: float, release_ms: float) -> np.ndarray:
    detector = np.max(np.abs(audio), axis=1)
    level_db = 20.0 * np.log10(np.maximum(detector, 1e-12))
    desired_db = np.minimum(0.0, (threshold_dbfs + (level_db - threshold_dbfs) / ratio) - level_db)
    attack = np.exp(-1.0 / max(1.0, sample_rate * attack_ms / 1000.0))
    release = np.exp(-1.0 / max(1.0, sample_rate * release_ms / 1000.0))
    smoothed = np.empty_like(desired_db)
    state = 0.0
    for index, target in enumerate(desired_db):
        coefficient = attack if target < state else release
        state = coefficient * state + (1.0 - coefficient) * target
        smoothed[index] = state
    return audio * (10.0 ** (smoothed / 20.0))[:, None]


def attenuation_peak_protection(audio: np.ndarray, ceiling_dbfs: float) -> tuple[np.ndarray, float]:
    """Apply global attenuation only, returning positive gain-reduction dB."""
    ceiling = 10.0 ** (ceiling_dbfs / 20.0)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= ceiling or peak == 0.0:
        return audio, 0.0
    gain = ceiling / peak
    return audio * gain, float(-20.0 * np.log10(gain))

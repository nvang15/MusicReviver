"""Objective mix and reference-comparison diagnostics."""

from __future__ import annotations

import numpy as np

from src.analysis.metrics import amplitude_to_db, integrated_loudness


def audio_metrics(audio: np.ndarray, sample_rate: int) -> dict[str, float | None]:
    """Return descriptive level metrics without applying normalization."""
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64))) if audio.size else 0.0
    return {
        "peak_amplitude": peak,
        "peak_dbfs": amplitude_to_db(peak),
        "rms": rms,
        "rms_dbfs": amplitude_to_db(rms),
        "integrated_lufs": integrated_loudness(audio, sample_rate),
    }


def reference_comparison(reference: np.ndarray, mix: np.ndarray) -> dict[str, float | None]:
    """Calculate objective similarity diagnostics without claiming perceptual quality."""
    ref_flat, mix_flat = reference.reshape(-1), mix.reshape(-1)
    ref_rms = float(np.sqrt(np.mean(np.square(ref_flat), dtype=np.float64)))
    mix_rms = float(np.sqrt(np.mean(np.square(mix_flat), dtype=np.float64)))
    correlation: float | None = None
    if float(np.std(ref_flat)) > 0.0 and float(np.std(mix_flat)) > 0.0:
        value = float(np.corrcoef(ref_flat, mix_flat)[0, 1])
        correlation = value if np.isfinite(value) else None
    denominator = float(np.mean(np.square(ref_flat), dtype=np.float64))
    nmse = float(np.mean(np.square(mix_flat - ref_flat), dtype=np.float64) / denominator) if denominator > 0.0 else None
    return {
        "reference_rms": ref_rms,
        "mix_rms": mix_rms,
        "rms_difference_db": (
            float(20.0 * np.log10(mix_rms / ref_rms)) if ref_rms > 0.0 and mix_rms > 0.0 else None
        ),
        "waveform_correlation": correlation,
        "normalized_mean_square_error": nmse,
    }

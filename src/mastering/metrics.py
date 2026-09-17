"""Mastering measurements built from the Milestone 4 metric primitives."""

from __future__ import annotations

import numpy as np

from src.analysis.metrics import (CLIPPING_THRESHOLD, amplitude_to_db,
                                  dynamic_and_noise_metrics, frame_rms,
                                  integrated_loudness, mono_mix, spectral_metrics)


def mastering_metrics(audio: np.ndarray, sample_rate: int) -> dict[str, object]:
    samples = np.asarray(audio, dtype=np.float64)
    absolute = np.abs(samples)
    peak = float(np.max(absolute)) if samples.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64))) if samples.size else 0.0
    peak_db = amplitude_to_db(peak)
    rms_db = amplitude_to_db(rms)
    mono = mono_mix(samples)
    _, _, dynamic = dynamic_and_noise_metrics(frame_rms(mono, sample_rate))
    _, _, _, bands = spectral_metrics(mono, sample_rate)
    correlation = None
    if samples.shape[1] == 2 and np.std(samples[:, 0]) > 0 and np.std(samples[:, 1]) > 0:
        candidate = float(np.corrcoef(samples[:, 0], samples[:, 1])[0, 1])
        correlation = float(np.clip(candidate, -1.0, 1.0)) if np.isfinite(candidate) else None
    return {
        "integrated_lufs": integrated_loudness(samples, sample_rate),
        "peak_amplitude": peak, "peak_dbfs": peak_db, "peak_measurement": "sample_peak",
        "rms": rms, "rms_dbfs": rms_db,
        "crest_factor_db": peak_db - rms_db if peak_db is not None and rms_db is not None else None,
        "dynamic_range_estimate_db": dynamic,
        "band_energy_fractions": bands,
        "clipped_sample_count": int(np.count_nonzero(absolute >= CLIPPING_THRESHOLD)),
        "stereo_correlation": correlation,
    }

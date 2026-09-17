"""Reusable analysis of one local WAV without modifying its samples."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from src.analysis.exceptions import AnalysisError, UnsupportedAnalysisInputError
from src.analysis.metrics import (
    CLIPPING_THRESHOLD,
    amplitude_to_db,
    dynamic_and_noise_metrics,
    estimate_key,
    estimate_tempo,
    frame_rms,
    integrated_loudness,
    mono_mix,
    spectral_metrics,
)
from src.analysis.models import AudioAnalysis, KeyEstimate


def analyze_audio(path: Path, *, logical_name: str, full_mix: bool = False) -> AudioAnalysis:
    """Measure one WAV file; tempo and key estimates are full-mix-only."""
    path = Path(path)
    if path.suffix.lower() != ".wav":
        raise UnsupportedAnalysisInputError(f"Analysis requires a WAV file: {path.name}")
    try:
        info = sf.info(path)
        if info.format not in {"WAV", "WAVEX"}:
            raise UnsupportedAnalysisInputError(f"Unsupported audio container: {info.format}")
        audio, sample_rate = sf.read(path, dtype="float64", always_2d=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise UnsupportedAnalysisInputError(f"Could not read WAV '{path.name}': {exc}") from exc
    if audio.size == 0 or audio.shape[0] == 0:
        raise AnalysisError(f"Audio contains no samples: {path.name}")
    if not np.all(np.isfinite(audio)):
        raise AnalysisError(f"Audio contains NaN or infinite samples: {path.name}")

    samples = audio.astype(np.float64, copy=False)
    mono = mono_mix(samples)
    absolute = np.abs(samples)
    peak = float(np.max(absolute))
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    peak_dbfs = amplitude_to_db(peak)
    rms_dbfs = amplitude_to_db(rms)
    crest = float(peak_dbfs - rms_dbfs) if peak_dbfs is not None and rms_dbfs is not None else None
    frames = frame_rms(mono, sample_rate)
    silence_fraction, noise_floor, dynamic_range = dynamic_and_noise_metrics(frames)
    centroid, bandwidth, rolloff, band_energy = spectral_metrics(mono, sample_rate)
    loudness = integrated_loudness(samples, sample_rate)
    clipped_count = int(np.count_nonzero(absolute >= CLIPPING_THRESHOLD))

    warnings: list[str] = [
        "noise_floor_estimate: low-level program frames may contain music as well as noise"
    ]
    if loudness is None:
        warnings.append("loudness_unavailable: audio is silent or too short for reliable integrated loudness")
    if dynamic_range is None:
        warnings.append("dynamic_range_unavailable: no frames exceed the -60 dBFS active threshold")

    correlation: float | None = None
    balance: float | None = None
    if samples.shape[1] >= 2:
        left, right = samples[:, 0], samples[:, 1]
        left_std, right_std = float(np.std(left)), float(np.std(right))
        if left_std > 0.0 and right_std > 0.0:
            value = float(np.corrcoef(left, right)[0, 1])
            correlation = float(np.clip(value, -1.0, 1.0)) if np.isfinite(value) else None
        else:
            warnings.append("stereo_correlation_unavailable: one or both channels are constant")
        left_rms = float(np.sqrt(np.mean(np.square(left))))
        right_rms = float(np.sqrt(np.mean(np.square(right))))
        if left_rms > 0.0 and right_rms > 0.0:
            balance = float(20.0 * np.log10(left_rms / right_rms))
    else:
        warnings.append("stereo_correlation_unavailable: mono audio has no channel correlation")

    tempo: float | None = None
    key: KeyEstimate | None = None
    if full_mix:
        tempo = estimate_tempo(mono, sample_rate)
        if tempo is None:
            warnings.append("tempo_unavailable: insufficient reliable rhythmic information")
        else:
            warnings.append("tempo_estimate: BPM is an estimate, not ground truth")
        key_data = estimate_key(mono, sample_rate)
        if key_data is None:
            warnings.append("key_unavailable: insufficient reliable tonal information")
        else:
            key = KeyEstimate(*key_data)
            warnings.append("key_estimate: chroma/profile result is experimental")
            if key.confidence < 0.20:
                warnings.append("key_confidence_low: estimated key is uncertain")

    return AudioAnalysis(
        filename=path.name,
        logical_name=logical_name,
        duration_seconds=float(info.frames / sample_rate),
        sample_rate=int(sample_rate),
        channels=int(samples.shape[1]),
        frames=int(info.frames),
        peak_amplitude=peak,
        peak_dbfs=peak_dbfs,
        rms=rms,
        rms_dbfs=rms_dbfs,
        dc_offset=float(np.mean(samples)),
        crest_factor_db=crest,
        integrated_lufs=loudness,
        dynamic_range_estimate_db=dynamic_range,
        spectral_centroid_hz=centroid,
        spectral_bandwidth_hz=bandwidth,
        spectral_rolloff_hz=rolloff,
        band_energy_fractions=band_energy,
        silence_fraction=silence_fraction,
        estimated_noise_floor_dbfs=noise_floor,
        clipped_sample_count=clipped_count,
        clipped_sample_fraction=float(clipped_count / samples.size),
        stereo_correlation=correlation,
        stereo_balance_db=balance,
        tempo_bpm=tempo,
        key_estimate=key,
        warnings=warnings,
    )

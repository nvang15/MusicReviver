"""Typed, JSON-safe audio-analysis result models."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class KeyEstimate:
    """Experimental chroma/profile key estimate, not musical ground truth."""

    tonic: str
    mode: str
    confidence: float


@dataclass(frozen=True)
class AudioAnalysis:
    """Objective measurements and explicitly labeled estimates for one WAV file."""

    filename: str
    logical_name: str
    duration_seconds: float
    sample_rate: int
    channels: int
    frames: int
    peak_amplitude: float
    peak_dbfs: float | None
    rms: float
    rms_dbfs: float | None
    dc_offset: float
    crest_factor_db: float | None
    integrated_lufs: float | None
    dynamic_range_estimate_db: float | None
    spectral_centroid_hz: float | None
    spectral_bandwidth_hz: float | None
    spectral_rolloff_hz: float | None
    band_energy_fractions: dict[str, float]
    silence_fraction: float
    estimated_noise_floor_dbfs: float | None
    clipped_sample_count: int
    clipped_sample_fraction: float
    stereo_correlation: float | None
    stereo_balance_db: float | None
    tempo_bpm: float | None = None
    key_estimate: KeyEstimate | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return standard-JSON-safe data, replacing non-finite floats with null."""
        return _finite_json(asdict(self))


def _finite_json(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _finite_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite_json(item) for item in value]
    return value

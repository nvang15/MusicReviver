"""Conservative thresholds and maximum correction amounts by strength."""

from __future__ import annotations

from dataclasses import dataclass

from src.restoration.models import RestorationStrength


@dataclass(frozen=True)
class RestorationPreset:
    dc_offset_threshold: float
    sub_energy_threshold: float
    compression_dynamic_range_threshold_db: float
    compression_crest_threshold_db: float
    compression_ratio: float
    high_pass_frequencies: dict[str, float]


PRESETS = {
    RestorationStrength.LIGHT: RestorationPreset(
        0.005, 0.08, 20.0, 14.0, 1.25,
        {"vocals": 50.0, "guitar": 35.0, "piano": 22.0, "electric_piano": 22.0,
         "bass": 18.0, "drums": 18.0, "other": 18.0, "instrumental": 18.0},
    ),
    RestorationStrength.BALANCED: RestorationPreset(
        0.002, 0.05, 16.0, 12.0, 1.40,
        {"vocals": 60.0, "guitar": 45.0, "piano": 28.0, "electric_piano": 28.0,
         "bass": 22.0, "drums": 22.0, "other": 22.0, "instrumental": 22.0},
    ),
    RestorationStrength.STRONG: RestorationPreset(
        0.001, 0.03, 13.0, 10.0, 1.60,
        {"vocals": 70.0, "guitar": 55.0, "piano": 35.0, "electric_piano": 35.0,
         "bass": 25.0, "drums": 25.0, "other": 25.0, "instrumental": 25.0},
    ),
}


def get_preset(strength: RestorationStrength) -> RestorationPreset:
    return PRESETS[strength]

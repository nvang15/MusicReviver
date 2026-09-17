"""Typed mastering decisions and results."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class MasteringMode(str, Enum):
    ARCHIVAL = "archival"
    BALANCED = "balanced"
    MODERN = "modern"


@dataclass(frozen=True)
class ModePolicy:
    loudness_range_lufs: tuple[float, float]
    peak_ceiling_dbfs: float
    max_gain_boost_db: float
    max_eq_gain_db: float
    max_compression_ratio: float
    compression_threshold_crest_db: float
    compression_threshold_dynamic_db: float
    max_planned_limiting_db: float


@dataclass(frozen=True)
class MasteringAction:
    type: str
    parameters: dict[str, float | str | bool]
    reason: str


@dataclass(frozen=True)
class MasteringWarning:
    code: str
    message: str


@dataclass(frozen=True)
class MasteringPlan:
    mode: MasteringMode
    source_file: Path
    source_metrics: dict[str, Any]
    actions: tuple[MasteringAction, ...]
    target_loudness_range_lufs: tuple[float, float]
    peak_ceiling_dbfs: float
    warnings: tuple[MasteringWarning, ...]
    reasoning: tuple[str, ...]
    bypass_eq: bool
    bypass_compression: bool
    bypass_gain: bool

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class MasteringResult:
    plan: MasteringPlan
    audio_path: Path
    metadata_path: Path
    text_path: Path
    peak_protection_gain_reduction_db: float
    processing_duration: float
    output_metrics: dict[str, Any]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value

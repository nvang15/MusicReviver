"""Typed plans, warnings, settings, and structured mix results."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class MixSource(str, Enum):
    AUTO = "auto"
    RESTORED = "restored"
    SEPARATED = "separated"


@dataclass(frozen=True)
class MixWarning:
    code: str
    message: str


@dataclass(frozen=True)
class StemMixSetting:
    stem: str
    gain_db: float
    reason: str

    @property
    def linear_gain(self) -> float:
        return 10.0 ** (self.gain_db / 20.0)


@dataclass(frozen=True)
class MixPlan:
    stem_source: MixSource
    stems: tuple[str, ...]
    settings: tuple[StemMixSetting, ...]
    gain_estimation_method: str
    reference_fitting_succeeded: bool
    warnings: tuple[MixWarning, ...] = ()
    unity_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class MixResult:
    plan: MixPlan
    audio_path: Path
    metadata_path: Path
    text_path: Path
    safety_gain_db: float
    processing_duration: float


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value

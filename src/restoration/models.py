"""Typed, machine-readable restoration plans and warnings."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RestorationStrength(str, Enum):
    LIGHT = "light"
    BALANCED = "balanced"
    STRONG = "strong"


@dataclass(frozen=True)
class RestorationAction:
    type: str
    parameters: dict[str, float]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class RestorationWarning:
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class RestorationPlan:
    target_name: str
    target_type: str
    restoration_strength: RestorationStrength
    actions: tuple[RestorationAction, ...] = ()
    warnings: tuple[RestorationWarning, ...] = ()
    reasoning: tuple[str, ...] = ()
    bypass: bool = True
    source_analysis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


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

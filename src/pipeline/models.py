"""Typed pipeline configuration, states, records, and results."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.mastering.models import MasteringMode
from src.restoration.models import RestorationStrength
from src.separation.backends import DeviceMode
from src.separation.models import DEFAULT_MODEL_ID


class PipelineStage(str, Enum):
    IMPORT = "import"
    SEPARATION = "separation"
    ANALYSIS = "analysis"
    RESTORATION = "restoration"
    MIXING = "mixing"
    MASTERING = "mastering"
    COMPLETE = "complete"


class PipelineStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    REUSED = "reused"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PipelineConfig:
    separation_model: str = DEFAULT_MODEL_ID
    device_mode: DeviceMode = DeviceMode.AUTO
    restoration_strength: RestorationStrength = RestorationStrength.BALANCED
    mastering_mode: MasteringMode = MasteringMode.BALANCED
    force: bool = False
    resume: bool = True
    requested_outputs: tuple[str, ...] = ()
    keep_intermediates: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass
class StageRecord:
    stage: PipelineStage
    status: PipelineStatus = PipelineStatus.PENDING
    duration_seconds: float = 0.0
    fingerprint: str | None = None
    outputs: list[str] = field(default_factory=list)
    message: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class PipelineResult:
    project_name: str
    original_input: Path
    standardized_source_path: Path | None
    separated_stems: dict[str, Path]
    analysis_reports: tuple[Path, ...]
    restored_stems: dict[str, Path]
    mixed_output: Path | None
    mastered_output: Path | None
    warnings: tuple[str, ...]
    stage_records: dict[PipelineStage, StageRecord]
    total_duration: float
    reused_stages: tuple[PipelineStage, ...]
    failed_stage: PipelineStage | None
    pipeline_json: Path
    pipeline_text: Path


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key.value if isinstance(key, Enum) else key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value

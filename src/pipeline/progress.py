"""GUI-neutral pipeline progress events."""

from __future__ import annotations

from dataclasses import dataclass

from src.pipeline.models import PipelineStage, PipelineStatus


@dataclass(frozen=True)
class PipelineProgress:
    stage: PipelineStage
    status: PipelineStatus
    message: str
    progress_fraction: float | None
    elapsed_seconds: float

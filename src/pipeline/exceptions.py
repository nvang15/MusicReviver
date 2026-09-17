"""Pipeline orchestration errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.pipeline.models import PipelineResult


class PipelineError(RuntimeError):
    """A stage failed during orchestration."""

    def __init__(self, message: str, *, result: "PipelineResult | None" = None) -> None:
        super().__init__(message)
        self.result = result


class PipelineCancelled(PipelineError):
    """Cancellation was requested between stages."""

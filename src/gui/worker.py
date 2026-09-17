"""Background execution bridge from Qt signals to backend APIs."""

from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from src.analysis.report import analyze_project
from src.audio.converter import safe_project_name
from src.config import OUTPUT_DIR
from src.gui.models import GuiJobConfig, GuiResult, GuiTask
from src.pipeline.exceptions import PipelineCancelled
from src.pipeline.models import PipelineConfig, PipelineStage, PipelineStatus
from src.pipeline.orchestrator import modernize
from src.pipeline.progress import PipelineProgress
from src.restoration.processor import restore_project
from src.separation.separator import prepare_separation, separate


class ProcessingWorker(QObject):
    """Execute one GUI job off the UI thread and emit thread-safe updates."""

    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str)
    finished = Signal()

    def __init__(self, config: GuiJobConfig,
                 runner: Callable[[GuiJobConfig, Callable[[PipelineProgress], None], threading.Event], GuiResult] | None = None) -> None:
        super().__init__()
        self.config = config
        self._cancel_event = threading.Event()
        self._runner = runner or run_gui_job

    def request_cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = self._runner(self.config, self.progress.emit, self._cancel_event)
        except PipelineCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__, traceback.format_exc())
        else:
            self.completed.emit(result)
        finally:
            self.finished.emit()


def _event(stage: PipelineStage, status: PipelineStatus, message: str,
           started: float) -> PipelineProgress:
    return PipelineProgress(stage, status, message, None, time.perf_counter() - started)


def run_gui_job(config: GuiJobConfig, callback: Callable[[PipelineProgress], None],
                cancel_event: threading.Event) -> GuiResult:
    """Dispatch to existing backend APIs; no stage processing is implemented here."""
    started = time.perf_counter()
    project_name = safe_project_name(config.input_path)
    project = OUTPUT_DIR / project_name
    if config.task is GuiTask.MODERNIZE:
        result = modernize(config.input_path, config=PipelineConfig(
            separation_model=config.separation_model, device_mode=config.device_mode,
            restoration_strength=config.restoration_strength,
            mastering_mode=config.mastering_mode, force=config.force,
        ), progress_callback=callback, cancellation_token=cancel_event)
        files = tuple([*result.separated_stems.values(), *result.analysis_reports,
                       *result.restored_stems.values(), *([result.mixed_output] if result.mixed_output else []),
                       *([result.mastered_output] if result.mastered_output else [])])
        return GuiResult(config.task, result.project_name, result.total_duration,
                         result.mastered_output, files, result.mastered_output.parent if result.mastered_output else project,
                         "Modernization completed.")
    stage = {GuiTask.SEPARATE: PipelineStage.SEPARATION,
             GuiTask.ANALYZE: PipelineStage.ANALYSIS,
             GuiTask.RESTORE: PipelineStage.RESTORATION}[config.task]
    if cancel_event.is_set():
        raise PipelineCancelled(f"Cancelled before {stage.value}.")
    callback(_event(stage, PipelineStatus.RUNNING, f"Running {stage.value}.", started))
    if config.task is GuiTask.SEPARATE:
        request = prepare_separation(config.input_path, model_id=config.separation_model,
                                     device=config.device_mode, force=config.force)
        value = separate(request)
        files = tuple(value.stems.values())
        primary, folder = None, value.stems_directory
    elif config.task is GuiTask.ANALYZE:
        _, json_path, text_path = analyze_project(config.input_path, force=config.force)
        files, primary, folder = (json_path, text_path), json_path, json_path.parent
    else:
        document, json_path, text_path = restore_project(
            config.input_path, strength=config.restoration_strength, force=config.force)
        files = tuple(Path(item["output"]) if Path(item["output"]).is_absolute()
                      else Path.cwd() / item["output"] for item in document["results"].values())
        files = (*files, json_path, text_path)
        primary, folder = None, json_path.parent
    elapsed = time.perf_counter() - started
    callback(_event(stage, PipelineStatus.COMPLETED, f"{stage.value.title()} completed.", started))
    return GuiResult(config.task, project_name, elapsed, primary, tuple(files), folder,
                     f"{stage.value.title()} completed.")

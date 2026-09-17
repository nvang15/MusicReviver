"""GUI-only task configuration, result presentation, and safe export helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.audio.metadata import SUPPORTED_EXTENSIONS
from src.mastering.models import MasteringMode
from src.restoration.models import RestorationStrength
from src.separation.backends import DeviceMode
from src.separation.models import DEFAULT_MODEL_ID, MODEL_REGISTRY


class GuiTask(str, Enum):
    SEPARATE = "separate"
    ANALYZE = "analyze"
    RESTORE = "restore"
    MODERNIZE = "modernize"


@dataclass(frozen=True)
class GuiJobConfig:
    input_path: Path
    task: GuiTask = GuiTask.MODERNIZE
    separation_model: str = DEFAULT_MODEL_ID
    device_mode: DeviceMode = DeviceMode.AUTO
    restoration_strength: RestorationStrength = RestorationStrength.BALANCED
    mastering_mode: MasteringMode = MasteringMode.BALANCED
    force: bool = False

    def validate(self) -> str | None:
        if not self.input_path.is_file():
            return "Choose an existing audio or video file."
        if self.input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return "This file type is not supported by MusicReviver."
        if self.separation_model not in MODEL_REGISTRY:
            return "The selected separation model is not registered."
        return None


@dataclass(frozen=True)
class GuiResult:
    task: GuiTask
    project_name: str
    elapsed_seconds: float
    primary_output: Path | None
    files: tuple[Path, ...]
    output_folder: Path | None
    summary: str


def unique_destination(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    source = Path(filename)
    counter = 2
    while True:
        candidate = directory / f"{source.stem}_{counter}{source.suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def export_files(files: tuple[Path, ...], destination: Path) -> tuple[Path, ...]:
    """Copy generated files without silently replacing user data."""
    destination.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    for source in files:
        if not source.is_file():
            continue
        target = unique_destination(destination, source.name)
        shutil.copy2(source, target)
        exported.append(target)
    return tuple(exported)

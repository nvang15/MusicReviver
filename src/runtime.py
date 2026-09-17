"""Centralized source and frozen-application runtime locations and tools."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class RuntimeDependencyError(RuntimeError):
    """A required external runtime executable could not be resolved."""


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    input: Path
    output: Path
    models: Path
    temp: Path
    bin: Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def application_root(*, frozen: bool | None = None, executable: Path | None = None,
                     source_file: Path | None = None) -> Path:
    """Return the external writable root, never PyInstaller's temporary bundle."""
    frozen = is_frozen() if frozen is None else frozen
    if frozen:
        return Path(executable or sys.executable).resolve().parent
    marker = Path(source_file or __file__).resolve()
    return marker.parent.parent


def runtime_paths(**kwargs) -> RuntimePaths:
    root = application_root(**kwargs)
    return RuntimePaths(root, root / "input", root / "output", root / "models",
                        root / "temp", root / "bin")


def ensure_runtime_directories(paths: RuntimePaths | None = None) -> RuntimePaths:
    paths = paths or runtime_paths()
    for directory in (paths.input, paths.output, paths.models, paths.temp):
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def resolve_executable(name: str, *, paths: RuntimePaths | None = None,
                       which: Callable[[str], str | None] | None = None) -> str:
    """Prefer a packaged bin executable, then fall back to PATH."""
    paths = paths or runtime_paths()
    candidates = (paths.bin / f"{name}.exe", paths.bin / name)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    discovered = (which or shutil.which)(name)
    if discovered:
        return discovered
    raise RuntimeDependencyError(
        f"{name} was not found. Packaged builds require '{candidate.name}' in "
        f"{paths.bin}, or {name} must be available on PATH."
    )


def configure_bundled_tools_path(paths: RuntimePaths | None = None) -> None:
    """Expose packaged tools to libraries that internally resolve command names."""
    paths = paths or runtime_paths()
    if is_frozen() and paths.bin.is_dir():
        current = os.environ.get("PATH", "")
        entries = current.split(os.pathsep) if current else []
        if str(paths.bin) not in entries:
            os.environ["PATH"] = str(paths.bin) + (os.pathsep + current if current else "")

"""MusicReviver Milestone 1 environment validation entry point."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.config import PROJECT_DIRECTORIES
from src.audio.converter import is_ffmpeg_available, is_ffprobe_available


@dataclass(frozen=True)
class CheckResult:
    """The display name and outcome of one environment check."""

    name: str
    passed: bool
    error: str | None = None


def check_python_version() -> CheckResult:
    """Confirm that the interpreter is the supported Python 3.11 release."""
    version = sys.version_info
    passed = version.major == 3 and version.minor == 11
    error = None if passed else f"Found Python {version.major}.{version.minor}; Python 3.11 is required."
    return CheckResult("Python 3.11", passed, error)


def check_project_directories(
    directories: tuple[Path, ...] = PROJECT_DIRECTORIES,
) -> CheckResult:
    """Confirm that each required project directory exists."""
    missing = [directory.name for directory in directories if not directory.is_dir()]
    error = None if not missing else f"Missing directories: {', '.join(missing)}."
    return CheckResult("Project directories", not missing, error)


def _tool_check(name: str, detector: Callable[[], bool], install_hint: str) -> CheckResult:
    available = detector()
    error = None if available else f"{name} was not found on PATH. {install_hint}"
    return CheckResult(name, available, error)


def run_environment_checks() -> tuple[CheckResult, ...]:
    """Run all startup checks without raising for expected missing tools."""
    return (
        check_python_version(),
        _tool_check("FFmpeg", is_ffmpeg_available, "Install FFmpeg and add its bin directory to PATH."),
        _tool_check("FFprobe", is_ffprobe_available, "FFprobe is normally included with FFmpeg."),
        check_project_directories(),
    )


def main() -> int:
    """Print a concise environment report and return a process status code."""
    results = run_environment_checks()
    print("MusicReviver Environment Check\n")
    for result in results:
        print(f"{result.name}: {'PASS' if result.passed else 'FAIL'}")

    failures = [result for result in results if not result.passed]
    if failures:
        print("\nAction required:")
        for failure in failures:
            print(f"- {failure.error}")
        return 1

    print("\nEnvironment is ready for MusicReviver Milestone 1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

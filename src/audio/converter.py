"""Detection helpers for external media conversion tools."""

from __future__ import annotations

import shutil


def is_executable_available(executable: str) -> bool:
    """Return whether an executable can be resolved from the current PATH."""
    return shutil.which(executable) is not None


def is_ffmpeg_available() -> bool:
    """Return whether FFmpeg is available on PATH."""
    return is_executable_available("ffmpeg")


def is_ffprobe_available() -> bool:
    """Return whether FFprobe is available on PATH."""
    return is_executable_available("ffprobe")

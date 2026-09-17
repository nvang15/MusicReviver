"""Filesystem helpers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def ensure_directories(directories: Iterable[Path]) -> None:
    """Create directories and their parents safely and idempotently."""
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

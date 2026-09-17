"""Project paths and directory initialization."""

from src.utils.paths import ensure_directories
from src.runtime import runtime_paths

_RUNTIME = runtime_paths()
PROJECT_ROOT = _RUNTIME.root
INPUT_DIR = _RUNTIME.input
OUTPUT_DIR = _RUNTIME.output
MODEL_DIR = _RUNTIME.models
TEMP_DIR = _RUNTIME.temp

PROJECT_DIRECTORIES = (INPUT_DIR, OUTPUT_DIR, MODEL_DIR, TEMP_DIR)


def initialize_project_directories() -> None:
    """Create runtime directories if they do not already exist."""
    ensure_directories(PROJECT_DIRECTORIES)

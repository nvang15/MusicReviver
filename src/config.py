"""Project paths and directory initialization."""

from pathlib import Path

from src.utils.paths import ensure_directories

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"
MODEL_DIR = PROJECT_ROOT / "models"
TEMP_DIR = PROJECT_ROOT / "temp"

PROJECT_DIRECTORIES = (INPUT_DIR, OUTPUT_DIR, MODEL_DIR, TEMP_DIR)


def initialize_project_directories() -> None:
    """Create runtime directories if they do not already exist."""
    ensure_directories(PROJECT_DIRECTORIES)

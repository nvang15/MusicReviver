from pathlib import Path

from src import config
from src.utils.paths import ensure_directories


def test_project_paths_are_rooted_in_repository() -> None:
    assert config.PROJECT_ROOT == Path(__file__).resolve().parents[1]
    assert config.INPUT_DIR == config.PROJECT_ROOT / "input"
    assert config.OUTPUT_DIR == config.PROJECT_ROOT / "output"
    assert config.MODEL_DIR == config.PROJECT_ROOT / "models"
    assert config.TEMP_DIR == config.PROJECT_ROOT / "temp"


def test_ensure_directories_creates_nested_directories(tmp_path: Path) -> None:
    targets = (tmp_path / "one", tmp_path / "nested" / "two")
    ensure_directories(targets)
    ensure_directories(targets)
    assert all(target.is_dir() for target in targets)

import importlib.util
from pathlib import Path

import pytest

from src.runtime import (RuntimeDependencyError, RuntimePaths, application_root,
                         ensure_runtime_directories, resolve_executable, runtime_paths)


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "packaging" / "build_windows.py"
SPEC = ROOT / "packaging" / "MusicReviver.spec"


def load_build_module():
    spec = importlib.util.spec_from_file_location("musicreviver_build_windows", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Dataclasses expect their module to be registered during class creation.
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def paths(root: Path) -> RuntimePaths:
    return RuntimePaths(root, root / "input", root / "output", root / "models",
                        root / "temp", root / "bin")


def test_source_runtime_directory_resolution() -> None:
    marker = ROOT / "src" / "runtime.py"
    assert application_root(frozen=False, source_file=marker) == ROOT


def test_simulated_frozen_runtime_uses_executable_directory_not_meipass(tmp_path: Path,
                                                                       monkeypatch) -> None:
    executable = tmp_path / "installed" / "MusicReviver.exe"
    fake_meipass = tmp_path / "_MEI12345"
    monkeypatch.setattr("src.runtime.sys._MEIPASS", str(fake_meipass), raising=False)
    resolved = runtime_paths(frozen=True, executable=executable)
    assert resolved.root == executable.parent.resolve()
    assert fake_meipass not in resolved.output.parents and resolved.output != fake_meipass


def test_packaged_bin_ffmpeg_resolution_precedes_path(tmp_path: Path) -> None:
    runtime = paths(tmp_path)
    runtime.bin.mkdir()
    bundled = runtime.bin / "ffmpeg.exe"
    bundled.write_bytes(b"binary")
    assert resolve_executable("ffmpeg", paths=runtime, which=lambda name: "PATH-ffmpeg") == str(bundled)


def test_path_ffmpeg_fallback_and_clear_missing_error(tmp_path: Path) -> None:
    runtime = paths(tmp_path)
    assert resolve_executable("ffmpeg", paths=runtime, which=lambda name: "C:/tools/ffmpeg.exe") == "C:/tools/ffmpeg.exe"
    with pytest.raises(RuntimeDependencyError, match="ffmpeg was not found"):
        resolve_executable("ffmpeg", paths=runtime, which=lambda name: None)


def test_writable_runtime_directories_and_external_model_cache(tmp_path: Path) -> None:
    runtime = ensure_runtime_directories(paths(tmp_path / "application"))
    assert all(directory.is_dir() for directory in (runtime.input, runtime.output, runtime.models, runtime.temp))
    assert runtime.models == runtime.root / "models"


def test_build_argument_parsing_and_console_modes() -> None:
    module = load_build_module()
    defaults = module.parse_args([])
    assert not defaults.clean and not defaults.debug and not defaults.include_model_cache
    selected = module.parse_args(["--clean", "--debug", "--include-model-cache"])
    assert selected.clean and selected.debug and selected.include_model_cache
    assert module.build_environment(defaults)["MUSICREVIVER_BUILD_DEBUG"] == "0"
    assert module.build_environment(selected)["MUSICREVIVER_BUILD_DEBUG"] == "1"


def test_distribution_never_copies_user_runtime_data_by_default(tmp_path: Path,
                                                                monkeypatch) -> None:
    module = load_build_module()
    project = tmp_path / "project"
    for name in ("input", "output", "temp", "models"):
        directory = project / name
        directory.mkdir(parents=True)
        (directory / f"private-{name}.dat").write_bytes(b"private")
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        (tools / name).write_bytes(name.encode())
    distribution = tmp_path / "dist" / "MusicReviver"
    distribution.mkdir(parents=True)
    monkeypatch.setattr(module, "PROJECT_ROOT", project)
    module.prepare_distribution(distribution, tools)
    assert not any((distribution / name / f"private-{name}.dat").exists()
                   for name in ("input", "output", "temp", "models"))
    assert (distribution / "bin" / "ffmpeg.exe").is_file()


def test_model_cache_copy_requires_explicit_option(tmp_path: Path, monkeypatch) -> None:
    module = load_build_module()
    project = tmp_path / "project"
    (project / "models").mkdir(parents=True)
    (project / "models" / "cached.onnx").write_bytes(b"model")
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        (tools / name).write_bytes(b"tool")
    monkeypatch.setattr(module, "PROJECT_ROOT", project)
    first = tmp_path / "first"
    first.mkdir()
    module.prepare_distribution(first, tools, include_model_cache=False)
    assert not (first / "models" / "cached.onnx").exists()
    second = tmp_path / "second"
    second.mkdir()
    module.prepare_distribution(second, tools, include_model_cache=True)
    assert (second / "models" / "cached.onnx").read_bytes() == b"model"


def test_canonical_spec_exists_and_declares_onedir_windowed_release() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert SPEC.is_file()
    assert "COLLECT(" in text
    assert "console=debug_build" in text
    assert 'MUSICREVIVER_BUILD_DEBUG' in text
    assert 'hiddenimports=["audio_separator.separator"]' in text


def test_packaging_module_import_does_not_start_build(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: calls.append(args))
    module = load_build_module()
    assert module.SPEC_PATH == SPEC
    assert calls == []

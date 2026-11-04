"""Regression for windowed Demucs/tqdm stderr access; no AI inference."""
import io
import sys
import traceback
from pathlib import Path

import pytest

from src.runtime import initialize_standard_streams, runtime_paths


def test_missing_streams_support_real_tqdm_and_tracebacks(tmp_path, monkeypatch):
    from tqdm import tqdm
    paths = runtime_paths(frozen=True, executable=tmp_path / "MusicReviver.exe")
    with monkeypatch.context() as patch:
        patch.setattr(sys, "frozen", True, raising=False)
        patch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
        patch.setattr(sys, "stdout", None)
        patch.setattr(sys, "stderr", None)
        initialize_standard_streams(paths)
        stdout, stderr = sys.stdout, sys.stderr
        try:
            initialize_standard_streams(paths)
            assert sys.stdout is stdout and sys.stderr is stderr
            print("ordinary output")
            assert list(tqdm(range(2), disable=False)) == [0, 1]
            try:
                raise RuntimeError("real backend failure remains reportable")
            except RuntimeError:
                traceback.print_exc()
            stderr.flush()
        finally:
            stdout.close()
            stderr.close()
    assert "ordinary output" in (paths.temp / "windowed-stdout.log").read_text()
    assert "real backend failure remains reportable" in (paths.temp / "windowed-stderr.log").read_text()
    assert not (tmp_path / "_internal").exists()


def test_debug_and_redirected_streams_are_preserved(tmp_path, monkeypatch):
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    initialize_standard_streams(runtime_paths(frozen=True, executable=tmp_path / "app.exe"))
    assert sys.stdout is stdout and sys.stderr is stderr
    assert not (tmp_path / "temp").exists()


def test_only_missing_stream_is_repaired_with_null_fallback(tmp_path, monkeypatch):
    paths = runtime_paths(frozen=True, executable=tmp_path / "app.exe")
    paths.temp.write_text("blocks directory creation")
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stderr", None)
        original_stdout = sys.stdout
        initialize_standard_streams(paths)
        try:
            assert sys.stdout is original_stdout
            sys.stderr.write("progress")
            sys.stderr.flush()
        finally:
            sys.stderr.close()


def test_spec_repairs_streams_before_entry_imports():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging/MusicReviver.spec").read_text()
    assert 'runtime_hooks=[str(spec_dir / "runtime_hook.py")]' in spec
    entry = (root / "gui.py").read_text()
    assert entry.index("initialize_standard_streams()") < entry.index("from src.gui.app import main")

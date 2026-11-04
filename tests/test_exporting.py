"""No AI, model downloads, or GUI required by export tests."""
import hashlib
from pathlib import Path
import threading

import numpy as np
import pytest
import soundfile as sf

from src.exporting import (AudioFormat, ExportConfig, ExportError, ExportCancelled,
                           export_files, available_formats)
from src.exporting import processor
from src.runtime import RuntimeDependencyError


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "source 音.wav"
    t = np.arange(24000) / 48000
    sf.write(path, np.column_stack((.2 * np.sin(2*np.pi*440*t), .15 * np.sin(2*np.pi*550*t))),
             48000, subtype="PCM_24")
    return path


@pytest.fixture
def media_tools():
    try:
        return available_formats()
    except RuntimeDependencyError:
        pytest.skip("FFmpeg integration requires local tools; pure safety tests still run")


@pytest.mark.parametrize("kind,bitrate", [(AudioFormat.WAV,320), (AudioFormat.FLAC,320),
    (AudioFormat.MP3,192), (AudioFormat.MP3,256), (AudioFormat.MP3,320), (AudioFormat.M4A,256)])
def test_real_formats(audio, tmp_path, media_tools, kind, bitrate):
    if kind not in media_tools:
        pytest.skip(f"Encoder for {kind} unavailable")
    before = hashlib.sha256(audio.read_bytes()).hexdigest()
    progress = []
    result = export_files((audio,), ExportConfig(tmp_path / "export", kind, bitrate), progress_callback=progress.append)
    output = result.files[0]
    assert output.path.is_file() and output.channels == 2 and output.sample_rate == 48000
    assert abs(output.duration - .5) < .15 and output.size_bytes > 0
    assert progress[0].total == 1 and result.elapsed_seconds > 0
    assert hashlib.sha256(audio.read_bytes()).hexdigest() == before
    if kind in (AudioFormat.WAV, AudioFormat.FLAC):
        np.testing.assert_array_equal(sf.read(audio, dtype="int32")[0], sf.read(output.path, dtype="int32")[0])


def test_invalid_options_and_missing_sources(tmp_path):
    with pytest.raises(ValueError):
        ExportConfig(tmp_path, "mp3", 999)
    with pytest.raises(ValueError):
        ExportConfig(tmp_path, "unknown")
    with pytest.raises(ExportError):
        export_files((), ExportConfig(tmp_path))
    with pytest.raises(ExportError, match="missing"):
        export_files((tmp_path / "absent.wav",), ExportConfig(tmp_path))


def test_encoder_unavailable(audio, tmp_path, monkeypatch):
    monkeypatch.setattr(processor, "available_formats", lambda: ())
    with pytest.raises(ExportError, match="encoder"):
        export_files((audio,), ExportConfig(tmp_path / "out"))
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("count", [2, 6, 7])
def test_dynamic_batch_selection_and_collisions(tmp_path, monkeypatch, count):
    # Stub encoding only; exercise real batch staging and publication.
    monkeypatch.setattr(processor, "available_formats", lambda: (AudioFormat.WAV,))
    metric = dict(codec="pcm_s24le", duration=2., sample_rate=48000, channels=2,
                  bitrate=2304000, container="wav", bits=24)
    monkeypatch.setattr(processor, "_probe", lambda path: metric)
    monkeypatch.setattr(processor, "resolve_executable", lambda name: name)
    monkeypatch.setattr(processor, "_run", lambda cmd: Path(cmd[-1]).write_bytes(b"encoded"))
    files = tuple(tmp_path / f"arbitrary 音 {i}.wav" for i in range(count))
    for file in files:
        file.write_bytes(b"source")
    config = ExportConfig(tmp_path / "destination")
    first = export_files(files, config)
    selected = export_files((files[-1],), config)
    assert len(first.files) == count and len(selected.files) == 1
    assert selected.files[0].path.name.endswith("_2.wav")
    assert all(file.read_bytes() == b"source" for file in files)
    assert all(item.path.read_bytes() == b"encoded" for item in first.files)


def reports(tmp_path):
    files = (tmp_path / "analysis.json", tmp_path / "analysis.txt")
    for file in files:
        file.write_text("report", encoding="utf-8")
    return files


def test_reports_do_not_need_ffmpeg_and_source_destination_collision(tmp_path, monkeypatch):
    monkeypatch.setattr(processor, "available_formats", lambda: pytest.fail("Reports must not require encoding"))
    files = reports(tmp_path)
    result = export_files(files, ExportConfig(tmp_path))
    assert [item.path.name for item in result.files] == ["analysis_2.json", "analysis_2.txt"]
    assert all(item.path.read_text() == "report" and item.codec is None for item in result.files)


def test_batch_publication_failure_rolls_back_only_own_files(tmp_path, monkeypatch):
    files = reports(tmp_path)
    destination = tmp_path / "out"
    destination.mkdir()
    existing = destination / "analysis.json"
    existing.write_text("existing")
    original = processor._publish
    calls = []
    def fail_second(*args):
        calls.append(args)
        if len(calls) == 2:
            raise OSError("simulated publication failure")
        return original(*args)
    monkeypatch.setattr(processor, "_publish", fail_second)
    with pytest.raises(ExportError):
        export_files(files, ExportConfig(destination))
    assert list(destination.iterdir()) == [existing] and existing.read_text() == "existing"


def test_conversion_failure_cleans_staging(audio, tmp_path, monkeypatch):
    monkeypatch.setattr(processor, "available_formats", lambda: (AudioFormat.WAV,))
    monkeypatch.setattr(processor, "_probe", lambda path: {})
    monkeypatch.setattr(processor, "resolve_executable", lambda name: name)
    def fail(cmd):
        Path(cmd[-1]).write_bytes(b"partial")
        raise ExportError("failed conversion")
    monkeypatch.setattr(processor, "_run", fail)
    destination = tmp_path / "out"
    with pytest.raises(ExportError):
        export_files((audio,), ExportConfig(destination))
    assert not list(destination.iterdir()) and audio.is_file()


def test_cancel_between_files_publishes_nothing(tmp_path):
    files = reports(tmp_path)
    token = threading.Event()
    destination = tmp_path / "out"
    with pytest.raises(ExportCancelled):
        export_files(files, ExportConfig(destination),
                     progress_callback=lambda event: token.set(), cancelled=token.is_set)
    assert not list(destination.iterdir())


@pytest.mark.parametrize("change", [dict(channels=1), dict(sample_rate=44100), dict(duration=5),
    dict(codec="mp3"), dict(container="mp3"), dict(bits=16)])
def test_probe_validation_rejects_bad_outputs(tmp_path, change):
    source = dict(codec="pcm_s24le", duration=2., sample_rate=48000, channels=2,
                  bitrate=2304000, container="wav", bits=24)
    with pytest.raises(ExportError):
        processor._validate(source, dict(source, **change), ExportConfig(tmp_path))


def test_unrelated_cwd(tmp_path, monkeypatch):
    files = reports(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    config = ExportConfig(tmp_path / "out")
    monkeypatch.chdir(elsewhere)
    assert all(item.path.is_absolute() for item in export_files(files, config).files)


def test_ffmpeg_command_no_shell_or_dsp(audio, tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(processor, "available_formats", lambda: (AudioFormat.MP3,))
    monkeypatch.setattr(processor, "resolve_executable", lambda name: name)
    metric = dict(codec="mp3", duration=2., sample_rate=48000, channels=2,
                  bitrate=320000, container="mp3", bits=0)
    monkeypatch.setattr(processor, "_probe", lambda path: metric)
    def run(cmd):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"encoded")
    monkeypatch.setattr(processor, "_run", run)
    export_files((audio,), ExportConfig(tmp_path / "out", AudioFormat.MP3))
    assert "-af" not in commands[0] and "-ar" not in commands[0] and "-ac" not in commands[0]


def test_subprocess_shell_disabled(monkeypatch):
    def run(command, **kwargs):
        assert isinstance(command, list) and kwargs["shell"] is False
        return type("Response", (), {"returncode":0, "stdout":"ok"})()
    monkeypatch.setattr(processor.subprocess, "run", run)
    assert processor._run(["ffmpeg", "-version"]) == "ok"

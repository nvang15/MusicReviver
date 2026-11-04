import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.audio import metadata


def test_missing_file() -> None:
    with pytest.raises(metadata.MediaNotFoundError, match="does not exist"):
        metadata.probe_media(Path("definitely-missing.wav"))


def test_unsupported_extension(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("not media", encoding="utf-8")
    with pytest.raises(metadata.UnsupportedMediaError, match="Unsupported"):
        metadata.probe_media(source)


def test_metadata_parsing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "Example.MP3"
    source.write_bytes(b"1234")
    payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264"},
            {
                "codec_type": "audio", "codec_name": "mp3", "sample_rate": "44100",
                "channels": 2, "channel_layout": "stereo", "bit_rate": "192000",
            },
        ],
        "format": {"format_name": "mp3", "duration": "62.5", "size": "4"},
    }
    monkeypatch.setattr(
        metadata.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode("utf-8"), stderr=b""),
    )
    result = metadata.probe_media(source)
    assert result.filename == "Example.MP3"
    assert result.extension == ".mp3"
    assert result.duration_seconds == 62.5
    assert result.audio_codec == "mp3"
    assert result.sample_rate == 44100
    assert result.channels == 2
    assert result.channel_layout == "stereo"
    assert result.bitrate == 192000
    assert result.file_size_bytes == 4
    assert result.has_audio is True
    assert result.has_video is True


def test_ffprobe_failure_is_readable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "bad.wav"
    source.write_bytes(b"bad")
    monkeypatch.setattr(
        metadata.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="invalid data"),
    )
    with pytest.raises(metadata.MediaProbeError, match="invalid data"):
        metadata.probe_media(source)


def test_probe_invocation_does_not_use_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "odd; name.wav"
    source.write_bytes(b"x")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        payload = {"streams": [{"codec_type": "audio", "codec_name": "pcm_s16le"}], "format": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(metadata.subprocess, "run", fake_run)
    metadata.probe_media(source)
    assert seen["command"][-1] == str(source)
    assert seen["kwargs"]["shell"] is False and seen["kwargs"]["text"] is False


def test_ffprobe_utf8_bom_and_unicode_are_decoded_independently_from_stderr(monkeypatch, tmp_path):
    source = tmp_path / "入力音楽" / "夜に駆ける.wav"
    source.parent.mkdir(); source.write_bytes(b"x")
    payload = {"streams": [{"codec_type": "audio", "codec_name": "pcm_s24le", "sample_rate": "48000", "channels": 2}], "format": {"filename": str(source)}}
    monkeypatch.setattr(metadata.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode("utf-8"), stderr="診断".encode("utf-8")))
    result = metadata.probe_media(source)
    assert result.filename == "夜に駆ける.wav" and result.original_path == str(source)


def test_invalid_json_reports_separate_unicode_stderr(monkeypatch, tmp_path):
    source = tmp_path / "月亮代表我的心.wav"; source.write_bytes(b"x")
    monkeypatch.setattr(metadata.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=b"not-json", stderr="詳細エラー".encode("utf-8")))
    with pytest.raises(metadata.MediaProbeError, match="詳細エラー"):
        metadata.probe_media(source)

from src.audio import converter


def test_ffmpeg_detection_when_available(monkeypatch) -> None:
    monkeypatch.setattr(converter.shutil, "which", lambda name: f"/tools/{name}")
    assert converter.is_ffmpeg_available() is True


def test_ffmpeg_detection_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(converter.shutil, "which", lambda _name: None)
    assert converter.is_ffmpeg_available() is False


def test_ffprobe_detection_when_available(monkeypatch) -> None:
    monkeypatch.setattr(converter.shutil, "which", lambda name: f"/tools/{name}")
    assert converter.is_ffprobe_available() is True


def test_ffprobe_detection_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(converter.shutil, "which", lambda _name: None)
    assert converter.is_ffprobe_available() is False

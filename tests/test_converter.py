import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.audio import converter, metadata


TOOLS_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run_ffmpeg(*arguments: str) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def generated_media(tmp_path: Path) -> dict[str, Path]:
    if not TOOLS_AVAILABLE:
        pytest.skip("FFmpeg and ffprobe are required for integration tests")
    wav = tmp_path / "My OLD Song!.WAV"
    mp3 = tmp_path / "test.mp3"
    video = tmp_path / "live performance.mp4"
    silent_video = tmp_path / "silent.mp4"
    run_ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=0.25", str(wav))
    run_ffmpeg("-f", "lavfi", "-i", "sine=frequency=330:duration=0.25", str(mp3))
    run_ffmpeg(
        "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=0.25",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=0.25",
        "-shortest", "-c:v", "mpeg4", str(video),
    )
    run_ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.25", "-c:v", "mpeg4", str(silent_video))
    return {"wav": wav, "mp3": mp3, "video": video, "silent_video": silent_video}


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


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("My OLD Song!.mp3", "my_old_song"),
        ("  déjà vu (Live)  .MP4", "déjà_vu_live"),
        ("...wav", "media"),
        ("夜に駆ける.wav", "夜に駆ける"),
        ("月亮代表我的心.wav", "月亮代表我的心"),
        ("사랑.wav", "사랑"),
        ("canción été.wav", "canción_été"),
        ("größer.wav", "größer"),
        ("song 🎵 test.wav", "song_🎵_test"),
        ("宇多田ヒカル - First Love (2026) 🎹.wav", "宇多田ヒカル_-_first_love_2026_🎹"),
        ("CON.wav", "_con"),
    ],
)
def test_safe_project_directory_naming(filename: str, expected: str) -> None:
    assert converter.safe_project_name(Path(filename)) == expected


@pytest.mark.parametrize("kind", ["wav", "mp3", "video"])
def test_real_conversion_supported_media(
    generated_media: dict[str, Path], tmp_path: Path, kind: str
) -> None:
    output_root = tmp_path / "outputs"
    result = converter.convert_media(
        generated_media[kind], output_root=output_root, project_root=tmp_path
    )
    assert result.audio_path.exists()
    assert result.metadata_path.exists()
    output_metadata = metadata.probe_media(result.audio_path)
    assert output_metadata.audio_codec == "pcm_s24le"
    assert output_metadata.sample_rate == 48000
    assert output_metadata.channels == 2
    document = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert document["standardized_output"]["bits_per_sample"] == 24
    assert not Path(document["original"]["original_path"]).is_absolute()
    assert document["ffmpeg_version"].startswith("ffmpeg version")


def test_malformed_media(generated_media: dict[str, Path]) -> None:
    malformed = generated_media["wav"].parent / "corrupt.mp3"
    malformed.write_bytes(b"this is not media")
    with pytest.raises(metadata.MediaProbeError, match="Could not inspect"):
        converter.convert_media(malformed, output_root=malformed.parent / "output")


def test_video_without_audio(generated_media: dict[str, Path]) -> None:
    with pytest.raises(metadata.NoAudioStreamError, match="no audio"):
        converter.convert_media(
            generated_media["silent_video"], output_root=generated_media["silent_video"].parent / "out"
        )


def test_existing_output_and_force_overwrite(generated_media: dict[str, Path], tmp_path: Path) -> None:
    output_root = tmp_path / "outputs"
    first = converter.convert_media(generated_media["mp3"], output_root=output_root)
    first.audio_path.write_bytes(b"sentinel")
    with pytest.raises(converter.OutputExistsError, match="--force"):
        converter.convert_media(generated_media["mp3"], output_root=output_root)
    assert first.audio_path.read_bytes() == b"sentinel"
    second = converter.convert_media(generated_media["mp3"], output_root=output_root, force=True)
    assert second.audio_path.read_bytes() != b"sentinel"
    assert metadata.probe_media(second.audio_path).audio_codec == "pcm_s24le"


@pytest.mark.parametrize("relative", ["夜に駆ける.wav", "月亮代表我的心.wav", "사랑.wav", "canción été.wav", "größer.wav", "song 🎵 test.wav", "宇多田ヒカル - First Love (2026) 🎹.wav", "入力音楽/夜に駆ける.wav"])
def test_real_ffmpeg_ffprobe_import_supports_unicode_paths(tmp_path, relative):
    if not TOOLS_AVAILABLE:
        pytest.skip("FFmpeg and ffprobe are required")
    source = tmp_path / relative; source.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=0.05", str(source))
    probed = metadata.probe_media(source)
    result = converter.convert_media(source, output_root=tmp_path / "output", project_root=tmp_path)
    raw = result.metadata_path.read_text(encoding="utf-8"); document = json.loads(raw)
    assert probed.filename == source.name and result.project_name == converter.safe_project_name(source)
    assert result.audio_path.is_file() and document["original"]["filename"] == source.name
    assert {char for char in source.stem if ord(char) > 127}.issubset(set(result.project_name))
    assert "\\u" not in raw

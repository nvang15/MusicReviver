"""Media validation and metadata inspection using ffprobe JSON output."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".webm"})
SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


class MediaImportError(Exception):
    """Base class for expected, user-readable media import errors."""


class MediaNotFoundError(MediaImportError):
    """Raised when an input path does not exist."""


class InvalidMediaPathError(MediaImportError):
    """Raised when an input path is not a regular file."""


class UnsupportedMediaError(MediaImportError):
    """Raised when an input file extension is unsupported."""


class MediaProbeError(MediaImportError):
    """Raised when ffprobe cannot inspect a media file."""


class NoAudioStreamError(MediaImportError):
    """Raised when probed media contains no usable audio stream."""


@dataclass(frozen=True)
class MediaMetadata:
    """Useful source-media properties reported by ffprobe."""

    filename: str
    original_path: str
    extension: str
    container_format: str | None
    duration_seconds: float | None
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None
    channel_layout: str | None
    bitrate: int | None
    file_size_bytes: int
    has_audio: bool
    has_video: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value)) if value not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    try:
        return float(str(value)) if value not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def validate_input_path(path: Path) -> Path:
    """Validate path and extension requirements without probing content."""
    path = Path(path)
    if not path.exists():
        raise MediaNotFoundError(f"Media file does not exist: {path}")
    if not path.is_file():
        raise InvalidMediaPathError(f"Media path is not a file: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedMediaError(
            f"Unsupported media extension '{path.suffix or '(none)'}'. Supported: {supported}"
        )
    return path


def probe_media(path: Path, *, ffprobe: str = "ffprobe") -> MediaMetadata:
    """Validate and inspect a media file with machine-readable ffprobe output."""
    path = validate_input_path(path)
    command = [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise MediaProbeError(f"Unable to run ffprobe: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown ffprobe error"
        raise MediaProbeError(f"Could not inspect '{path.name}': {detail}")
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MediaProbeError(f"ffprobe returned invalid JSON for '{path.name}'.") from exc

    streams = payload.get("streams", [])
    if not isinstance(streams, list):
        raise MediaProbeError(f"ffprobe returned invalid stream data for '{path.name}'.")
    audio_streams = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]
    has_video = any(isinstance(s, dict) and s.get("codec_type") == "video" for s in streams)
    if not audio_streams:
        raise NoAudioStreamError(f"Media file contains no audio stream: {path.name}")

    audio = audio_streams[0]
    format_data = payload.get("format", {})
    if not isinstance(format_data, dict):
        format_data = {}
    duration = _optional_float(format_data.get("duration"))
    if duration is None:
        duration = _optional_float(audio.get("duration"))
    bitrate = _optional_int(audio.get("bit_rate"))
    if bitrate is None:
        bitrate = _optional_int(format_data.get("bit_rate"))
    return MediaMetadata(
        filename=path.name,
        original_path=str(path),
        extension=path.suffix.lower(),
        container_format=format_data.get("format_name"),
        duration_seconds=duration,
        audio_codec=audio.get("codec_name"),
        sample_rate=_optional_int(audio.get("sample_rate")),
        channels=_optional_int(audio.get("channels")),
        channel_layout=audio.get("channel_layout"),
        bitrate=bitrate,
        file_size_bytes=path.stat().st_size,
        has_audio=True,
        has_video=has_video,
    )

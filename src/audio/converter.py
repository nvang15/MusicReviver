"""FFmpeg-backed conversion to MusicReviver's internal audio format."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.audio.metadata import MediaImportError, MediaMetadata, probe_media
from src.config import OUTPUT_DIR, PROJECT_ROOT

INTERNAL_SAMPLE_RATE = 48_000
INTERNAL_CHANNELS = 2
INTERNAL_CODEC = "pcm_s24le"


class OutputExistsError(MediaImportError):
    """Raised when conversion would overwrite an existing output."""


class MediaConversionError(MediaImportError):
    """Raised when FFmpeg cannot convert a source file."""


@dataclass(frozen=True)
class ConversionResult:
    """Paths and metadata produced by a completed import."""

    source_metadata: MediaMetadata
    project_name: str
    project_directory: Path
    audio_path: Path
    metadata_path: Path


def is_executable_available(executable: str) -> bool:
    """Return whether an executable can be resolved from the current PATH."""
    return shutil.which(executable) is not None


def is_ffmpeg_available() -> bool:
    """Return whether FFmpeg is available on PATH."""
    return is_executable_available("ffmpeg")


def is_ffprobe_available() -> bool:
    """Return whether FFprobe is available on PATH."""
    return is_executable_available("ffprobe")


def safe_project_name(path: Path) -> str:
    """Create a filesystem-safe, readable project name from a media filename."""
    stem = unicodedata.normalize("NFKC", Path(path).stem).strip().lower()
    stem = re.sub(r"[^\w-]+", "_", stem, flags=re.UNICODE)
    stem = re.sub(r"_+", "_", stem).strip("._-")
    return stem or "media"


def _relative_or_filename(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.name


def get_ffmpeg_version(*, ffmpeg: str = "ffmpeg") -> str | None:
    """Return the first FFmpeg version line when available."""
    try:
        result = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    lines = result.stdout.splitlines()
    return lines[0].strip() if result.returncode == 0 and lines else None


def convert_media(
    input_path: Path,
    *,
    output_root: Path = OUTPUT_DIR,
    project_root: Path = PROJECT_ROOT,
    force: bool = False,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> ConversionResult:
    """Probe and convert media to stereo 48 kHz, 24-bit PCM WAV."""
    input_path = Path(input_path)
    metadata = probe_media(input_path, ffprobe=ffprobe)
    project_name = safe_project_name(input_path)
    project_directory = Path(output_root) / project_name
    source_directory = project_directory / "source"
    output_path = source_directory / "original_48k.wav"
    metadata_path = source_directory / "metadata.json"
    if output_path.exists() and not force:
        raise OutputExistsError(
            f"Converted audio already exists: {output_path}. Use --force to overwrite it."
        )
    source_directory.mkdir(parents=True, exist_ok=True)
    temporary_path = source_directory / ".original_48k.tmp.wav"
    temporary_path.unlink(missing_ok=True)
    command = [
        ffmpeg, "-v", "error", "-nostdin", "-i", str(input_path),
        "-map", "0:a:0", "-vn", "-c:a", INTERNAL_CODEC,
        "-ar", str(INTERNAL_SAMPLE_RATE), "-ac", str(INTERNAL_CHANNELS),
        "-y", str(temporary_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise MediaConversionError(f"Unable to run FFmpeg: {exc}") from exc
    if result.returncode != 0:
        temporary_path.unlink(missing_ok=True)
        detail = result.stderr.strip() or "unknown FFmpeg error"
        raise MediaConversionError(f"FFmpeg could not convert '{input_path.name}': {detail}")
    try:
        converted = probe_media(temporary_path, ffprobe=ffprobe)
    except MediaImportError as exc:
        temporary_path.unlink(missing_ok=True)
        raise MediaConversionError(f"Converted WAV validation failed: {exc}") from exc
    if (converted.audio_codec != INTERNAL_CODEC or converted.sample_rate != INTERNAL_SAMPLE_RATE
            or converted.channels != INTERNAL_CHANNELS):
        temporary_path.unlink(missing_ok=True)
        raise MediaConversionError(
            "Converted WAV failed format validation "
            f"(codec={converted.audio_codec}, sample_rate={converted.sample_rate}, "
            f"channels={converted.channels})."
        )
    os.replace(temporary_path, output_path)
    document = {
        "original": {**metadata.to_dict(), "original_path": _relative_or_filename(input_path, project_root)},
        "standardized_output": {
            "format": "wav", "codec": INTERNAL_CODEC, "sample_rate": INTERNAL_SAMPLE_RATE,
            "channels": INTERNAL_CHANNELS, "channel_layout": "stereo", "bits_per_sample": 24,
            "path": _relative_or_filename(output_path, project_root),
        },
        "conversion_timestamp": datetime.now(timezone.utc).isoformat(),
        "ffmpeg_version": get_ffmpeg_version(ffmpeg=ffmpeg),
    }
    temporary_metadata = source_directory / ".metadata.tmp.json"
    temporary_metadata.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary_metadata, metadata_path)
    return ConversionResult(metadata, project_name, project_directory, output_path, metadata_path)

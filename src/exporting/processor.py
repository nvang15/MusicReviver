"""Staged encoding and no-overwrite publication. No DSP or pipeline calls."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from dataclasses import replace
from typing import Callable

from src.runtime import resolve_executable
from .exceptions import ExportCancelled, ExportError
from .models import AudioFormat, ExportConfig, ExportedFile, ExportProgress, ExportResult

ENCODERS = {AudioFormat.WAV: "pcm_s24le", AudioFormat.FLAC: "flac",
            AudioFormat.MP3: "libmp3lame", AudioFormat.M4A: "aac"}
CODECS = {**ENCODERS, AudioFormat.MP3: "mp3"}
REPORT_EXTENSIONS = {".json", ".txt"}


def _run(command: list[str]) -> str:
    result = subprocess.run(command, shell=False, capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ExportError(f"Media tool failed: {result.stderr[-2000:].strip()}")
    return result.stdout


def available_formats() -> tuple[AudioFormat, ...]:
    listing = _run([resolve_executable("ffmpeg"), "-hide_banner", "-encoders"])
    names = {parts[1] for line in listing.splitlines() if len(parts := line.split()) >= 2}
    return tuple(kind for kind, encoder in ENCODERS.items() if encoder in names)


def _probe(path: Path) -> dict:
    try:
        data = json.loads(_run([resolve_executable("ffprobe"), "-v", "error", "-select_streams", "a:0",
                               "-show_streams", "-show_format", "-of", "json", str(path)]))
        stream = data["streams"][0]
        duration = float(stream.get("duration", data["format"].get("duration")))
        rate, channels = int(stream["sample_rate"]), int(stream["channels"])
        if not math.isfinite(duration) or duration <= 0 or rate <= 0 or channels <= 0:
            raise ValueError("Invalid audio dimensions")
        bitrate = stream.get("bit_rate", data["format"].get("bit_rate"))
        return dict(codec=stream["codec_name"], duration=duration, sample_rate=rate,
                    channels=channels, bitrate=int(bitrate) if bitrate and bitrate != "N/A" else None,
                    container=data["format"]["format_name"], bits=int(stream.get("bits_per_raw_sample") or 0))
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ExportError(f"Could not validate audio: {path.name}") from exc


def _validate(source: dict, output: dict, config: ExportConfig) -> None:
    tolerance = .15 if config.format in (AudioFormat.MP3, AudioFormat.M4A) else 1 / source["sample_rate"]
    containers = {AudioFormat.WAV: "wav", AudioFormat.FLAC: "flac", AudioFormat.MP3: "mp3", AudioFormat.M4A: "mp4"}
    if (output["codec"] != CODECS[config.format] or containers[config.format] not in output["container"].split(",")
            or output["sample_rate"] != source["sample_rate"] or output["channels"] != source["channels"]
            or abs(output["duration"] - source["duration"]) > tolerance):
        raise ExportError("Export validation failed: codec, container, duration, or audio dimensions changed.")
    if config.format in (AudioFormat.WAV, AudioFormat.FLAC) and output["bits"] != 24:
        raise ExportError("Export validation failed: expected 24-bit audio.")
    if config.format is AudioFormat.MP3 and (not output["bitrate"] or
            abs(output["bitrate"] - config.bitrate_kbps * 1000) > config.bitrate_kbps * 100):
        raise ExportError("Export validation failed: unexpected MP3 bitrate.")
    if config.format is AudioFormat.M4A and (not output["bitrate"] or output["bitrate"] <= 0
                                            or output["bitrate"] > 640000):
        raise ExportError("Export validation failed: invalid AAC bitrate.")


def _publish(staged: Path, directory: Path, filename: str) -> Path:
    """Atomic no-replace publication: Windows rename, POSIX hard link."""
    name = Path(filename)
    counter = 1
    while True:
        target = directory / (name.name if counter == 1 else f"{name.stem}_{counter}{name.suffix}")
        try:
            if os.name == "nt":
                os.rename(staged, target)  # Windows rename never replaces an existing file.
            else:
                os.link(staged, target)
            return target
        except FileExistsError:
            counter += 1


def export_files(files: tuple[Path, ...], config: ExportConfig, *,
                 progress_callback: Callable[[ExportProgress], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> ExportResult:
    """Encode selected audio/copy reports; publish only after every file validates.

    POSIX publication requires a filesystem supporting hard links (e.g. ext4).
    Cancellation is checked between files and before publication. A process crash
    during publication can leave complete files, but never partially written files.
    """
    started = time.perf_counter()
    sources = tuple(Path(path).resolve() for path in files)
    if not sources or len(set(sources)) != len(sources):
        raise ExportError("Select at least one file, without duplicates.")
    if any(not path.is_file() for path in sources):
        raise ExportError("An export source is missing. Run processing again or select an existing result.")
    audio = any(path.suffix.lower() not in REPORT_EXTENSIONS for path in sources)
    if audio and config.format not in available_formats():
        raise ExportError(f"The installed FFmpeg does not provide the {config.format.value.upper()} encoder.")
    config.destination.mkdir(parents=True, exist_ok=True)
    published = []
    def check_cancel():
        if cancelled and cancelled():
            raise ExportCancelled("Export cancelled after the current file; no files published.")
    try:
        with tempfile.TemporaryDirectory(prefix=".musicreviver-export-", dir=config.destination) as temporary:
            pending = []
            for index, source in enumerate(sources):
                check_cancel()
                if progress_callback:
                    progress_callback(ExportProgress(index, len(sources), f"Preparing {source.name}"))
                report = source.suffix.lower() in REPORT_EXTENSIONS
                suffix = source.suffix if report else f".{config.format.value}"
                stage = Path(temporary) / f"{index}{suffix}"
                measured = dict(codec=None, duration=None, sample_rate=None, channels=None, bitrate=None)
                if report:
                    shutil.copyfile(source, stage)
                else:
                    original = _probe(source)
                    command = [resolve_executable("ffmpeg"), "-v", "error", "-nostdin", "-i", str(source),
                               "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-c:a", ENCODERS[config.format]]
                    if config.format in (AudioFormat.MP3, AudioFormat.M4A):
                        command += ["-b:a", f"{config.bitrate_kbps}k"]
                    if config.format is AudioFormat.FLAC:
                        command += ["-sample_fmt", "s32", "-bits_per_raw_sample", "24"]
                    _run(command + ["-n", str(stage)])
                    measured = _probe(stage)
                    _validate(original, measured, config)
                pending.append((stage, source.stem + suffix, ExportedFile(source, stage,
                    **{key: measured[key] for key in ("codec", "duration", "sample_rate", "channels", "bitrate")},
                    size_bytes=stage.stat().st_size)))
            check_cancel()
            results = []
            try:
                for stage, name, result in pending:
                    identity = stage.stat()
                    target = _publish(stage, config.destination, name)
                    published.append((target, identity))
                    results.append(replace(result, path=target))
            except Exception:
                for target, identity in reversed(published):
                    if target.exists() and os.path.samestat(target.stat(), identity):
                        target.unlink()
                raise
        # Callback errors after publication must not turn a successful export into failure.
        return ExportResult(tuple(results), time.perf_counter() - started)
    except (ExportError, ExportCancelled):
        raise
    except OSError as exc:
        raise ExportError(f"Could not export files: {exc}. On Linux/macOS the destination must support hard links.") from exc

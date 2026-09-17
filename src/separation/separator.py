"""High-level import, inference, validation, and publication for stem separation."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.audio.converter import INTERNAL_CHANNELS, INTERNAL_CODEC, INTERNAL_SAMPLE_RATE, convert_media, safe_project_name
from src.audio.metadata import MediaImportError, probe_media
from src.config import MODEL_DIR, OUTPUT_DIR, PROJECT_ROOT, TEMP_DIR
from src.separation.backends import AudioSeparatorBackend, DeviceMode, device_selection_reason, directml_available, select_device
from src.separation.exceptions import BackendUnavailableError, MissingStemError, OutputExistsError, SeparationError
from src.separation.models import DEFAULT_MODEL_ID, SeparationModel, get_model
from src.separation.stems import StemType


@dataclass(frozen=True)
class SeparationRequest:
    input_path: Path
    model: SeparationModel
    requested_device: DeviceMode
    selected_device: DeviceMode
    selection_reason: str
    directml_available: bool
    force: bool = False


@dataclass(frozen=True)
class SeparationResult:
    request: SeparationRequest
    standardized_source: Path
    stems_directory: Path
    stems: dict[StemType, Path]
    metadata_path: Path
    processing_duration: float


def prepare_separation(input_path: Path, *, model_id: str = DEFAULT_MODEL_ID,
                       device: DeviceMode | str = DeviceMode.AUTO, force: bool = False,
                       providers: tuple[str, ...] | None = None) -> SeparationRequest:
    """Validate media, model compatibility, and requested execution device."""
    probe_media(input_path)
    model = get_model(model_id)
    try:
        requested = device if isinstance(device, DeviceMode) else DeviceMode(device)
    except ValueError as exc:
        raise SeparationError(f"Unknown separation device '{device}'.") from exc
    has_directml = directml_available(providers)
    selected = select_device(requested, model=model, providers=providers)
    reason = device_selection_reason(requested, selected, model, directml=has_directml)
    return SeparationRequest(Path(input_path), model, requested, selected, reason, has_directml, force)


def _standardized_source(request: SeparationRequest, *, output_root: Path, project_root: Path) -> Path:
    source = output_root / safe_project_name(request.input_path) / "source" / "original_48k.wav"
    if source.exists():
        metadata = probe_media(source)
        if metadata.audio_codec == INTERNAL_CODEC and metadata.sample_rate == INTERNAL_SAMPLE_RATE and metadata.channels == INTERNAL_CHANNELS:
            return source
    return convert_media(request.input_path, output_root=output_root, project_root=project_root,
                         force=source.exists()).audio_path


def _existing_output_is_valid(directory: Path, model: SeparationModel) -> bool:
    metadata_path = directory / "separation.json"
    if not metadata_path.is_file():
        return False
    try:
        document = json.loads(metadata_path.read_text(encoding="utf-8"))
        if document.get("model_filename") != model.filename:
            return False
        return all(probe_media(directory / f"{stem}.wav").has_audio for stem in model.expected_stems)
    except (OSError, ValueError, json.JSONDecodeError, MediaImportError):
        return False


def _validate_stem(path: Path, source_duration: float | None) -> None:
    metadata = probe_media(path)
    if metadata.audio_codec != INTERNAL_CODEC:
        raise SeparationError(
            f"Canonical stem has invalid codec '{metadata.audio_codec}': {path.name}"
        )
    if metadata.sample_rate != INTERNAL_SAMPLE_RATE:
        raise SeparationError(
            f"Canonical stem has invalid sample rate '{metadata.sample_rate}': {path.name}"
        )
    if metadata.channels != INTERNAL_CHANNELS:
        raise SeparationError(
            f"Canonical stem has invalid channel count '{metadata.channels}': {path.name}"
        )
    if source_duration is not None and metadata.duration_seconds is not None:
        tolerance = max(2.0, source_duration * 0.10)
        if abs(metadata.duration_seconds - source_duration) > tolerance:
            raise SeparationError(f"Generated stem duration differs too much from the source: {path.name}")


def _normalize_stem(source: Path, destination: Path, *, ffmpeg: str = "ffmpeg") -> None:
    """Create a canonical 48 kHz, stereo, 24-bit PCM WAV without altering source."""
    command = [
        ffmpeg, "-v", "error", "-nostdin", "-i", str(source), "-map", "0:a:0",
        "-vn", "-c:a", INTERNAL_CODEC, "-ar", str(INTERNAL_SAMPLE_RATE),
        "-ac", str(INTERNAL_CHANNELS), "-y", str(destination),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise SeparationError(f"Unable to run FFmpeg while normalizing {source.name}: {exc}") from exc
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = result.stderr.strip() or "unknown FFmpeg error"
        raise SeparationError(f"Could not normalize stem '{source.name}': {detail}")


def _package_version() -> str | None:
    try:
        return importlib.metadata.version("audio-separator")
    except importlib.metadata.PackageNotFoundError:
        return None


def separate(request: SeparationRequest, *, backend: AudioSeparatorBackend | None = None,
             output_root: Path = OUTPUT_DIR, temp_root: Path = TEMP_DIR,
             project_root: Path = PROJECT_ROOT) -> SeparationResult:
    """Standardize input, run a backend in staging, validate, and publish stems."""
    backend = backend or AudioSeparatorBackend(device=request.selected_device, model_cache=MODEL_DIR)
    if not backend.available:
        raise BackendUnavailableError("The audio-separator backend is not installed. Install the separation dependencies first.")
    source = _standardized_source(request, output_root=output_root, project_root=project_root)
    source_metadata = probe_media(source)
    project_directory = output_root / safe_project_name(request.input_path)
    final_directory = project_directory / "stems"
    if final_directory.exists() and not request.force:
        state = "valid stems already exist" if _existing_output_is_valid(final_directory, request.model) else "a stems directory already exists"
        raise OutputExistsError(f"{state} at {final_directory}. Use --force to replace it.")

    temp_root.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="musicreviver-separation-", dir=temp_root) as temporary:
        temporary_root = Path(temporary)
        raw_directory = temporary_root / "backend"
        staged_directory = temporary_root / "stems"
        raw_directory.mkdir()
        staged_directory.mkdir()
        generated = backend.separate(source, raw_directory, request.model)
        missing = [stem for stem in request.model.expected_stems if stem not in generated]
        if missing:
            raise MissingStemError("Backend did not produce required stem(s): " + ", ".join(str(stem) for stem in missing))

        canonical: dict[StemType, Path] = {}
        native_sample_rates: dict[str, int | None] = {}
        for stem in request.model.expected_stems:
            generated_path = generated[stem]
            if not generated_path.is_file():
                raise MissingStemError(f"Backend reported a missing stem file: {generated_path}")
            native_sample_rates[str(stem)] = probe_media(generated_path).sample_rate
            destination = staged_directory / f"{stem}.wav"
            _normalize_stem(generated_path, destination)
            _validate_stem(destination, source_metadata.duration_seconds)
            canonical[stem] = destination

        elapsed = time.perf_counter() - started
        document = {
            "backend": backend.name,
            "audio_separator_version": _package_version(),
            "model_filename": request.model.filename,
            "model_display_name": request.model.display_name,
            "selected_device": request.selected_device.value,
            "requested_device": request.requested_device.value,
            "device_selection_reason": request.selection_reason,
            "directml_available": request.directml_available,
            "expected_stems": [str(stem) for stem in request.model.expected_stems],
            "actual_stems": [str(stem) for stem in canonical],
            "processing_start_time": started_at.isoformat(),
            "processing_duration_seconds": elapsed,
            "source_file": source.resolve().relative_to(project_root.resolve()).as_posix(),
            "output_format": "wav",
            "backend_native_output_sample_rates": native_sample_rates,
            "canonical_output_sample_rate": INTERNAL_SAMPLE_RATE,
            "canonical_output_codec": INTERNAL_CODEC,
            "canonical_output_channels": INTERNAL_CHANNELS,
            "warnings": [request.model.notes] if request.model.notes else [],
            "experimental_notes": request.model.notes if request.model.experimental else None,
        }
        (staged_directory / "separation.json").write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        backup = project_directory / ".stems-backup"
        if backup.exists():
            shutil.rmtree(backup)
        if final_directory.exists():
            os.replace(final_directory, backup)
        try:
            os.replace(staged_directory, final_directory)
        except OSError:
            if backup.exists() and not final_directory.exists():
                os.replace(backup, final_directory)
            raise
        if backup.exists():
            shutil.rmtree(backup)

    final_stems = {stem: final_directory / f"{stem}.wav" for stem in request.model.expected_stems}
    return SeparationResult(request, source, final_directory, final_stems,
                            final_directory / "separation.json", elapsed)

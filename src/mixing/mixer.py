"""Stem discovery, aligned floating-point summing, safety, and atomic output."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from src.audio.converter import INTERNAL_CHANNELS, INTERNAL_CODEC, INTERNAL_SAMPLE_RATE, convert_media, safe_project_name
from src.audio.metadata import MediaImportError, probe_media
from src.config import OUTPUT_DIR, PROJECT_ROOT, TEMP_DIR
from src.mixing.exceptions import MixOutputExistsError, MixingError, NoMixStemsError, StemAlignmentError
from src.mixing.metrics import audio_metrics, reference_comparison
from src.mixing.models import MixResult, MixSource, MixWarning
from src.mixing.planner import create_mix_plan
from src.mixing.report import render_mix_report

SCHEMA_VERSION = "1.0"
PEAK_CEILING_DBFS = -0.5
PEAK_CEILING = 10.0 ** (PEAK_CEILING_DBFS / 20.0)
FRAME_TOLERANCE = 1


def _ensure_reference(input_path: Path, output_root: Path, project_root: Path) -> Path:
    reference = output_root / safe_project_name(input_path) / "source" / "original_48k.wav"
    if reference.exists():
        metadata = probe_media(reference)
        if metadata.audio_codec == INTERNAL_CODEC and metadata.sample_rate == INTERNAL_SAMPLE_RATE and metadata.channels == INTERNAL_CHANNELS:
            return reference
    return convert_media(input_path, output_root=output_root, project_root=project_root,
                         force=reference.exists()).audio_path


def _discover_restored(project: Path) -> tuple[dict[str, Path], list[MixWarning]]:
    directory = project / "restored"
    metadata_path = directory / "restoration.json"
    if not metadata_path.is_file():
        return {}, []
    stems = {
        path.stem.removesuffix("_restored"): path
        for path in sorted(directory.glob("*_restored.wav")) if path.is_file()
    }
    warnings: list[MixWarning] = []
    try:
        expected = set(json.loads(metadata_path.read_text(encoding="utf-8")).get("results", {}))
    except (OSError, json.JSONDecodeError):
        return {}, [MixWarning("invalid_restoration_metadata", "Restored stems were ignored because restoration.json was invalid.")]
    missing = sorted(expected - set(stems))
    if missing:
        warnings.append(MixWarning("invalid_restored_set", "Missing restored stems: " + ", ".join(missing)))
        return {}, warnings
    for name, path in stems.items():
        try:
            metadata = probe_media(path)
        except (MediaImportError, OSError):
            return {}, [MixWarning("invalid_restored_set", f"Restored stem could not be validated: {name}")]
        if metadata.audio_codec != INTERNAL_CODEC or metadata.sample_rate != INTERNAL_SAMPLE_RATE or metadata.channels != INTERNAL_CHANNELS:
            return {}, [MixWarning("invalid_restored_set", f"Restored stem is not canonical: {name}")]
    return stems, warnings


def _discover_separated(project: Path) -> tuple[dict[str, Path], list[MixWarning]]:
    directory = project / "stems"
    stems = {path.stem: path for path in sorted(directory.glob("*.wav")) if path.is_file()} if directory.is_dir() else {}
    warnings: list[MixWarning] = []
    metadata_path = directory / "separation.json"
    if metadata_path.is_file():
        try:
            expected = set(json.loads(metadata_path.read_text(encoding="utf-8")).get("actual_stems", []))
            missing = sorted(expected - set(stems))
            if missing:
                warnings.append(MixWarning("partial_separated_set", "Missing separated stems: " + ", ".join(missing)))
        except (OSError, json.JSONDecodeError):
            warnings.append(MixWarning("invalid_separation_metadata", "Stem files were discovered but separation.json was invalid."))
    return stems, warnings


def discover_mix_inputs(project: Path, requested: MixSource) -> tuple[MixSource, dict[str, Path], list[MixWarning]]:
    """Select restored or separated stems without starting separation."""
    restored, restored_warnings = _discover_restored(project)
    separated, separated_warnings = _discover_separated(project)
    if requested is MixSource.RESTORED:
        if not restored:
            raise NoMixStemsError("No valid restored stems were found for this project.")
        return MixSource.RESTORED, restored, restored_warnings
    if requested is MixSource.SEPARATED:
        if not separated:
            raise NoMixStemsError("No canonical separated stems were found for this project.")
        return MixSource.SEPARATED, separated, separated_warnings
    if restored:
        return MixSource.RESTORED, restored, restored_warnings
    if separated:
        return MixSource.SEPARATED, separated, [*restored_warnings, *separated_warnings]
    raise NoMixStemsError(
        "No restored or separated stems were found. Run stem separation first; mixing does not start AI separation automatically."
    )


def _load_canonical(path: Path) -> tuple[np.ndarray, int]:
    try:
        info = sf.info(path)
        audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise StemAlignmentError(f"Could not read canonical audio '{path.name}': {exc}") from exc
    if sample_rate != INTERNAL_SAMPLE_RATE:
        raise StemAlignmentError(f"Sample-rate mismatch for {path.name}: {sample_rate} Hz")
    if audio.shape[1] != INTERNAL_CHANNELS:
        raise StemAlignmentError(f"Channel-count mismatch for {path.name}: {audio.shape[1]}")
    if info.subtype != "PCM_24":
        raise StemAlignmentError(f"Bit-depth mismatch for {path.name}: {info.subtype}")
    if audio.size == 0 or not np.all(np.isfinite(audio)):
        raise StemAlignmentError(f"Invalid samples in {path.name}")
    return audio, sample_rate


def _aligned_audio(paths: dict[str, Path], reference_path: Path) -> tuple[dict[str, np.ndarray], np.ndarray]:
    reference, _ = _load_canonical(reference_path)
    stems = {name: _load_canonical(path)[0] for name, path in paths.items()}
    frame_counts = [reference.shape[0], *(audio.shape[0] for audio in stems.values())]
    if max(frame_counts) - min(frame_counts) > FRAME_TOLERANCE:
        details = ", ".join(f"{name}={audio.shape[0]}" for name, audio in stems.items())
        raise StemAlignmentError(
            f"Stem durations are materially misaligned (reference={reference.shape[0]}, {details})."
        )
    frames = min(frame_counts)
    return {name: audio[:frames] for name, audio in stems.items()}, reference[:frames]


def mix_project(input_path: Path, *, source: MixSource = MixSource.AUTO, force: bool = False,
                output_root: Path = OUTPUT_DIR, project_root: Path = PROJECT_ROOT,
                temp_root: Path = TEMP_DIR) -> MixResult:
    """Plan and atomically render a reference-aware canonical stereo mix."""
    input_path = Path(input_path)
    project_name = safe_project_name(input_path)
    project = output_root / project_name
    reference_path = _ensure_reference(input_path, output_root, project_root)
    selected_source, stem_paths, discovery_warnings = discover_mix_inputs(project, source)
    mix_directory = project / "mix"
    if mix_directory.exists() and not force:
        raise MixOutputExistsError(f"Mix output already exists: {mix_directory}. Use --force to replace it.")
    stems, reference = _aligned_audio(stem_paths, reference_path)
    plan = create_mix_plan(stems, reference, selected_source)
    started = time.perf_counter()
    premix = np.zeros(reference.shape, dtype=np.float64)
    for setting in plan.settings:
        premix += stems[setting.stem].astype(np.float64, copy=False) * setting.linear_gain
    if not np.all(np.isfinite(premix)):
        raise MixingError("Mix summing produced non-finite samples.")
    premix_peak = float(np.max(np.abs(premix)))
    safety_gain = min(1.0, PEAK_CEILING / premix_peak) if premix_peak > 0.0 else 1.0
    final_mix = premix * safety_gain
    safety_gain_db = float(20.0 * np.log10(safety_gain)) if safety_gain < 1.0 else 0.0
    warnings = [*discovery_warnings, *plan.warnings]
    if safety_gain < 1.0:
        warnings.append(MixWarning(
            "safety_attenuation_applied",
            "The summed peak exceeded -0.5 dBFS; transparent global attenuation was applied.",
        ))
    elapsed = time.perf_counter() - started
    output_name = "restored_mix.wav" if selected_source is MixSource.RESTORED else "separated_mix.wav"
    final_audio_path = mix_directory / output_name
    reference_values = audio_metrics(reference, INTERNAL_SAMPLE_RATE)
    premix_values = audio_metrics(premix, INTERNAL_SAMPLE_RATE)
    final_values = audio_metrics(final_mix, INTERNAL_SAMPLE_RATE)
    comparison = reference_comparison(reference, final_mix)

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project": project_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stem_source": selected_source.value,
        "stems_used": [
            {"name": name, "path": path.resolve().relative_to(project_root.resolve()).as_posix()}
            for name, path in stem_paths.items()
        ],
        "gain_settings": [setting.__dict__ for setting in plan.settings],
        "gain_estimation_method": plan.gain_estimation_method,
        "reference_fitting_succeeded": plan.reference_fitting_succeeded,
        "unity_fallback": plan.unity_fallback,
        "safety_gain_db": safety_gain_db,
        "reference_metrics": reference_values,
        "premix_metrics": premix_values,
        "final_mix_metrics": final_values,
        "reference_comparison": comparison,
        "warnings": [warning.__dict__ for warning in warnings],
        "processing_duration_seconds": elapsed,
        "output_format": {"container": "wav", "codec": INTERNAL_CODEC,
                          "sample_rate": INTERNAL_SAMPLE_RATE, "channels": INTERNAL_CHANNELS},
        "output_path": final_audio_path.resolve().relative_to(project_root.resolve()).as_posix(),
        "clipping": bool(float(final_values["peak_amplitude"] or 0.0) > PEAK_CEILING + 1e-9),
    }
    temp_root.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="musicreviver-mix-", dir=temp_root) as temporary:
        staged = Path(temporary) / "mix"
        staged.mkdir()
        staged_audio = staged / output_name
        try:
            sf.write(staged_audio, final_mix, INTERNAL_SAMPLE_RATE, format="WAV", subtype="PCM_24")
        except (OSError, RuntimeError, ValueError) as exc:
            raise MixingError(f"Could not write staged mix: {exc}") from exc
        metadata = probe_media(staged_audio)
        if metadata.audio_codec != INTERNAL_CODEC or metadata.sample_rate != INTERNAL_SAMPLE_RATE or metadata.channels != INTERNAL_CHANNELS:
            raise MixingError("Rendered mix failed canonical format validation.")
        (staged / "mix.json").write_text(
            json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
        )
        (staged / "mix.txt").write_text(render_mix_report(document), encoding="utf-8")
        backup = project / ".mix-backup"
        if backup.exists():
            shutil.rmtree(backup)
        if mix_directory.exists():
            os.replace(mix_directory, backup)
        try:
            os.replace(staged, mix_directory)
        except OSError:
            if backup.exists() and not mix_directory.exists():
                os.replace(backup, mix_directory)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    return MixResult(plan, final_audio_path, mix_directory / "mix.json",
                     mix_directory / "mix.txt", safety_gain_db, elapsed)

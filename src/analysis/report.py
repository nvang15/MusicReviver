"""Project-level discovery, atomic report output, and text formatting."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.analysis.analyzer import analyze_audio
from src.analysis.exceptions import AnalysisOutputExistsError
from src.analysis.models import AudioAnalysis
from src.audio.converter import INTERNAL_CHANNELS, INTERNAL_CODEC, INTERNAL_SAMPLE_RATE, convert_media, safe_project_name
from src.audio.metadata import probe_media
from src.config import OUTPUT_DIR, PROJECT_ROOT, TEMP_DIR

SCHEMA_VERSION = "1.0"


def _ensure_source(input_path: Path, output_root: Path, project_root: Path) -> Path:
    source = output_root / safe_project_name(input_path) / "source" / "original_48k.wav"
    if source.exists():
        metadata = probe_media(source)
        if metadata.audio_codec == INTERNAL_CODEC and metadata.sample_rate == INTERNAL_SAMPLE_RATE and metadata.channels == INTERNAL_CHANNELS:
            return source
    return convert_media(input_path, output_root=output_root, project_root=project_root,
                         force=source.exists()).audio_path


def discover_stems(project_directory: Path) -> dict[str, Path]:
    """Discover arbitrary canonical WAV stems without assuming a fixed model set."""
    stems_directory = project_directory / "stems"
    if not stems_directory.is_dir():
        return {}
    return {path.stem: path for path in sorted(stems_directory.glob("*.wav")) if path.is_file()}


def _number(value: float | None, suffix: str = "", digits: int = 2) -> str:
    return "unavailable" if value is None else f"{value:.{digits}f}{suffix}"


def render_text_report(project: str, source: AudioAnalysis, stems: dict[str, AudioAnalysis]) -> str:
    """Render a neutral, human-readable measurement report."""
    lines = ["MusicReviver Audio Analysis", "============================", "", "Source", "------"]
    lines.extend([
        f"Duration: {_number(source.duration_seconds, ' s')}",
        f"Integrated loudness: {_number(source.integrated_lufs, ' LUFS')}",
        f"Peak: {_number(source.peak_dbfs, ' dBFS')}",
        f"RMS: {_number(source.rms_dbfs, ' dBFS')}",
        f"Crest factor: {_number(source.crest_factor_db, ' dB')}",
        f"Dynamic range estimate: {_number(source.dynamic_range_estimate_db, ' dB')}",
        f"Stereo correlation: {_number(source.stereo_correlation)}",
        f"Estimated noise floor: {_number(source.estimated_noise_floor_dbfs, ' dBFS')}",
        "", "Spectrum", "--------",
    ])
    for name, fraction in source.band_energy_fractions.items():
        lines.append(f"{name.replace('_', ' ').title()}: {fraction * 100.0:.2f}%")
    lines.extend(["", f"Estimated tempo: {_number(source.tempo_bpm, ' BPM', 1)}"])
    key = source.key_estimate
    lines.append(
        "Estimated key: unavailable" if key is None
        else f"Estimated key: {key.tonic} {key.mode} (confidence {key.confidence:.2f})"
    )
    if stems:
        lines.extend(["", "Stems", "-----"])
        for name, result in stems.items():
            lines.extend([
                f"{name}:",
                f"  Loudness: {_number(result.integrated_lufs, ' LUFS')}",
                f"  Peak: {_number(result.peak_dbfs, ' dBFS')}",
                f"  RMS: {_number(result.rms_dbfs, ' dBFS')}",
                f"  Dynamic range estimate: {_number(result.dynamic_range_estimate_db, ' dB')}",
            ])
    return "\n".join(lines) + "\n"


def analyze_project(input_path: Path, *, force: bool = False, output_root: Path = OUTPUT_DIR,
                    project_root: Path = PROJECT_ROOT, temp_root: Path = TEMP_DIR) -> tuple[dict[str, Any], Path, Path]:
    """Import as needed, analyze source and existing stems, and atomically publish reports."""
    input_path = Path(input_path)
    project_name = safe_project_name(input_path)
    project_directory = output_root / project_name
    analysis_directory = project_directory / "analysis"
    if analysis_directory.exists() and not force:
        raise AnalysisOutputExistsError(
            f"Analysis output already exists: {analysis_directory}. Use --force to replace it."
        )
    source_path = _ensure_source(input_path, output_root, project_root)
    source = analyze_audio(source_path, logical_name="source", full_mix=True)
    stem_results = {
        name: analyze_audio(path, logical_name=name, full_mix=False)
        for name, path in discover_stems(project_directory).items()
    }
    warnings = list(source.warnings)
    for name, result in stem_results.items():
        warnings.extend(f"{name}: {warning}" for warning in result.warnings)
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project": project_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_path": source_path.resolve().relative_to(project_root.resolve()).as_posix(),
        "source": source.to_dict(),
        "stems": {name: result.to_dict() for name, result in stem_results.items()},
        "warnings": warnings,
    }
    temp_root.mkdir(parents=True, exist_ok=True)
    project_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="musicreviver-analysis-", dir=temp_root) as temporary:
        staged = Path(temporary) / "analysis"
        staged.mkdir()
        json_path = staged / "analysis.json"
        text_path = staged / "analysis.txt"
        json_path.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        text_path.write_text(render_text_report(project_name, source, stem_results), encoding="utf-8")
        backup = project_directory / ".analysis-backup"
        if backup.exists():
            shutil.rmtree(backup)
        if analysis_directory.exists():
            os.replace(analysis_directory, backup)
        try:
            os.replace(staged, analysis_directory)
        except OSError:
            if backup.exists() and not analysis_directory.exists():
                os.replace(backup, analysis_directory)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    return document, analysis_directory / "analysis.json", analysis_directory / "analysis.txt"

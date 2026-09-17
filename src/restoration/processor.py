"""Project-level restoration planning, staged processing, and reporting."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.analysis.report import analyze_project, discover_stems
from src.audio.converter import safe_project_name
from src.audio.metadata import probe_media
from src.config import OUTPUT_DIR, PROJECT_ROOT, TEMP_DIR
from src.restoration.dsp import process_audio
from src.restoration.exceptions import NoStemsError, RestorationError, RestorationOutputExistsError, RestorationProcessingError
from src.restoration.models import RestorationPlan, RestorationStrength
from src.restoration.planner import plan_all

SCHEMA_VERSION = "1.0"


def _load_analysis(input_path: Path, output_root: Path, project_root: Path,
                   temp_root: Path) -> tuple[dict[str, Any], Path]:
    project_directory = output_root / safe_project_name(input_path)
    analysis_path = project_directory / "analysis" / "analysis.json"
    if not analysis_path.is_file():
        analyze_project(input_path, output_root=output_root, project_root=project_root,
                        temp_root=temp_root)
    try:
        return json.loads(analysis_path.read_text(encoding="utf-8")), analysis_path
    except (OSError, json.JSONDecodeError) as exc:
        raise RestorationError(f"Could not load analysis report: {exc}") from exc


def _plan_document(input_path: Path, strength: RestorationStrength, output_root: Path,
                   project_root: Path, temp_root: Path) -> tuple[dict[str, Any], dict[str, RestorationPlan], Path]:
    project_name = safe_project_name(input_path)
    project_directory = output_root / project_name
    analysis, analysis_path = _load_analysis(input_path, output_root, project_root, temp_root)
    stems = discover_stems(project_directory)
    if not stems:
        raise NoStemsError(
            "No canonical stems were found. Run stem separation first; restoration does not start AI separation automatically."
        )
    analyzed_stems = analysis.get("stems", {})
    missing = sorted(set(stems) - set(analyzed_stems))
    if missing:
        raise RestorationError(
            "Analysis is missing discovered stem(s): " + ", ".join(missing) + ". Re-run analysis with --force."
        )
    plans = plan_all({name: analyzed_stems[name] for name in stems}, strength)
    document = {
        "schema_version": SCHEMA_VERSION,
        "project": project_name,
        "restoration_strength": strength.value,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_path": analysis_path.resolve().relative_to(project_root.resolve()).as_posix(),
        "input_stems": {
            name: path.resolve().relative_to(project_root.resolve()).as_posix()
            for name, path in stems.items()
        },
        "plans": {name: plan.to_dict() for name, plan in plans.items()},
    }
    return document, plans, project_directory


def _render_plan_text(document: dict[str, Any]) -> str:
    lines = ["MusicReviver Restoration Plan", "=============================", "",
             f"Project: {document['project']}", f"Strength: {document['restoration_strength']}"]
    for name, plan in document["plans"].items():
        lines.extend(["", name, "-" * len(name), f"Bypass: {'YES' if plan['bypass'] else 'NO'}"])
        for action in plan["actions"]:
            lines.append(f"- {action['type']}: {action['reason']}")
        for warning in plan["warnings"]:
            lines.append(f"! {warning['code']}: {warning['message']}")
    return "\n".join(lines) + "\n"


def write_restoration_plan(input_path: Path, *, strength: RestorationStrength,
                           force: bool = False, output_root: Path = OUTPUT_DIR,
                           project_root: Path = PROJECT_ROOT, temp_root: Path = TEMP_DIR) -> tuple[dict[str, Any], Path, Path]:
    """Generate plan reports without processing any audio."""
    document, _, project_directory = _plan_document(
        Path(input_path), strength, output_root, project_root, temp_root
    )
    restored = project_directory / "restored"
    json_path, text_path = restored / "restoration_plan.json", restored / "restoration_plan.txt"
    if (json_path.exists() or text_path.exists()) and not force:
        raise RestorationOutputExistsError(
            f"Restoration plan already exists in {restored}. Use --force to replace it."
        )
    restored.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="musicreviver-plan-", dir=temp_root) as temporary:
        staged_json, staged_text = Path(temporary) / json_path.name, Path(temporary) / text_path.name
        staged_json.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        staged_text.write_text(_render_plan_text(document), encoding="utf-8")
        os.replace(staged_json, json_path)
        os.replace(staged_text, text_path)
    return document, json_path, text_path


def restore_project(input_path: Path, *, strength: RestorationStrength,
                    force: bool = False, output_root: Path = OUTPUT_DIR,
                    project_root: Path = PROJECT_ROOT, temp_root: Path = TEMP_DIR) -> tuple[dict[str, Any], Path, Path]:
    """Plan, process, validate, and atomically publish every discovered stem."""
    input_path = Path(input_path)
    plan_document, plans, project_directory = _plan_document(
        input_path, strength, output_root, project_root, temp_root
    )
    final_directory = project_directory / "restored"
    if ((final_directory / "restoration.json").exists()
            or any(final_directory.glob("*_restored.wav"))) and not force:
        raise RestorationOutputExistsError(
            f"Restored output already exists: {final_directory}. Use --force to replace it."
        )
    stems = discover_stems(project_directory)
    temp_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="musicreviver-restoration-", dir=temp_root) as temporary:
        staged = Path(temporary) / "restored"
        staged.mkdir()
        results: dict[str, Any] = {}
        for name, source_path in stems.items():
            destination = staged / f"{name}_restored.wav"
            before = probe_media(source_path)
            safety = process_audio(source_path, destination, plans[name])
            after = probe_media(destination)
            if after.audio_codec != "pcm_s24le" or after.sample_rate != 48_000 or after.channels != 2:
                raise RestorationProcessingError(f"Restored stem failed canonical format validation: {destination.name}")
            tolerance = max(0.05, (before.duration_seconds or 0.0) * 0.001)
            if before.duration_seconds is not None and after.duration_seconds is not None and abs(before.duration_seconds - after.duration_seconds) > tolerance:
                raise RestorationProcessingError(f"Restored stem duration changed unexpectedly: {destination.name}")
            results[name] = {
                "input": source_path.resolve().relative_to(project_root.resolve()).as_posix(),
                "output": (final_directory / destination.name).resolve().relative_to(project_root.resolve()).as_posix(),
                "bypass": plans[name].bypass,
                "actions_applied": safety["actions_applied"],
                "before_metrics": plans[name].source_analysis,
                "after_safety_metrics": {
                    "codec": after.audio_codec, "sample_rate": after.sample_rate,
                    "channels": after.channels, "duration_seconds": after.duration_seconds,
                    "peak_amplitude": safety["peak_after_processing"],
                    "clipped": bool(float(safety["peak_after_processing"]) >= 1.0),
                    "peak_protection_applied": safety["peak_protection_applied"],
                },
            }
        elapsed = time.perf_counter() - started
        warnings = [warning.to_dict() if hasattr(warning, "to_dict") else {"code": warning.code, "message": warning.message}
                    for plan in plans.values() for warning in plan.warnings]
        document = {
            **plan_document,
            "processing_duration_seconds": elapsed,
            "output_format": {"container": "wav", "codec": "pcm_s24le", "sample_rate": 48000, "channels": 2},
            "results": results,
            "warnings": warnings,
        }
        (staged / "restoration.json").write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        (staged / "restoration.txt").write_text(_render_plan_text(document), encoding="utf-8")
        backup = project_directory / ".restored-backup"
        if backup.exists():
            shutil.rmtree(backup)
        if final_directory.exists():
            os.replace(final_directory, backup)
        try:
            os.replace(staged, final_directory)
        except OSError:
            if backup.exists() and not final_directory.exists():
                os.replace(backup, final_directory)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    return document, final_directory / "restoration.json", final_directory / "restoration.txt"

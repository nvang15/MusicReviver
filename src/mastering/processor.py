"""Mix discovery, mastering execution, validation, and atomic publication."""

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

from src.audio.converter import INTERNAL_CHANNELS, INTERNAL_CODEC, INTERNAL_SAMPLE_RATE, safe_project_name
from src.audio.metadata import MediaImportError, probe_media
from src.config import OUTPUT_DIR, PROJECT_ROOT, TEMP_DIR
from src.mastering.dsp import attenuation_peak_protection, broad_eq, linked_compressor
from src.mastering.exceptions import (MasteringError, MasteringSafetyError,
                                      MasterOutputExistsError, NoMixError)
from src.mastering.metrics import mastering_metrics
from src.mastering.models import (MasteringMode, MasteringPlan, MasteringResult,
                                  MasteringWarning)
from src.mastering.planner import POLICIES, create_mastering_plan
from src.mastering.report import render_master_report

SCHEMA_VERSION = "1.0"


def discover_mix(input_path: Path, *, output_root: Path = OUTPUT_DIR) -> Path:
    """Locate and validate the published Milestone 6 mix without running any stage."""
    project = output_root / safe_project_name(Path(input_path))
    mix_dir = project / "mix"
    metadata_path = mix_dir / "mix.json"
    if not metadata_path.is_file():
        raise NoMixError("No valid Milestone 6 mix exists. Run 'python app.py mix <input>' first; mastering does not run earlier stages.")
    try:
        document = json.loads(metadata_path.read_text(encoding="utf-8"))
        relative = document.get("output_path")
        candidates = [mix_dir / "restored_mix.wav", mix_dir / "separated_mix.wav"]
        mix_path = next((path for path in candidates if path.is_file()), None)
        if relative:
            described = PROJECT_ROOT / Path(relative)
            if described.is_file() and described.parent == mix_dir.resolve():
                mix_path = described
        if mix_path is None:
            raise ValueError("reported mix audio is missing")
        info = sf.info(mix_path)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise NoMixError(f"The Milestone 6 mix is invalid: {exc}") from exc
    if info.samplerate != INTERNAL_SAMPLE_RATE or info.channels != INTERNAL_CHANNELS or info.subtype != "PCM_24":
        raise NoMixError("The Milestone 6 mix is not canonical 48 kHz, stereo, 24-bit PCM.")
    return mix_path


def _load_mix(path: Path) -> np.ndarray:
    try:
        audio, rate = sf.read(path, dtype="float64", always_2d=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise NoMixError(f"Could not read mix '{path.name}': {exc}") from exc
    if rate != INTERNAL_SAMPLE_RATE or audio.shape[1] != INTERNAL_CHANNELS or not audio.size or not np.all(np.isfinite(audio)):
        raise NoMixError("The source mix contains invalid or non-canonical audio.")
    return audio


def plan_mastering(input_path: Path, *, mode: MasteringMode = MasteringMode.BALANCED,
                   output_root: Path = OUTPUT_DIR) -> MasteringPlan:
    mix_path = discover_mix(input_path, output_root=output_root)
    audio = _load_mix(mix_path)
    return create_mastering_plan(mix_path, mastering_metrics(audio, INTERNAL_SAMPLE_RATE), mode)


def _execute(audio: np.ndarray, plan: MasteringPlan) -> tuple[np.ndarray, float]:
    working = audio.astype(np.float64, copy=True)
    for action in plan.actions:
        parameters = action.parameters
        if action.type == "broad_eq":
            working = broad_eq(working, INTERNAL_SAMPLE_RATE,
                               frequency_hz=float(parameters["frequency_hz"]),
                               gain_db=float(parameters["gain_db"]), q=float(parameters["q"]))
        elif action.type == "bus_compression":
            working = linked_compressor(working, INTERNAL_SAMPLE_RATE,
                                        threshold_dbfs=float(parameters["threshold_dbfs"]),
                                        ratio=float(parameters["ratio"]),
                                        attack_ms=float(parameters["attack_ms"]),
                                        release_ms=float(parameters["release_ms"]))
        elif action.type == "global_gain":
            working *= 10.0 ** (float(parameters["gain_db"]) / 20.0)
        else:
            raise MasteringError(f"Unsupported mastering action: {action.type}")
    return attenuation_peak_protection(working, plan.peak_ceiling_dbfs)


def master_project(input_path: Path, *, mode: MasteringMode = MasteringMode.BALANCED,
                   force: bool = False, output_root: Path = OUTPUT_DIR,
                   project_root: Path = PROJECT_ROOT, temp_root: Path = TEMP_DIR) -> MasteringResult:
    """Plan and atomically publish one canonical preservation-first master."""
    input_path = Path(input_path)
    project_name = safe_project_name(input_path)
    project = output_root / project_name
    mix_path = discover_mix(input_path, output_root=output_root)
    audio = _load_mix(mix_path)
    master_dir = project / "master"
    if master_dir.exists() and not force:
        raise MasterOutputExistsError(f"Master output already exists: {master_dir}. Use --force to replace it.")
    plan = create_mastering_plan(mix_path, mastering_metrics(audio, INTERNAL_SAMPLE_RATE), mode)
    started = time.perf_counter()
    processed, reduction = _execute(audio, plan)
    if not np.all(np.isfinite(processed)):
        raise MasteringSafetyError("Mastering produced NaN or infinite samples.")
    ceiling = 10.0 ** (plan.peak_ceiling_dbfs / 20.0)
    if float(np.max(np.abs(processed))) > ceiling + 1e-9:
        raise MasteringSafetyError("Mastering exceeded the configured sample-peak ceiling.")
    warnings = list(plan.warnings)
    policy = POLICIES[mode]
    if reduction > 0.0:
        warnings.append(MasteringWarning("peak_protection_applied", "Attenuation-only sample-peak protection was applied."))
    if reduction > policy.max_planned_limiting_db:
        warnings.append(MasteringWarning("significant_peak_reduction", "Peak protection exceeded the conservative mode allowance; output loudness was allowed to remain below guidance."))
    elapsed = time.perf_counter() - started
    output_metrics = mastering_metrics(processed, INTERNAL_SAMPLE_RATE)
    output_name = f"{mode.value}_master.wav"
    audio_path = master_dir / output_name
    try:
        source_display = mix_path.resolve().relative_to(project_root.resolve()).as_posix()
        output_display = audio_path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        source_display, output_display = mix_path.as_posix(), audio_path.as_posix()
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "project": project_name,
        "mode": mode.value, "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_mix": source_display, "source_metrics": plan.source_metrics,
        "actions": [a.__dict__ for a in plan.actions],
        "target_loudness_range_lufs": list(plan.target_loudness_range_lufs),
        "actual_output_loudness_lufs": output_metrics["integrated_lufs"],
        "peak_ceiling_dbfs": plan.peak_ceiling_dbfs,
        "peak_measurement": "sample_peak",
        "actual_peak_dbfs": output_metrics["peak_dbfs"],
        "safety_limiting_gain_reduction_db": reduction,
        "warnings": [w.__dict__ for w in warnings], "reasoning": list(plan.reasoning),
        "bypass": {"eq": plan.bypass_eq, "compression": plan.bypass_compression, "gain": plan.bypass_gain},
        "processing_duration_seconds": elapsed, "output_metrics": output_metrics,
        "output_format": {"container": "wav", "codec": INTERNAL_CODEC,
                          "sample_rate": INTERNAL_SAMPLE_RATE, "channels": INTERNAL_CHANNELS},
        "output_path": output_display,
    }
    temp_root.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="musicreviver-master-", dir=temp_root) as temporary:
        staged = Path(temporary) / "master"
        staged.mkdir()
        staged_audio = staged / output_name
        try:
            sf.write(staged_audio, processed, INTERNAL_SAMPLE_RATE, format="WAV", subtype="PCM_24")
            info = sf.info(staged_audio)
            if info.samplerate != INTERNAL_SAMPLE_RATE or info.channels != INTERNAL_CHANNELS or info.subtype != "PCM_24" or info.frames != audio.shape[0]:
                raise MasteringSafetyError("Rendered master failed format or duration validation.")
            (staged / "master.json").write_text(json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            (staged / "master.txt").write_text(render_master_report(document), encoding="utf-8")
        except (OSError, RuntimeError, ValueError) as exc:
            raise MasteringError(f"Could not write staged master: {exc}") from exc
        backup = project / ".master-backup"
        if backup.exists():
            shutil.rmtree(backup)
        if master_dir.exists():
            os.replace(master_dir, backup)
        try:
            os.replace(staged, master_dir)
        except OSError:
            if backup.exists() and not master_dir.exists():
                os.replace(backup, master_dir)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    final_plan = MasteringPlan(plan.mode, plan.source_file, plan.source_metrics, plan.actions,
                               plan.target_loudness_range_lufs, plan.peak_ceiling_dbfs,
                               tuple(warnings), plan.reasoning, plan.bypass_eq,
                               plan.bypass_compression, plan.bypass_gain)
    return MasteringResult(final_plan, audio_path, master_dir / "master.json",
                           master_dir / "master.txt", reduction, elapsed, output_metrics)

"""Conservative execution of explicit restoration actions."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard import Compressor, HighpassFilter, Limiter, Pedalboard

from src.restoration.exceptions import RestorationProcessingError
from src.restoration.models import RestorationPlan


def process_audio(input_path: Path, output_path: Path, plan: RestorationPlan) -> dict[str, object]:
    """Execute a plan and write canonical PCM-24 WAV, preserving duration."""
    try:
        audio, sample_rate = sf.read(input_path, dtype="float32", always_2d=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RestorationProcessingError(f"Could not read stem '{input_path.name}': {exc}") from exc
    if sample_rate != 48_000 or audio.shape[1] != 2 or audio.size == 0:
        raise RestorationProcessingError(
            f"Stem must be canonical 48 kHz stereo audio: {input_path.name}"
        )
    if not np.all(np.isfinite(audio)):
        raise RestorationProcessingError(f"Stem contains non-finite samples: {input_path.name}")

    working = audio.T.copy()
    plugins = []
    applied: list[dict[str, object]] = []
    for action in plan.actions:
        parameters = action.parameters
        if action.type == "dc_offset_removal":
            working -= np.mean(working, axis=1, keepdims=True)
        elif action.type == "high_pass_filter":
            plugins.append(HighpassFilter(cutoff_frequency_hz=parameters["frequency_hz"]))
        elif action.type == "gentle_compression":
            plugins.append(Compressor(
                threshold_db=parameters["threshold_db"], ratio=parameters["ratio"],
                attack_ms=parameters["attack_ms"], release_ms=parameters["release_ms"],
            ))
        else:
            raise RestorationProcessingError(f"Unsupported restoration action: {action.type}")
        applied.append(action.to_dict() if hasattr(action, "to_dict") else {
            "type": action.type, "parameters": action.parameters, "reason": action.reason
        })
    if plugins:
        working = Pedalboard(plugins)(working, sample_rate)

    peak_before_protection = float(np.max(np.abs(working)))
    peak_protection = False
    if peak_before_protection >= 0.999:
        working = Pedalboard([Limiter(threshold_db=-0.5, release_ms=100.0)])(working, sample_rate)
        peak_protection = True
        applied.append({
            "type": "peak_protection", "parameters": {"threshold_db": -0.5},
            "reason": "Planned processing would otherwise approach or exceed digital full scale.",
        })
    peak_after = float(np.max(np.abs(working)))
    if not np.all(np.isfinite(working)) or peak_after > 1.0:
        raise RestorationProcessingError(f"Unsafe processed samples for stem: {input_path.name}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        sf.write(output_path, working.T, sample_rate, format="WAV", subtype="PCM_24")
    except (OSError, RuntimeError, ValueError) as exc:
        raise RestorationProcessingError(f"Could not write restored stem '{output_path.name}': {exc}") from exc
    return {
        "actions_applied": applied,
        "peak_before_protection": peak_before_protection,
        "peak_after_processing": peak_after,
        "peak_protection_applied": peak_protection,
        "frames": int(working.shape[1]),
    }

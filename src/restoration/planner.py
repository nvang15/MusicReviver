"""Deterministic, analysis-driven conservative restoration planning."""

from __future__ import annotations

from typing import Any

from src.restoration.models import RestorationAction, RestorationPlan, RestorationStrength, RestorationWarning
from src.restoration.presets import get_preset


def plan_restoration(target_name: str, analysis: dict[str, Any],
                     strength: RestorationStrength = RestorationStrength.BALANCED) -> RestorationPlan:
    """Build an explicit plan from existing analysis without inspecting audio again."""
    preset = get_preset(strength)
    target_type = target_name.strip().lower()
    actions: list[RestorationAction] = []
    warnings: list[RestorationWarning] = []
    reasoning: list[str] = []

    dc_offset = abs(float(analysis.get("dc_offset") or 0.0))
    if dc_offset > preset.dc_offset_threshold:
        actions.append(RestorationAction(
            "dc_offset_removal", {},
            f"Measured absolute DC offset {dc_offset:.6f} exceeded the {strength.value} threshold {preset.dc_offset_threshold:.6f}.",
        ))
    else:
        reasoning.append("Measured DC offset remained below the selected correction threshold.")

    sub_fraction = float((analysis.get("band_energy_fractions") or {}).get("sub") or 0.0)
    high_pass_frequency = preset.high_pass_frequencies.get(target_type, preset.high_pass_frequencies["other"])
    if sub_fraction > preset.sub_energy_threshold:
        actions.append(RestorationAction(
            "high_pass_filter",
            {"frequency_hz": high_pass_frequency, "slope_db_per_octave": 12.0},
            f"Measured 20–60 Hz energy fraction {sub_fraction:.4f} exceeded the {strength.value} threshold {preset.sub_energy_threshold:.4f}.",
        ))
    else:
        reasoning.append("Measured sub-band energy did not justify automatic high-pass filtering.")

    dynamic_range = analysis.get("dynamic_range_estimate_db")
    crest = analysis.get("crest_factor_db")
    if (dynamic_range is not None and crest is not None
            and float(dynamic_range) > preset.compression_dynamic_range_threshold_db
            and float(crest) > preset.compression_crest_threshold_db):
        rms_dbfs = float(analysis.get("rms_dbfs") or -24.0)
        actions.append(RestorationAction(
            "gentle_compression",
            {"threshold_db": min(-6.0, rms_dbfs + 8.0), "ratio": preset.compression_ratio,
             "attack_ms": 30.0 if target_type == "drums" else 20.0, "release_ms": 150.0},
            f"Dynamic-range estimate {float(dynamic_range):.2f} dB and crest factor {float(crest):.2f} dB both exceeded conservative {strength.value} thresholds.",
        ))
    else:
        reasoning.append("Dynamics did not satisfy both conservative compression conditions.")

    if int(analysis.get("clipped_sample_count") or 0) > 0:
        warnings.append(RestorationWarning(
            "clipping_detected",
            "Clipping detected; automatic de-clipping is not implemented in the current restoration engine.",
        ))
    noise_floor = analysis.get("estimated_noise_floor_dbfs")
    if noise_floor is not None and float(noise_floor) > -35.0:
        warnings.append(RestorationWarning(
            "elevated_noise_floor_estimate",
            "The estimated noise floor is elevated; no automatic gate or neural denoising is applied.",
        ))
    correlation = analysis.get("stereo_correlation")
    if correlation is not None and float(correlation) < -0.50:
        warnings.append(RestorationWarning(
            "negative_stereo_correlation",
            "Strong negative stereo correlation was measured; stereo width is left unchanged.",
        ))

    return RestorationPlan(
        target_name=target_name,
        target_type=target_type,
        restoration_strength=strength,
        actions=tuple(actions),
        warnings=tuple(warnings),
        reasoning=tuple(reasoning),
        bypass=not actions,
        source_analysis=analysis,
    )


def plan_all(stem_analyses: dict[str, dict[str, Any]], strength: RestorationStrength) -> dict[str, RestorationPlan]:
    """Plan any discovered stem set without assuming six sources."""
    return {name: plan_restoration(name, analysis, strength) for name, analysis in stem_analyses.items()}

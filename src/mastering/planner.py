"""Measurement-driven, bounded mastering planning."""

from __future__ import annotations

from pathlib import Path

from src.mastering.models import (MasteringAction, MasteringMode, MasteringPlan,
                                  MasteringWarning, ModePolicy)

POLICIES = {
    MasteringMode.ARCHIVAL: ModePolicy((-20.0, -16.0), -1.5, 1.0, 0.5, 1.2, 15.0, 11.0, 0.5),
    MasteringMode.BALANCED: ModePolicy((-16.0, -13.0), -1.0, 3.0, 1.0, 1.5, 13.0, 9.0, 1.5),
    MasteringMode.MODERN: ModePolicy((-13.0, -10.0), -0.8, 5.0, 1.5, 1.8, 11.0, 7.0, 2.0),
}


def create_mastering_plan(source_file: Path, metrics: dict[str, object],
                          mode: MasteringMode = MasteringMode.BALANCED) -> MasteringPlan:
    policy = POLICIES[mode]
    actions: list[MasteringAction] = []
    warnings: list[MasteringWarning] = []
    reasoning: list[str] = []
    loudness = metrics.get("integrated_lufs")
    peak_db = metrics.get("peak_dbfs")
    crest = metrics.get("crest_factor_db")
    dynamic = metrics.get("dynamic_range_estimate_db")
    bands = metrics.get("band_energy_fractions") or {}

    if metrics.get("clipped_sample_count", 0):
        warnings.append(MasteringWarning("source_clipping", "The source mix contains samples near digital full scale; no de-clipping is attempted."))
    correlation = metrics.get("stereo_correlation")
    if correlation is not None and float(correlation) < 0.0:
        warnings.append(MasteringWarning("negative_stereo_correlation", "Negative stereo correlation was measured; stereo width and timing are unchanged."))

    # Broad cuts only. Thresholds rise for more preservation-oriented modes.
    low_mid = float(bands.get("low_mid", 0.0))
    bass = float(bands.get("bass", 0.0))
    high = float(bands.get("high", 0.0))
    threshold_shift = {MasteringMode.ARCHIVAL: 0.05, MasteringMode.BALANCED: 0.02, MasteringMode.MODERN: 0.0}[mode]
    if low_mid > 0.29 + threshold_shift:
        gain = -min(policy.max_eq_gain_db, 0.4 + (low_mid - 0.29) * 5.0)
        actions.append(MasteringAction("broad_eq", {"frequency_hz": 350.0, "gain_db": gain, "q": 0.7}, "Measured low-mid energy exceeded the mode threshold."))
    elif bass > 0.58 + threshold_shift:
        gain = -min(policy.max_eq_gain_db, 0.4 + (bass - 0.58) * 4.0)
        actions.append(MasteringAction("broad_eq", {"frequency_hz": 120.0, "gain_db": gain, "q": 0.7}, "Measured bass energy exceeded the mode threshold."))
    elif high > 0.32 + threshold_shift:
        gain = -min(policy.max_eq_gain_db, 0.35 + (high - 0.32) * 4.0)
        actions.append(MasteringAction("broad_eq", {"frequency_hz": 8500.0, "gain_db": gain, "q": 0.65}, "Measured high-frequency energy exceeded the mode threshold."))

    already_limited = crest is not None and float(crest) < 8.0
    if already_limited:
        warnings.append(MasteringWarning("already_compressed", "Low crest factor indicates limited material; additional bus compression was bypassed."))
    if (mode is not MasteringMode.ARCHIVAL and not already_limited and crest is not None and dynamic is not None
            and float(crest) >= policy.compression_threshold_crest_db
            and float(dynamic) >= policy.compression_threshold_dynamic_db):
        ratio = 1.35 if mode is MasteringMode.BALANCED else 1.65
        actions.append(MasteringAction("bus_compression", {
            "threshold_dbfs": -18.0 if mode is MasteringMode.BALANCED else -20.0,
            "ratio": min(ratio, policy.max_compression_ratio), "attack_ms": 30.0,
            "release_ms": 180.0 if mode is MasteringMode.BALANCED else 140.0,
        }, "Crest factor and dynamic-range estimate permit light linked-stereo bus control."))

    if loudness is None or peak_db is None:
        warnings.append(MasteringWarning("gain_unavailable", "Loudness or peak measurement was unavailable; automatic gain was bypassed."))
    elif float(loudness) < policy.loudness_range_lufs[0]:
        requested = policy.loudness_range_lufs[0] - float(loudness)
        headroom = policy.peak_ceiling_dbfs - float(peak_db)
        gain = max(0.0, min(requested, policy.max_gain_boost_db, headroom))
        if gain > 0.01:
            actions.append(MasteringAction("global_gain", {"gain_db": gain}, "Source loudness was below the guidance range and peak headroom allowed a bounded increase."))
        if requested > gain + 0.01:
            warnings.append(MasteringWarning("loudness_target_not_forced", "The target range was not forced because gain or peak-headroom limits took priority."))
    else:
        reasoning.append("No gain boost: source loudness is already within or above the guidance range.")

    reasoning.append("Loudness range is guidance; preservation and the sample-peak ceiling take priority.")
    return MasteringPlan(mode, Path(source_file), metrics, tuple(actions),
                         policy.loudness_range_lufs, policy.peak_ceiling_dbfs,
                         tuple(warnings), tuple(reasoning),
                         not any(a.type == "broad_eq" for a in actions),
                         not any(a.type == "bus_compression" for a in actions),
                         not any(a.type == "global_gain" for a in actions))

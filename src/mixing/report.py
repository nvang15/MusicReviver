"""Readable non-subjective mix report formatting."""

from __future__ import annotations

from typing import Any


def _number(value: float | None, suffix: str = "") -> str:
    return "unavailable" if value is None else f"{value:.2f}{suffix}"


def render_mix_report(document: dict[str, Any]) -> str:
    lines = [
        "MusicReviver Mix Report", "=======================", "",
        "Stem Source", "-----------", document["stem_source"].title(), "",
        "Stem Gains", "----------",
    ]
    for setting in document["gain_settings"]:
        lines.append(f"{setting['stem']}: {setting['gain_db']:+.2f} dB")
    reference = document["reference_metrics"]
    final = document["final_mix_metrics"]
    comparison = document["reference_comparison"]
    lines.extend([
        "", "Reference Comparison", "--------------------",
        f"Reference LUFS: {_number(reference['integrated_lufs'], ' LUFS')}",
        f"Final mix LUFS: {_number(final['integrated_lufs'], ' LUFS')}",
        f"Reference peak: {_number(reference['peak_dbfs'], ' dBFS')}",
        f"Final mix peak: {_number(final['peak_dbfs'], ' dBFS')}",
        f"RMS difference: {_number(comparison['rms_difference_db'], ' dB')}",
        f"Waveform correlation: {_number(comparison['waveform_correlation'])}",
        "", "Safety", "------",
        f"Safety attenuation: {document['safety_gain_db']:.2f} dB",
        f"Clipping: {'YES' if document['clipping'] else 'NO'}",
        "", "Warnings", "--------",
    ])
    warnings = document["warnings"]
    lines.extend(f"- {warning['code']}: {warning['message']}" for warning in warnings)
    if not warnings:
        lines.append("- None")
    return "\n".join(lines) + "\n"

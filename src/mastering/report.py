"""Readable objective mastering report."""

from __future__ import annotations

from typing import Any


def _number(value: object, suffix: str = "") -> str:
    return "unavailable" if value is None else f"{float(value):.2f}{suffix}"


def render_master_report(document: dict[str, Any]) -> str:
    source, output = document["source_metrics"], document["output_metrics"]
    lines = ["MusicReviver Mastering Report", "=============================", "",
             "Mode", "----", document["mode"].title(), "", "Source", "------",
             f"Integrated loudness: {_number(source['integrated_lufs'], ' LUFS')}",
             f"Sample peak: {_number(source['peak_dbfs'], ' dBFS')}",
             f"Dynamic range estimate: {_number(source['dynamic_range_estimate_db'], ' dB')}",
             "", "Actions", "-------"]
    for action in document["actions"]:
        params = ", ".join(f"{key}={value}" for key, value in action["parameters"].items())
        lines.append(f"{action['type']}: {params} — {action['reason']}")
    if not document["actions"]:
        lines.append("Bypass: no processing was justified.")
    lines.extend(["", "Output", "------",
                  f"Integrated loudness: {_number(output['integrated_lufs'], ' LUFS')}",
                  f"Sample peak: {_number(output['peak_dbfs'], ' dBFS')}",
                  f"Sample-peak ceiling: {document['peak_ceiling_dbfs']:.2f} dBFS",
                  f"Peak-protection gain reduction: {document['safety_limiting_gain_reduction_db']:.2f} dB",
                  "", "Warnings", "--------"])
    lines.extend(f"- {w['code']}: {w['message']}" for w in document["warnings"])
    if not document["warnings"]:
        lines.append("- None")
    return "\n".join(lines) + "\n"

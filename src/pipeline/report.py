"""Human-readable pipeline reporting without subjective claims."""

from __future__ import annotations

from typing import Any


def render_pipeline_report(document: dict[str, Any]) -> str:
    config = document["configuration"]
    lines = ["MusicReviver Pipeline Report", "============================", "",
             "Input", "-----", document["input_identity"]["path"], "",
             "Configuration", "-------------",
             f"Separation model: {config['separation_model']}",
             f"Device: {config['device_mode']}",
             f"Restoration: {config['restoration_strength']}",
             f"Mastering: {config['mastering_mode']}", "", "Stages", "------"]
    for name, record in document["stages"].items():
        duration = float(record["duration_seconds"])
        lines.append(f"{name.title()}: {record['status'].upper()} ({duration:.2f}s)")
        if record.get("error"):
            lines.append(f"  Error: {record['error']}")
    lines.extend(["", "Final Output", "------------",
                  document.get("final_output") or "unavailable", "",
                  f"Total processing time: {float(document['total_processing_time_seconds']):.2f}s",
                  "", "Warnings", "--------"])
    lines.extend(f"- {warning}" for warning in document.get("warnings", []))
    if not document.get("warnings"):
        lines.append("- None")
    return "\n".join(lines) + "\n"

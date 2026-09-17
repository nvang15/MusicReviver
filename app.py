"""MusicReviver environment, import, separation, and analysis CLI."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.config import PROJECT_DIRECTORIES
from src.audio.converter import convert_media, is_ffmpeg_available, is_ffprobe_available, safe_project_name
from src.audio.metadata import MediaImportError, probe_media
from src.analysis.exceptions import AnalysisError
from src.analysis.report import analyze_project
from src.separation.backends import DeviceMode
from src.separation.diagnostics import collect_diagnostics, format_diagnostics
from src.separation.exceptions import SeparationError
from src.separation.models import DEFAULT_MODEL_ID
from src.separation.separator import prepare_separation, separate
from src.restoration.exceptions import RestorationError
from src.restoration.models import RestorationStrength
from src.restoration.processor import restore_project, write_restoration_plan
from src.mixing.exceptions import MixingError
from src.mixing.mixer import mix_project
from src.mixing.models import MixSource


@dataclass(frozen=True)
class CheckResult:
    """The display name and outcome of one environment check."""

    name: str
    passed: bool
    error: str | None = None


def check_python_version() -> CheckResult:
    """Confirm that the interpreter is the supported Python 3.11 release."""
    version = sys.version_info
    passed = version.major == 3 and version.minor == 11
    error = None if passed else f"Found Python {version.major}.{version.minor}; Python 3.11 is required."
    return CheckResult("Python 3.11", passed, error)


def check_project_directories(
    directories: tuple[Path, ...] = PROJECT_DIRECTORIES,
) -> CheckResult:
    """Confirm that each required project directory exists."""
    missing = [directory.name for directory in directories if not directory.is_dir()]
    error = None if not missing else f"Missing directories: {', '.join(missing)}."
    return CheckResult("Project directories", not missing, error)


def _tool_check(name: str, detector: Callable[[], bool], install_hint: str) -> CheckResult:
    available = detector()
    error = None if available else f"{name} was not found on PATH. {install_hint}"
    return CheckResult(name, available, error)


def run_environment_checks() -> tuple[CheckResult, ...]:
    """Run all startup checks without raising for expected missing tools."""
    return (
        check_python_version(),
        _tool_check("FFmpeg", is_ffmpeg_available, "Install FFmpeg and add its bin directory to PATH."),
        _tool_check("FFprobe", is_ffprobe_available, "FFprobe is normally included with FFmpeg."),
        check_project_directories(),
    )


def run_environment_command() -> int:
    """Print a concise environment report and return a process status code."""
    results = run_environment_checks()
    print("MusicReviver Environment Check\n")
    for result in results:
        print(f"{result.name}: {'PASS' if result.passed else 'FAIL'}")

    failures = [result for result in results if not result.passed]
    if failures:
        print("\nAction required:")
        for failure in failures:
            print(f"- {failure.error}")
        return 1

    print("\nEnvironment is ready for MusicReviver Milestone 1.")
    return 0


def _duration_display(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    total = round(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def run_import_command(path: Path, *, force: bool = False) -> int:
    """Show source metadata and import one media file."""
    print("MusicReviver Media Import\n")
    try:
        metadata = probe_media(path)
        print(f"File: {metadata.filename}")
        print(f"Duration: {_duration_display(metadata.duration_seconds)}")
        print(f"Codec: {metadata.audio_codec or 'unknown'}")
        print(f"Sample Rate: {metadata.sample_rate or 'unknown'} Hz")
        print(f"Channels: {metadata.channels or 'unknown'}")
        print("\nConverting to MusicReviver internal format...")
        result = convert_media(path, force=force)
    except MediaImportError as exc:
        print(f"\nImport failed: {exc}", file=sys.stderr)
        return 1
    print(f"\nOutput:\n{result.audio_path}")
    print("\nConversion: PASS")
    return 0


def run_separation_info_command() -> int:
    """Print optional backend, provider, model, and hardware diagnostics."""
    print(format_diagnostics(collect_diagnostics()))
    return 0


def run_separate_command(
    path: Path,
    *,
    device: str = DeviceMode.AUTO.value,
    model: str = DEFAULT_MODEL_ID,
    force: bool = False,
) -> int:
    """Standardize media and run real AI stem separation."""
    print("MusicReviver Stem Separation\n")
    try:
        request = prepare_separation(path, model_id=model, device=device, force=force)
        print(f"File: {request.input_path.name}")
        print(f"Model: {request.model.identifier}")
        print(f"Standardized source: output/{safe_project_name(request.input_path)}/source/original_48k.wav")
        print("Backend: audio-separator")
        print(f"Requested device: {request.requested_device.value}")
        print(f"Selected device: {request.selected_device.value}")
        print(f"Reason: {request.selection_reason}")
        print("\nLoading model and separating (the model may download on first use)...")
        result = separate(request)
    except (MediaImportError, SeparationError) as exc:
        print(f"Separation unavailable: {exc}", file=sys.stderr)
        return 1
    print(f"\nProcessing duration: {result.processing_duration:.2f} seconds")
    print("Generated:")
    for stem_path in result.stems.values():
        print(f"- {stem_path.name}")
    print("\nSeparation: PASS")
    return 0


def _metric_display(value: object, suffix: str = "", digits: int = 1) -> str:
    return "unavailable" if value is None else f"{float(value):.{digits}f}{suffix}"


def run_analyze_command(path: Path, *, force: bool = False) -> int:
    """Import as needed and analyze the full mix plus existing canonical stems."""
    print("MusicReviver Audio Analysis\n")
    print(f"Input: {path}")
    print(f"Source: output/{safe_project_name(path)}/source/original_48k.wav")
    print("\nAnalyzing source and any existing stems...")
    try:
        document, json_path, text_path = analyze_project(path, force=force)
    except (MediaImportError, AnalysisError) as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 1
    source = document["source"]
    print(f"\nIntegrated loudness: {_metric_display(source['integrated_lufs'], ' LUFS')}")
    print(f"Peak: {_metric_display(source['peak_dbfs'], ' dBFS')}")
    print(f"Dynamic range estimate: {_metric_display(source['dynamic_range_estimate_db'], ' dB')}")
    print(f"Tempo estimate: {_metric_display(source['tempo_bpm'], ' BPM', 0)}")
    key = source["key_estimate"]
    key_text = "unavailable" if key is None else f"{key['tonic']} {key['mode']} (confidence {key['confidence']:.2f})"
    print(f"Key estimate: {key_text}")
    print(f"\nReport:\n{json_path}\n{text_path}")
    print("\nAnalysis: PASS")
    return 0


def run_plan_restoration_command(path: Path, *, strength: str, force: bool = False) -> int:
    """Create analysis-driven plans without altering audio."""
    print("MusicReviver Restoration Plan\n")
    try:
        document, json_path, text_path = write_restoration_plan(
            path, strength=RestorationStrength(strength), force=force
        )
    except (MediaImportError, AnalysisError, RestorationError) as exc:
        print(f"Planning failed: {exc}", file=sys.stderr)
        return 1
    print(f"Input: {path}")
    print(f"Strength: {strength}")
    print("Plans:")
    for name, plan in document["plans"].items():
        action_names = ", ".join(action["type"] for action in plan["actions"]) or "bypass"
        print(f"- {name}: {action_names}")
    print(f"\nReport:\n{json_path}\n{text_path}")
    print("\nPlanning: PASS")
    return 0


def run_restore_command(path: Path, *, strength: str, force: bool = False) -> int:
    """Plan and conservatively restore all existing canonical stems."""
    print("MusicReviver Conservative Restoration\n")
    try:
        document, json_path, text_path = restore_project(
            path, strength=RestorationStrength(strength), force=force
        )
    except (MediaImportError, AnalysisError, RestorationError) as exc:
        print(f"Restoration failed: {exc}", file=sys.stderr)
        return 1
    print(f"Input: {path}")
    print(f"Strength: {strength}")
    print("Restored:")
    for name, result in document["results"].items():
        print(f"- {Path(result['output']).name}: {'bypass' if result['bypass'] else 'processed'}")
    print(f"\nProcessing duration: {document['processing_duration_seconds']:.2f} seconds")
    print(f"Report:\n{json_path}\n{text_path}")
    print("\nRestoration: PASS")
    return 0


def run_mix_command(path: Path, *, source: str = MixSource.AUTO.value,
                    force: bool = False) -> int:
    """Create a bounded reference-aware mix from restored or separated stems."""
    print("MusicReviver Mixing / Recombination\n")
    try:
        result = mix_project(path, source=MixSource(source), force=force)
    except (MediaImportError, MixingError) as exc:
        print(f"Mixing failed: {exc}", file=sys.stderr)
        return 1
    print(f"Input: {path}")
    print(f"Stem source: {result.plan.stem_source.value}")
    print("Stem gains:")
    for setting in result.plan.settings:
        print(f"- {setting.stem}: {setting.gain_db:+.2f} dB")
    print(f"Reference fitting: {'PASS' if result.plan.reference_fitting_succeeded else 'UNITY FALLBACK'}")
    print(f"Safety attenuation: {result.safety_gain_db:.2f} dB")
    print(f"Processing duration: {result.processing_duration:.2f} seconds")
    print(f"\nOutput:\n{result.audio_path}")
    print(f"Reports:\n{result.metadata_path}\n{result.text_path}")
    print("\nMixing: PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch CLI commands while retaining the default environment check."""
    parser = argparse.ArgumentParser(description="MusicReviver local audio restoration tools")
    subparsers = parser.add_subparsers(dest="command")
    import_parser = subparsers.add_parser("import", help="import and standardize a media file")
    import_parser.add_argument("path", type=Path, help="audio or video file to import")
    import_parser.add_argument("--force", action="store_true", help="overwrite existing output")
    subparsers.add_parser("separation-info", help="show separation backend diagnostics")
    separate_parser = subparsers.add_parser(
        "separate", help="run AI stem separation"
    )
    separate_parser.add_argument("path", type=Path, help="media file to separate")
    separate_parser.add_argument(
        "--device", choices=[mode.value for mode in DeviceMode], default=DeviceMode.AUTO.value,
        help="model-aware execution device selection",
    )
    separate_parser.add_argument(
        "--model", default=DEFAULT_MODEL_ID, help="registered model filename"
    )
    separate_parser.add_argument(
        "--force", action="store_true", help="replace existing stem output"
    )
    analyze_parser = subparsers.add_parser(
        "analyze", help="measure a source and any existing canonical stems"
    )
    analyze_parser.add_argument("path", type=Path, help="audio or video file to analyze")
    analyze_parser.add_argument("--force", action="store_true", help="replace existing reports")
    for command, help_text in (
        ("plan-restoration", "create analysis-driven restoration plans"),
        ("restore", "conservatively restore existing canonical stems"),
    ):
        restoration_parser = subparsers.add_parser(command, help=help_text)
        restoration_parser.add_argument("path", type=Path, help="original project media path")
        restoration_parser.add_argument(
            "--strength", choices=[item.value for item in RestorationStrength],
            default=RestorationStrength.BALANCED.value,
        )
        restoration_parser.add_argument("--force", action="store_true", help="replace existing output")
    mix_parser = subparsers.add_parser("mix", help="recombine existing stems without mastering")
    mix_parser.add_argument("path", type=Path, help="original project media path")
    mix_parser.add_argument(
        "--source", choices=[item.value for item in MixSource], default=MixSource.AUTO.value,
        help="stem source selection (default: auto prefers restored)",
    )
    mix_parser.add_argument("--force", action="store_true", help="replace existing mix output")
    args = parser.parse_args(argv)
    if args.command == "import":
        return run_import_command(args.path, force=args.force)
    if args.command == "separation-info":
        return run_separation_info_command()
    if args.command == "separate":
        return run_separate_command(
            args.path, device=args.device, model=args.model, force=args.force
        )
    if args.command == "analyze":
        return run_analyze_command(args.path, force=args.force)
    if args.command == "plan-restoration":
        return run_plan_restoration_command(args.path, strength=args.strength, force=args.force)
    if args.command == "restore":
        return run_restore_command(args.path, strength=args.strength, force=args.force)
    if args.command == "mix":
        return run_mix_command(args.path, source=args.source, force=args.force)
    return run_environment_command()


if __name__ == "__main__":
    raise SystemExit(main())

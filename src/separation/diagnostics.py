"""Safe diagnostics for optional separation dependencies and hardware providers."""

from __future__ import annotations

import platform
import importlib.metadata
from dataclasses import dataclass
from pathlib import Path

from src.config import MODEL_DIR, PROJECT_ROOT
from src.separation.backends import (
    directml_available,
    get_onnx_execution_providers,
    is_optional_dependency_installed,
)
from src.separation.models import HTDEMUCS_6S, MODEL_REGISTRY


@dataclass(frozen=True)
class SeparationDiagnostics:
    python: str
    operating_system: str
    architecture: str
    audio_separator_installed: bool
    audio_separator_version: str | None
    onnxruntime_installed: bool
    torch_directml_installed: bool
    onnx_providers: tuple[str, ...]
    directml_available: bool
    detected_models: tuple[str, ...]
    model_cache: Path


def detect_cached_models(model_cache: Path = MODEL_DIR) -> tuple[str, ...]:
    """List local model-like files without loading or downloading anything."""
    if not model_cache.is_dir():
        return ()
    suffixes = {".onnx", ".yaml", ".ckpt", ".pth", ".pt", ".th"}
    return tuple(
        sorted(path.relative_to(model_cache).as_posix() for path in model_cache.rglob("*") if path.is_file() and path.suffix.lower() in suffixes)
    )


def collect_diagnostics(model_cache: Path = MODEL_DIR) -> SeparationDiagnostics:
    """Collect diagnostics without requiring any optional ML package."""
    onnx_installed = is_optional_dependency_installed("onnxruntime")
    providers = get_onnx_execution_providers() if onnx_installed else ()
    audio_separator_installed = is_optional_dependency_installed("audio_separator")
    try:
        audio_separator_version = importlib.metadata.version("audio-separator") if audio_separator_installed else None
    except importlib.metadata.PackageNotFoundError:
        audio_separator_version = None
    return SeparationDiagnostics(
        python=platform.python_version(),
        operating_system=f"{platform.system()} {platform.release()}".strip(),
        architecture=platform.machine() or platform.architecture()[0],
        audio_separator_installed=audio_separator_installed,
        audio_separator_version=audio_separator_version,
        onnxruntime_installed=onnx_installed,
        torch_directml_installed=is_optional_dependency_installed("torch_directml"),
        onnx_providers=providers,
        directml_available=directml_available(providers),
        detected_models=detect_cached_models(model_cache),
        model_cache=model_cache,
    )


def format_diagnostics(report: SeparationDiagnostics) -> str:
    """Format a readable separation diagnostics report."""
    try:
        cache = report.model_cache.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix() + "/"
    except ValueError:
        cache = str(report.model_cache)
    providers = "\n".join(f"- {provider}" for provider in report.onnx_providers) or "- (none)"
    models = "\n".join(f"- {model}" for model in report.detected_models) or "- (none)"
    stems = "\n".join(f"- {stem}" for stem in HTDEMUCS_6S.expected_stems)
    yes_no = lambda value: "YES" if value else "NO"
    compatibility = []
    for model in MODEL_REGISTRY.values():
        compatibility.extend(
            [
                model.filename,
                f"  CPU: {'supported' if 'cpu' in model.supported_devices else 'unsupported'}",
                f"  DirectML: {'supported' if 'directml' in model.supported_devices else 'unsupported'}",
            ]
        )
    return (
        "MusicReviver Separation Diagnostics\n\n"
        f"Python: {report.python}\n"
        f"Operating System: {report.operating_system}\n"
        f"Architecture: {report.architecture}\n\n"
        f"audio-separator installed: {yes_no(report.audio_separator_installed)}\n"
        f"audio-separator version: {report.audio_separator_version or '(not installed)'}\n"
        f"ONNX Runtime installed: {yes_no(report.onnxruntime_installed)}\n\n"
        f"torch-directml installed: {yes_no(report.torch_directml_installed)}\n\n"
        f"Available ONNX execution providers:\n{providers}\n\n"
        f"DirectML available: {yes_no(report.directml_available)}\n\n"
        f"Detected separation models:\n{models}\n\n"
        f"Registered model compatibility:\n{chr(10).join(compatibility)}\n\n"
        f"Configured model cache: {cache}\n"
        f"Default intended model: {HTDEMUCS_6S.identifier}\n\n"
        f"Expected stems:\n{stems}"
    )

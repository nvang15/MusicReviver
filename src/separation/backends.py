"""Backend contracts, optional-dependency detection, and device selection."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Protocol

from src.config import MODEL_DIR
from src.separation.exceptions import BackendUnavailableError, DeviceUnavailableError, SeparationError
from src.separation.models import MODEL_REGISTRY, SeparationModel
from src.separation.stems import StemType

DML_PROVIDER = "DmlExecutionProvider"


class DeviceMode(str, Enum):
    """Requested execution device; WinML can be added without changing callers."""

    AUTO = "auto"
    DIRECTML = "directml"
    CPU = "cpu"


class SeparationBackend(Protocol):
    """Library-independent contract for present and future separator backends."""

    @property
    def name(self) -> str: ...

    @property
    def available(self) -> bool: ...

    @property
    def hardware_provider(self) -> str: ...

    @property
    def supported_models(self) -> tuple[SeparationModel, ...]: ...

    @property
    def supported_stems(self) -> frozenset[StemType]: ...

    @property
    def model_cache(self) -> Path: ...

    def separate(self, input_path: Path, output_directory: Path, model: SeparationModel) -> dict[StemType, Path]: ...


def is_optional_dependency_installed(module_name: str) -> bool:
    """Check an optional dependency without importing it."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def get_onnx_execution_providers() -> tuple[str, ...]:
    """Return actual ONNX Runtime providers, or an empty tuple when unavailable."""
    if not is_optional_dependency_installed("onnxruntime"):
        return ()
    try:
        runtime = importlib.import_module("onnxruntime")
        providers = runtime.get_available_providers()
    except (ImportError, AttributeError, RuntimeError):
        return ()
    return tuple(str(provider) for provider in providers)


def directml_available(providers: tuple[str, ...] | None = None) -> bool:
    """Return true only when ONNX Runtime reports the DirectML provider."""
    actual_providers = providers if providers is not None else get_onnx_execution_providers()
    return DML_PROVIDER in actual_providers


def select_device(
    requested: DeviceMode | str,
    *,
    model: SeparationModel | None = None,
    providers: tuple[str, ...] | None = None,
) -> DeviceMode:
    """Resolve model-aware device selection without silent GPU fallback."""
    try:
        mode = requested if isinstance(requested, DeviceMode) else DeviceMode(requested)
    except ValueError as exc:
        choices = ", ".join(mode.value for mode in DeviceMode)
        raise DeviceUnavailableError(f"Unknown device '{requested}'. Available: {choices}") from exc
    if mode is DeviceMode.CPU:
        return DeviceMode.CPU
    supports_directml = model is None or DeviceMode.DIRECTML.value in model.supported_devices
    if mode is DeviceMode.DIRECTML and not supports_directml:
        raise DeviceUnavailableError(
            f"Model '{model.identifier}' does not support DirectML; use --device cpu."
        )
    has_directml = directml_available(providers)
    if mode is DeviceMode.DIRECTML and not has_directml:
        raise DeviceUnavailableError(
            "DirectML was requested but DmlExecutionProvider is not available in ONNX Runtime."
        )
    if mode is DeviceMode.DIRECTML or (mode is DeviceMode.AUTO and supports_directml and has_directml):
        return DeviceMode.DIRECTML
    return DeviceMode.CPU


def device_selection_reason(
    requested: DeviceMode | str, selected: DeviceMode, model: SeparationModel, *, directml: bool
) -> str:
    """Explain a completed model-aware device decision."""
    requested_mode = requested if isinstance(requested, DeviceMode) else DeviceMode(requested)
    if requested_mode is DeviceMode.CPU:
        return "CPU was explicitly requested"
    if requested_mode is DeviceMode.DIRECTML:
        return "DirectML was explicitly requested and is available"
    if DeviceMode.DIRECTML.value not in model.supported_devices:
        return "selected model does not support DirectML"
    if selected is DeviceMode.DIRECTML:
        return "model supports DirectML and DmlExecutionProvider is available"
    return "DirectML is unavailable; using CPU fallback"


class AudioSeparatorBackend:
    """Capability description for the intended audio-separator backend."""

    def __init__(self, *, device: DeviceMode = DeviceMode.CPU, model_cache: Path = MODEL_DIR) -> None:
        self.device = device
        self._model_cache = Path(model_cache)

    @property
    def name(self) -> str:
        return "audio-separator"

    @property
    def available(self) -> bool:
        return is_optional_dependency_installed("audio_separator")

    @property
    def hardware_provider(self) -> str:
        return self.device.value

    @property
    def supported_models(self) -> tuple[SeparationModel, ...]:
        return tuple(model for model in MODEL_REGISTRY.values() if model.backend == self.name)

    @property
    def supported_stems(self) -> frozenset[StemType]:
        return frozenset(stem for model in self.supported_models for stem in model.expected_stems)

    @property
    def model_cache(self) -> Path:
        return self._model_cache

    def separate(self, input_path: Path, output_directory: Path, model: SeparationModel) -> dict[StemType, Path]:
        """Run audio-separator and map its backend filenames to expected stem types."""
        if not self.available:
            raise BackendUnavailableError(
                "The audio-separator backend is not installed. No model or stem files were created."
            )
        self._model_cache.mkdir(parents=True, exist_ok=True)
        output_directory.mkdir(parents=True, exist_ok=True)
        try:
            separator_module = importlib.import_module("audio_separator.separator")
            separator_class = separator_module.Separator
            separator = separator_class(
                log_level=logging.INFO,
                model_file_dir=str(self._model_cache.resolve()),
                output_dir=str(output_directory.resolve()),
                output_format="WAV",
                use_directml=self.device is DeviceMode.DIRECTML,
            )
            separator.load_model(model.filename)
            generated = separator.separate(str(input_path.resolve()))
        except Exception as exc:
            raise SeparationError(f"audio-separator failed with model '{model.filename}': {exc}") from exc

        results: dict[StemType, Path] = {}
        for generated_name in generated:
            path = Path(generated_name)
            if not path.is_absolute():
                path = output_directory / path
            normalized_name = re.sub(r"[^a-z0-9]+", "_", path.stem.lower()).strip("_")
            matches = [stem for stem in model.expected_stems if re.search(rf"(^|_){re.escape(str(stem))}(_|$)", normalized_name)]
            if len(matches) == 1:
                results[matches[0]] = path
        return results

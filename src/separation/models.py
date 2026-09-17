"""Typed separation model metadata and registry."""

from __future__ import annotations

from dataclasses import dataclass

from src.separation.exceptions import UnknownModelError
from src.separation.stems import StemType


@dataclass(frozen=True)
class SeparationModel:
    """Description of a model supported by a separation backend."""

    identifier: str
    display_name: str
    backend: str
    filename: str
    expected_stems: tuple[StemType, ...]
    supported_devices: frozenset[str]
    experimental: bool = False
    notes: str | None = None


HTDEMUCS_6S = SeparationModel(
    identifier="htdemucs_6s.yaml",
    display_name="HTDemucs 6-source",
    backend="audio-separator",
    filename="htdemucs_6s.yaml",
    expected_stems=tuple(
        StemType(name) for name in ("vocals", "drums", "bass", "guitar", "piano", "other")
    ),
    supported_devices=frozenset({"cpu"}),
    experimental=True,
    notes="Six-stem Demucs model. Piano/keys separation quality is experimental and may vary.",
)

UVR_MDX_NET_INST_HQ_5 = SeparationModel(
    identifier="UVR-MDX-NET-Inst_HQ_5.onnx",
    display_name="UVR MDX-NET Inst HQ 5",
    backend="audio-separator",
    filename="UVR-MDX-NET-Inst_HQ_5.onnx",
    expected_stems=(StemType("vocals"), StemType("instrumental")),
    supported_devices=frozenset({"cpu", "directml"}),
    notes="Specialized two-stem vocals/instrumental model with optional DirectML acceleration.",
)

MODEL_REGISTRY: dict[str, SeparationModel] = {
    HTDEMUCS_6S.identifier: HTDEMUCS_6S,
    UVR_MDX_NET_INST_HQ_5.identifier: UVR_MDX_NET_INST_HQ_5,
}
DEFAULT_MODEL_ID = HTDEMUCS_6S.identifier


def get_model(identifier: str) -> SeparationModel:
    """Return registered model metadata or raise a readable domain error."""
    try:
        return MODEL_REGISTRY[identifier]
    except KeyError as exc:
        available = ", ".join(sorted(MODEL_REGISTRY))
        raise UnknownModelError(f"Unknown separation model '{identifier}'. Available: {available}") from exc

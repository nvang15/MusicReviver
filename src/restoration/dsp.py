"""Conservative execution of explicit restoration actions."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, sosfilt_zi, sosfiltfilt

from src.restoration.exceptions import RestorationProcessingError
from src.restoration.models import RestorationPlan

PEAK_CEILING_DBFS = -0.5
PEAK_CEILING_AMPLITUDE = 10.0 ** (PEAK_CEILING_DBFS / 20.0)


def remove_dc_offset(audio: np.ndarray) -> np.ndarray:
    """Subtract each channel's mean without changing length or channel balance."""
    return audio - np.mean(audio, axis=1, keepdims=True, dtype=np.float64)


def high_pass_filter(audio: np.ndarray, sample_rate: int, cutoff_hz: float) -> np.ndarray:
    """Apply a stable second-order (12 dB/octave) Butterworth SOS high-pass.

    Zero-phase filtering avoids phase rotation for normal files. Very short inputs
    that cannot meet ``sosfiltfilt`` padding requirements use causal SOS filtering
    initialized to the first sample, avoiding a startup impulse and preserving length.
    """
    nyquist = sample_rate / 2.0
    if not 0.0 < cutoff_hz < nyquist:
        raise RestorationProcessingError(f"Invalid high-pass cutoff: {cutoff_hz} Hz")
    sos = butter(2, cutoff_hz / nyquist, btype="highpass", output="sos")
    try:
        return sosfiltfilt(sos, audio, axis=1)
    except ValueError:
        initial_state = sosfilt_zi(sos)
        filtered = np.empty_like(audio, dtype=np.float64)
        for channel in range(audio.shape[0]):
            filtered[channel], _ = sosfilt(
                sos, audio[channel], zi=initial_state * float(audio[channel, 0])
            )
        return filtered


def gentle_compressor(audio: np.ndarray, sample_rate: int, *, threshold_db: float,
                      ratio: float, attack_ms: float, release_ms: float) -> np.ndarray:
    """Apply deterministic linked-stereo downward compression without makeup gain.

    A peak envelope follows the largest absolute channel sample. Attack and release
    use independent one-pole smoothing coefficients. Gain above the threshold follows
    the requested low ratio and the same gain is applied to every channel, preserving
    the stereo relationship. There is no lookahead, makeup gain, or normalization.
    """
    if ratio < 1.0 or attack_ms <= 0.0 or release_ms <= 0.0:
        raise RestorationProcessingError("Invalid gentle-compressor parameters.")
    linked_level = np.max(np.abs(audio), axis=0)
    attack = float(np.exp(-1.0 / (sample_rate * attack_ms / 1000.0)))
    release = float(np.exp(-1.0 / (sample_rate * release_ms / 1000.0)))
    envelope = np.empty_like(linked_level, dtype=np.float64)
    current = 0.0
    for index, level in enumerate(linked_level):
        coefficient = attack if level > current else release
        current = coefficient * current + (1.0 - coefficient) * float(level)
        envelope[index] = current
    envelope_db = 20.0 * np.log10(np.maximum(envelope, np.finfo(np.float64).tiny))
    gain_reduction_db = np.zeros_like(envelope_db)
    above = envelope_db > threshold_db
    gain_reduction_db[above] = (
        threshold_db + (envelope_db[above] - threshold_db) / ratio - envelope_db[above]
    )
    gain = np.power(10.0, gain_reduction_db / 20.0)
    return audio * gain[np.newaxis, :]


def apply_peak_protection(audio: np.ndarray, ceiling: float = PEAK_CEILING_AMPLITUDE) -> tuple[np.ndarray, bool]:
    """Attenuate globally only when the sample peak exceeds the safety ceiling."""
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= ceiling or peak <= 0.0:
        return audio, False
    return audio * (ceiling / peak), True


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

    working = audio.T.astype(np.float64, copy=True)
    applied: list[dict[str, object]] = []
    for action in plan.actions:
        parameters = action.parameters
        if action.type == "dc_offset_removal":
            working = remove_dc_offset(working)
        elif action.type == "high_pass_filter":
            working = high_pass_filter(working, sample_rate, parameters["frequency_hz"])
        elif action.type == "gentle_compression":
            working = gentle_compressor(
                working, sample_rate, threshold_db=parameters["threshold_db"],
                ratio=parameters["ratio"], attack_ms=parameters["attack_ms"],
                release_ms=parameters["release_ms"],
            )
        else:
            raise RestorationProcessingError(f"Unsupported restoration action: {action.type}")
        applied.append(action.to_dict() if hasattr(action, "to_dict") else {
            "type": action.type, "parameters": action.parameters, "reason": action.reason
        })
    peak_before_protection = float(np.max(np.abs(working)))
    working, peak_protection = apply_peak_protection(working)
    if peak_protection:
        applied.append({
            "type": "peak_protection", "parameters": {"threshold_db": PEAK_CEILING_DBFS},
            "reason": "Planned processing exceeded the safety peak ceiling; attenuation only was applied.",
        })
    peak_after = float(np.max(np.abs(working)))
    if not np.all(np.isfinite(working)) or peak_after > PEAK_CEILING_AMPLITUDE + 1e-9:
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

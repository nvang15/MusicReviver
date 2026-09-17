"""Transparent bounded reference-aware gain estimation."""

from __future__ import annotations

import numpy as np
from scipy.optimize import lsq_linear

from src.mixing.models import MixPlan, MixSource, MixWarning, StemMixSetting

GAIN_BOUND_DB = 3.0
MIN_GAIN = 10.0 ** (-GAIN_BOUND_DB / 20.0)
MAX_GAIN = 10.0 ** (GAIN_BOUND_DB / 20.0)
MAX_FIT_SAMPLES = 200_000


def unity_plan(stem_names: tuple[str, ...], stem_source: MixSource, warning: MixWarning | None = None) -> MixPlan:
    """Return the deterministic safe fallback with no hidden normalization."""
    warnings = (warning,) if warning else ()
    return MixPlan(
        stem_source, stem_names,
        tuple(StemMixSetting(name, 0.0, "Unity-gain fallback") for name in stem_names),
        "unity_gain", False, warnings, True,
    )


def create_mix_plan(stems: dict[str, np.ndarray], reference: np.ndarray,
                    stem_source: MixSource) -> MixPlan:
    """Fit bounded non-negative stem gains to the reference waveform.

    The sampled linear system minimizes ``||Sg - r||²`` where each column of ``S``
    is one aligned stem and ``r`` is the original mix. Gains are bounded to ±3 dB,
    so the solution can refine balance but cannot perform an aggressive remix.
    """
    names = tuple(stems)
    if not names:
        return unity_plan(names, stem_source, MixWarning("reference_fit_unavailable", "No stems were available for fitting."))
    try:
        total_values = reference.size
        stride = max(1, int(np.ceil(total_values / MAX_FIT_SAMPLES)))
        target = reference.reshape(-1)[::stride].astype(np.float64, copy=False)
        matrix = np.column_stack([
            stems[name].reshape(-1)[::stride].astype(np.float64, copy=False) for name in names
        ])
        if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(target)) or not np.any(matrix):
            raise ValueError("non-finite or silent fitting data")
        solution = lsq_linear(matrix, target, bounds=(MIN_GAIN, MAX_GAIN), method="trf")
        if not solution.success or not np.all(np.isfinite(solution.x)):
            raise ValueError(solution.message)
    except (ValueError, np.linalg.LinAlgError) as exc:
        return unity_plan(
            names, stem_source,
            MixWarning("reference_fit_failed", f"Reference fitting failed; unity gain was used: {exc}"),
        )
    settings = tuple(
        StemMixSetting(
            name, float(np.clip(20.0 * np.log10(gain), -GAIN_BOUND_DB, GAIN_BOUND_DB)),
            "Reference-aware bounded least-squares fit to the original standardized mix",
        )
        for name, gain in zip(names, solution.x, strict=True)
    )
    warnings: list[MixWarning] = []
    if np.linalg.matrix_rank(matrix) < len(names):
        warnings.append(MixWarning(
            "reference_fit_rank_deficient",
            "Some stems were linearly dependent; fitted gains remain bounded but may not be unique.",
        ))
    return MixPlan(stem_source, names, settings, "bounded_linear_least_squares", True, tuple(warnings), False)

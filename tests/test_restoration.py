import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.audio.metadata import probe_media
from src.restoration import processor
from src.restoration.dsp import process_audio
from src.restoration.exceptions import RestorationOutputExistsError, RestorationProcessingError
from src.restoration.models import RestorationAction, RestorationPlan, RestorationStrength
from src.restoration.planner import plan_restoration

SAMPLE_RATE = 48_000


def analysis(**overrides):
    data = {
        "dc_offset": 0.0,
        "band_energy_fractions": {"sub": 0.0},
        "dynamic_range_estimate_db": 8.0,
        "crest_factor_db": 8.0,
        "rms_dbfs": -18.0,
        "clipped_sample_count": 0,
        "estimated_noise_floor_dbfs": -60.0,
        "stereo_correlation": 0.5,
    }
    data.update(overrides)
    return data


def action_types(plan):
    return {action.type for action in plan.actions}


def test_zero_dc_offset_has_no_dc_action() -> None:
    assert "dc_offset_removal" not in action_types(plan_restoration("vocals", analysis()))


def test_significant_dc_offset_triggers_removal() -> None:
    plan = plan_restoration("vocals", analysis(dc_offset=0.01))
    assert "dc_offset_removal" in action_types(plan)
    assert "Measured absolute DC offset" in plan.actions[0].reason


def test_bass_high_pass_preserves_low_fundamentals() -> None:
    plan = plan_restoration("bass", analysis(band_energy_fractions={"sub": 0.2}))
    action = next(action for action in plan.actions if action.type == "high_pass_filter")
    assert action.parameters["frequency_hz"] <= 25.0


def test_vocal_subsonic_energy_triggers_conservative_high_pass() -> None:
    plan = plan_restoration("vocals", analysis(band_energy_fractions={"sub": 0.2}))
    action = next(action for action in plan.actions if action.type == "high_pass_filter")
    assert action.parameters == {"frequency_hz": 60.0, "slope_db_per_octave": 12.0}
    assert "Measured 20–60 Hz energy fraction" in action.reason


def test_drums_do_not_receive_aggressive_high_pass() -> None:
    plan = plan_restoration("drums", analysis(band_energy_fractions={"sub": 0.2}))
    action = next(action for action in plan.actions if action.type == "high_pass_filter")
    assert action.parameters["frequency_hz"] <= 25.0


def test_clipping_warns_without_fake_declip() -> None:
    plan = plan_restoration("vocals", analysis(clipped_sample_count=10))
    assert any(warning.code == "clipping_detected" for warning in plan.warnings)
    assert all("declip" not in action.type for action in plan.actions)


def test_limited_dynamics_avoid_compression() -> None:
    plan = plan_restoration("bass", analysis(dynamic_range_estimate_db=5.0, crest_factor_db=5.0))
    assert "gentle_compression" not in action_types(plan)


def test_dynamic_material_may_receive_gentle_compression() -> None:
    plan = plan_restoration("vocals", analysis(dynamic_range_estimate_db=22.0, crest_factor_db=16.0))
    action = next(action for action in plan.actions if action.type == "gentle_compression")
    assert 1.0 < action.parameters["ratio"] <= 1.6


def test_unknown_stem_uses_universal_conservative_rules() -> None:
    plan = plan_restoration("strings", analysis(band_energy_fractions={"sub": 0.2}))
    action = next(action for action in plan.actions if action.type == "high_pass_filter")
    assert action.parameters["frequency_hz"] == 22.0


def test_strength_thresholds_differ_predictably() -> None:
    data = analysis(band_energy_fractions={"sub": 0.04})
    assert "high_pass_filter" not in action_types(plan_restoration("vocals", data, RestorationStrength.LIGHT))
    assert "high_pass_filter" not in action_types(plan_restoration("vocals", data, RestorationStrength.BALANCED))
    assert "high_pass_filter" in action_types(plan_restoration("vocals", data, RestorationStrength.STRONG))


def test_empty_plan_is_bypass() -> None:
    plan = plan_restoration("other", analysis())
    assert plan.bypass is True
    assert plan.actions == ()


def write_canonical(path: Path, *, dc: float = 0.0, frequency: float = 440.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    times = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    signal = 0.25 * np.sin(2 * np.pi * frequency * times) + dc
    sf.write(path, np.column_stack((signal, signal)), SAMPLE_RATE, subtype="PCM_24")
    return path


def test_bypass_output_remains_canonical_and_duration_preserved(tmp_path: Path) -> None:
    source = write_canonical(tmp_path / "source.wav")
    destination = tmp_path / "restored.wav"
    plan = plan_restoration("other", analysis())
    result = process_audio(source, destination, plan)
    metadata = probe_media(destination)
    assert metadata.audio_codec == "pcm_s24le"
    assert metadata.sample_rate == SAMPLE_RATE
    assert metadata.channels == 2
    assert metadata.duration_seconds == pytest.approx(1.0, abs=0.001)
    assert result["peak_after_processing"] < 1.0


def test_processed_output_is_canonical_and_removes_dc(tmp_path: Path) -> None:
    source = write_canonical(tmp_path / "source.wav", dc=0.05)
    destination = tmp_path / "restored.wav"
    plan = plan_restoration("vocals", analysis(dc_offset=0.05))
    process_audio(source, destination, plan)
    audio, rate = sf.read(destination, always_2d=True)
    assert rate == SAMPLE_RATE and audio.shape[1] == 2
    assert abs(float(np.mean(audio))) < 1e-5
    assert float(np.max(np.abs(audio))) < 1.0


def project_fixture(tmp_path: Path, stems=("vocals", "future_stem")):
    input_path = tmp_path / "song.wav"
    write_canonical(input_path)
    project = tmp_path / "output" / "song"
    stem_analysis = {}
    for index, name in enumerate(stems):
        write_canonical(project / "stems" / f"{name}.wav", dc=0.01 if index == 0 else 0.0,
                        frequency=220 + 110 * index)
        stem_analysis[name] = analysis(dc_offset=0.01 if index == 0 else 0.0)
    analysis_dir = project / "analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "analysis.json").write_text(json.dumps({"stems": stem_analysis}), encoding="utf-8")
    return input_path, tmp_path / "output", project


def restore_kwargs(tmp_path: Path, output_root: Path):
    return {"strength": RestorationStrength.BALANCED, "output_root": output_root,
            "project_root": tmp_path, "temp_root": tmp_path / "temp"}


def test_arbitrary_future_stem_and_strict_json(tmp_path: Path) -> None:
    input_path, output_root, _ = project_fixture(tmp_path)
    document, json_path, _ = processor.restore_project(input_path, **restore_kwargs(tmp_path, output_root))
    assert "future_stem" in document["results"]
    raw = json_path.read_text(encoding="utf-8")
    json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    assert "NaN" not in raw and "Infinity" not in raw


def test_force_replacement_and_stale_cleanup(tmp_path: Path) -> None:
    input_path, output_root, project = project_fixture(tmp_path, stems=("vocals",))
    kwargs = restore_kwargs(tmp_path, output_root)
    processor.restore_project(input_path, **kwargs)
    stale = project / "restored" / "stale_restored.wav"
    stale.write_bytes(b"stale")
    with pytest.raises(RestorationOutputExistsError, match="--force"):
        processor.restore_project(input_path, **kwargs)
    processor.restore_project(input_path, force=True, **kwargs)
    assert not stale.exists()


def test_processing_failure_rolls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_path, output_root, project = project_fixture(tmp_path, stems=("vocals",))
    kwargs = restore_kwargs(tmp_path, output_root)
    _, json_path, _ = processor.restore_project(input_path, **kwargs)
    previous = json_path.read_bytes()
    monkeypatch.setattr(
        processor, "process_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(RestorationProcessingError("DSP failed")),
    )
    with pytest.raises(RestorationProcessingError, match="DSP failed"):
        processor.restore_project(input_path, force=True, **kwargs)
    assert json_path.read_bytes() == previous
    assert list((tmp_path / "temp").iterdir()) == []

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app import main
from src.audio.converter import safe_project_name
from src.audio.metadata import probe_media
from src.mastering import processor
from src.mastering.dsp import attenuation_peak_protection, linked_compressor
from src.mastering.exceptions import MasterOutputExistsError, MasteringError, NoMixError
from src.mastering.models import MasteringMode
from src.mastering.planner import POLICIES, create_mastering_plan

RATE = 48_000


def program(frames: int = RATE, amplitude: float = 0.08, right: float = 0.7,
            dynamic: bool = True) -> np.ndarray:
    t = np.arange(frames) / RATE
    envelope = (0.2 + 0.8 * np.square(np.sin(2 * np.pi * 1.5 * t))) if dynamic else 1.0
    left = amplitude * envelope * (np.sin(2 * np.pi * 110 * t) + 0.35 * np.sin(2 * np.pi * 350 * t))
    return np.column_stack((left, left * right)).astype(np.float64)


def fixture(tmp_path: Path, audio: np.ndarray | None = None, name: str = "odd project"):
    input_path = tmp_path / f"{name}.mp3"
    input_path.write_bytes(b"identity only")
    root = tmp_path / "output"
    mix = root / safe_project_name(input_path) / "mix"
    mix.mkdir(parents=True)
    sf.write(mix / "restored_mix.wav", program() if audio is None else audio, RATE, subtype="PCM_24")
    (mix / "mix.json").write_text(json.dumps({"output_path": "unused"}), encoding="utf-8")
    return input_path, root


def options(tmp_path: Path, root: Path):
    return {"output_root": root, "project_root": tmp_path, "temp_root": tmp_path / "temp"}


def metrics(lufs=-24.0, peak=-8.0, crest=16.0, dynamic=14.0, low_mid=0.1, correlation=0.8):
    return {"integrated_lufs": lufs, "peak_dbfs": peak, "crest_factor_db": crest,
            "dynamic_range_estimate_db": dynamic, "band_energy_fractions": {"low_mid": low_mid, "bass": .2, "high": .1},
            "clipped_sample_count": 0, "stereo_correlation": correlation}


def action(plan, kind):
    return next((item for item in plan.actions if item.type == kind), None)


def test_modes_have_bounded_meaningfully_different_plans() -> None:
    plans = {mode: create_mastering_plan(Path("mix.wav"), metrics(low_mid=.40), mode) for mode in MasteringMode}
    assert action(plans[MasteringMode.ARCHIVAL], "bus_compression") is None
    assert action(plans[MasteringMode.BALANCED], "bus_compression").parameters["ratio"] <= 1.5
    assert action(plans[MasteringMode.MODERN], "bus_compression").parameters["ratio"] <= 1.8
    for mode, plan in plans.items():
        assert abs(action(plan, "broad_eq").parameters["gain_db"]) <= POLICIES[mode].max_eq_gain_db
        assert action(plan, "global_gain").parameters["gain_db"] <= POLICIES[mode].max_gain_boost_db


@pytest.mark.parametrize("mode", list(MasteringMode))
def test_already_loud_input_is_not_amplified(mode: MasteringMode) -> None:
    assert action(create_mastering_plan(Path("mix.wav"), metrics(lufs=-9.0, peak=-.9), mode), "global_gain") is None


def test_quiet_extreme_gain_is_bounded_and_range_is_guidance() -> None:
    plan = create_mastering_plan(Path("mix.wav"), metrics(lufs=-50, peak=-20), MasteringMode.MODERN)
    assert action(plan, "global_gain").parameters["gain_db"] == 5.0
    assert any(w.code == "loudness_target_not_forced" for w in plan.warnings)


def test_highly_compressed_material_avoids_compression() -> None:
    assert create_mastering_plan(Path("mix.wav"), metrics(crest=5.0), MasteringMode.MODERN).bypass_compression


def test_negative_correlation_warns_without_stereo_action() -> None:
    plan = create_mastering_plan(Path("mix.wav"), metrics(correlation=-.5), MasteringMode.MODERN)
    assert any(w.code == "negative_stereo_correlation" for w in plan.warnings)
    assert not any("stereo" in a.type for a in plan.actions)


def test_linked_compression_preserves_channel_relationship() -> None:
    audio = program(right=.37)
    result = linked_compressor(audio, RATE, threshold_dbfs=-30, ratio=1.5, attack_ms=30, release_ms=150)
    nonzero = np.abs(result[:, 0]) > 1e-8
    assert result[nonzero, 1] / result[nonzero, 0] == pytest.approx(.37, abs=1e-10)


def test_peak_protection_prevents_clipping_and_never_increases() -> None:
    audio = program(amplitude=1.2)
    result, reduction = attenuation_peak_protection(audio, -1.0)
    assert reduction >= 0 and np.max(np.abs(result)) <= 10 ** (-1 / 20) + 1e-12
    quiet, reduction = attenuation_peak_protection(audio * .01, -1.0)
    assert reduction == 0 and quiet == pytest.approx(audio * .01)


def test_master_output_format_duration_strict_json_and_gui_api(tmp_path: Path) -> None:
    source = program(frames=RATE + 37)
    input_path, root = fixture(tmp_path, source)
    result = processor.master_project(input_path, **options(tmp_path, root))
    info = probe_media(result.audio_path)
    assert (info.audio_codec, info.sample_rate, info.channels) == ("pcm_s24le", RATE, 2)
    assert sf.info(result.audio_path).frames == source.shape[0]
    raw = result.metadata_path.read_text(encoding="utf-8")
    document = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    assert "NaN" not in raw and "Infinity" not in raw
    assert document["mode"] == "balanced" and document["peak_measurement"] == "sample_peak"
    assert float(document["actual_peak_dbfs"]) <= -1.0 + .001


def test_mode_selection_force_and_stale_cleanup(tmp_path: Path) -> None:
    input_path, root = fixture(tmp_path)
    opts = options(tmp_path, root)
    first = processor.master_project(input_path, mode=MasteringMode.ARCHIVAL, **opts)
    (first.audio_path.parent / "stale.wav").write_bytes(b"stale")
    with pytest.raises(MasterOutputExistsError):
        processor.master_project(input_path, mode=MasteringMode.MODERN, **opts)
    second = processor.master_project(input_path, mode=MasteringMode.MODERN, force=True, **opts)
    assert second.audio_path.name == "modern_master.wav" and not (second.audio_path.parent / "stale.wav").exists()


def test_failure_rollback_preserves_existing_master(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_path, root = fixture(tmp_path)
    opts = options(tmp_path, root)
    result = processor.master_project(input_path, **opts)
    previous = result.metadata_path.read_bytes()
    monkeypatch.setattr(processor.sf, "write", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("write failed")))
    with pytest.raises(MasteringError, match="write failed"):
        processor.master_project(input_path, force=True, **opts)
    assert result.metadata_path.read_bytes() == previous


def test_missing_mix_never_runs_earlier_stages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = False
    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
    monkeypatch.setattr("src.audio.converter.convert_media", forbidden)
    with pytest.raises(NoMixError, match="does not run earlier stages"):
        processor.master_project(tmp_path / "missing.mp3", **options(tmp_path, tmp_path / "output"))
    assert not called


def test_cli_mode_selection(capsys: pytest.CaptureFixture[str], tmp_path: Path,
                            monkeypatch: pytest.MonkeyPatch) -> None:
    input_path, root = fixture(tmp_path)
    import app
    real = processor.master_project
    monkeypatch.setattr(app, "master_project", lambda path, **kw: real(path, output_root=root, project_root=tmp_path, temp_root=tmp_path / "temp", **kw))
    assert main(["master", str(input_path), "--mode", "modern"]) == 0
    assert "Mode: modern" in capsys.readouterr().out


def test_excessive_peak_need_uses_attenuation_not_loudness_limiting() -> None:
    protected, reduction = attenuation_peak_protection(np.full((1000, 2), 2.0), -1.5)
    assert reduction > .5 and np.max(np.abs(protected)) <= 10 ** (-1.5 / 20) + 1e-12

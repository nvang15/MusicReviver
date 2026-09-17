import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.audio.metadata import probe_media
from src.mixing import mixer
from src.mixing.exceptions import MixOutputExistsError, MixingError, NoMixStemsError, StemAlignmentError
from src.mixing.models import MixSource
from src.mixing.planner import GAIN_BOUND_DB, create_mix_plan

SAMPLE_RATE = 48_000


def signal(frequency: float, frames: int = SAMPLE_RATE, amplitude: float = 0.08,
           right_scale: float = 1.0) -> np.ndarray:
    times = np.arange(frames) / SAMPLE_RATE
    left = amplitude * np.sin(2 * np.pi * frequency * times)
    return np.column_stack((left, left * right_scale)).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio, sample_rate, subtype="PCM_24")
    return path


def project_fixture(tmp_path: Path, *, restored: bool = False,
                    stem_names: tuple[str, ...] = ("vocals", "drums"),
                    weights: tuple[float, ...] | None = None):
    input_path = write_wav(tmp_path / "song.wav", signal(100))
    project = tmp_path / "output" / "song"
    stems = {name: signal(220 + index * 173, right_scale=0.7 + index * 0.1)
             for index, name in enumerate(stem_names)}
    weights = weights or tuple(1.0 for _ in stem_names)
    reference = sum((stems[name] * weight for name, weight in zip(stem_names, weights, strict=True)),
                    np.zeros_like(next(iter(stems.values()))))
    write_wav(project / "source" / "original_48k.wav", reference)
    if restored:
        results = {}
        for name, audio in stems.items():
            write_wav(project / "restored" / f"{name}_restored.wav", audio)
            results[name] = {}
        (project / "restored" / "restoration.json").write_text(
            json.dumps({"results": results}), encoding="utf-8"
        )
    else:
        for name, audio in stems.items():
            write_wav(project / "stems" / f"{name}.wav", audio)
    return input_path, tmp_path / "output", project, stems, reference


def kwargs(tmp_path: Path, output_root: Path):
    return {"output_root": output_root, "project_root": tmp_path, "temp_root": tmp_path / "temp"}


def test_two_unity_stems_sum_correctly_and_preserve_stereo(tmp_path: Path) -> None:
    input_path, output_root, _, stems, reference = project_fixture(tmp_path)
    result = mixer.mix_project(input_path, **kwargs(tmp_path, output_root))
    mixed, rate = sf.read(result.audio_path, always_2d=True)
    assert rate == SAMPLE_RATE
    assert mixed == pytest.approx(reference, abs=2e-6)
    assert mixed[:, 1] != pytest.approx(mixed[:, 0])


def test_arbitrary_and_partial_stem_set_mix_dynamically(tmp_path: Path) -> None:
    input_path, output_root, _, _, _ = project_fixture(
        tmp_path, stem_names=("organ", "percussion", "future_texture")
    )
    result = mixer.mix_project(input_path, **kwargs(tmp_path, output_root))
    assert result.plan.stems == ("future_texture", "organ", "percussion")


def test_auto_prefers_restored_stems(tmp_path: Path) -> None:
    input_path, output_root, project, stems, _ = project_fixture(tmp_path, restored=True)
    for name, audio in stems.items():
        write_wav(project / "stems" / f"{name}.wav", audio)
    result = mixer.mix_project(input_path, **kwargs(tmp_path, output_root))
    assert result.plan.stem_source is MixSource.RESTORED
    assert result.audio_path.name == "restored_mix.wav"


def test_auto_falls_back_when_restored_set_is_invalid(tmp_path: Path) -> None:
    input_path, output_root, project, stems, _ = project_fixture(tmp_path)
    write_wav(project / "restored" / "vocals_restored.wav", stems["vocals"])
    (project / "restored" / "restoration.json").write_text(
        json.dumps({"results": {"vocals": {}, "drums": {}}}), encoding="utf-8"
    )
    result = mixer.mix_project(input_path, **kwargs(tmp_path, output_root))
    assert result.plan.stem_source is MixSource.SEPARATED
    document = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert any(warning["code"] == "invalid_restored_set" for warning in document["warnings"])


def test_separated_fallback_and_explicit_source_selection(tmp_path: Path) -> None:
    input_path, output_root, project, stems, _ = project_fixture(tmp_path)
    result = mixer.mix_project(input_path, source=MixSource.AUTO, **kwargs(tmp_path, output_root))
    assert result.plan.stem_source is MixSource.SEPARATED
    assert result.audio_path.name == "separated_mix.wav"
    for name, audio in stems.items():
        write_wav(project / "restored" / f"{name}_restored.wav", audio)
    (project / "restored" / "restoration.json").write_text(json.dumps({"results": {n: {} for n in stems}}), encoding="utf-8")
    result = mixer.mix_project(input_path, source=MixSource.SEPARATED, force=True,
                               **kwargs(tmp_path, output_root))
    assert result.plan.stem_source is MixSource.SEPARATED


def test_no_stems_fails_without_starting_separation(tmp_path: Path) -> None:
    input_path = write_wav(tmp_path / "song.wav", signal(220))
    write_wav(tmp_path / "output" / "song" / "source" / "original_48k.wav", signal(220))
    with pytest.raises(NoMixStemsError, match="does not start AI separation"):
        mixer.mix_project(input_path, **kwargs(tmp_path, tmp_path / "output"))


def test_material_duration_mismatch_fails(tmp_path: Path) -> None:
    input_path, output_root, project, _, _ = project_fixture(tmp_path)
    write_wav(project / "stems" / "drums.wav", signal(393, frames=SAMPLE_RATE - 100))
    with pytest.raises(StemAlignmentError, match="materially misaligned"):
        mixer.mix_project(input_path, **kwargs(tmp_path, output_root))


@pytest.mark.parametrize(
    "audio,rate,message",
    [(signal(220), 44_100, "Sample-rate mismatch"), (signal(220)[:, :1], SAMPLE_RATE, "Channel-count mismatch")],
)
def test_format_mismatch_fails(tmp_path: Path, audio: np.ndarray, rate: int, message: str) -> None:
    input_path, output_root, project, _, _ = project_fixture(tmp_path)
    write_wav(project / "stems" / "vocals.wav", audio, rate)
    with pytest.raises(StemAlignmentError, match=message):
        mixer.mix_project(input_path, **kwargs(tmp_path, output_root))


def test_reference_fit_is_bounded_and_improves_known_reference() -> None:
    stems = {"a": signal(220), "b": signal(510)}
    reference = stems["a"] * 0.8 + stems["b"] * 1.2
    plan = create_mix_plan(stems, reference, MixSource.SEPARATED)
    assert plan.reference_fitting_succeeded
    assert all(-GAIN_BOUND_DB <= setting.gain_db <= GAIN_BOUND_DB for setting in plan.settings)
    fitted = sum((stems[s.stem] * s.linear_gain for s in plan.settings), np.zeros_like(reference))
    unity = stems["a"] + stems["b"]
    assert np.mean((fitted - reference) ** 2) < np.mean((unity - reference) ** 2)


def test_failed_reference_fit_uses_unity() -> None:
    stems = {"silent": np.zeros((100, 2), dtype=np.float32)}
    plan = create_mix_plan(stems, np.zeros((100, 2)), MixSource.SEPARATED)
    assert plan.unity_fallback is True
    assert plan.settings[0].gain_db == 0.0


def test_safety_attenuation_prevents_clipping_and_never_increases(tmp_path: Path) -> None:
    input_path, output_root, project, _, _ = project_fixture(tmp_path)
    loud = signal(220, amplitude=0.8)
    write_wav(project / "stems" / "vocals.wav", loud)
    write_wav(project / "stems" / "drums.wav", loud)
    write_wav(project / "source" / "original_48k.wav", loud + loud)
    result = mixer.mix_project(input_path, **kwargs(tmp_path, output_root))
    document = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert document["safety_gain_db"] <= 0.0
    assert document["final_mix_metrics"]["peak_amplitude"] <= mixer.PEAK_CEILING + 1e-9
    assert document["clipping"] is False


def test_output_format_duration_json_and_reference_diagnostics(tmp_path: Path) -> None:
    input_path, output_root, _, _, _ = project_fixture(tmp_path, weights=(0.8, 1.2))
    result = mixer.mix_project(input_path, **kwargs(tmp_path, output_root))
    metadata = probe_media(result.audio_path)
    assert metadata.audio_codec == "pcm_s24le"
    assert metadata.sample_rate == SAMPLE_RATE and metadata.channels == 2
    assert metadata.duration_seconds == pytest.approx(1.0, abs=0.001)
    raw = result.metadata_path.read_text(encoding="utf-8")
    document = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    assert "NaN" not in raw and "Infinity" not in raw
    assert document["reference_metrics"]["integrated_lufs"] is not None
    assert document["reference_comparison"]["waveform_correlation"] is not None


def test_force_replacement_removes_stale_mix(tmp_path: Path) -> None:
    input_path, output_root, project, _, _ = project_fixture(tmp_path)
    options = kwargs(tmp_path, output_root)
    mixer.mix_project(input_path, **options)
    stale = project / "mix" / "stale.wav"
    stale.write_bytes(b"stale")
    with pytest.raises(MixOutputExistsError, match="--force"):
        mixer.mix_project(input_path, **options)
    mixer.mix_project(input_path, force=True, **options)
    assert not stale.exists()


def test_failure_rolls_back_existing_mix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_path, output_root, _, _, _ = project_fixture(tmp_path)
    options = kwargs(tmp_path, output_root)
    result = mixer.mix_project(input_path, **options)
    previous = result.metadata_path.read_bytes()
    monkeypatch.setattr(mixer.sf, "write", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("write failed")))
    with pytest.raises(MixingError, match="write failed"):
        mixer.mix_project(input_path, force=True, **options)
    assert result.metadata_path.read_bytes() == previous
    assert list((tmp_path / "temp").iterdir()) == []

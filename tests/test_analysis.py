import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.analysis import report
from src.analysis.analyzer import analyze_audio
from src.analysis.exceptions import AnalysisOutputExistsError, UnsupportedAnalysisInputError

SAMPLE_RATE = 48_000


def write_wav(path: Path, audio: np.ndarray, *, sample_rate: int = SAMPLE_RATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio, sample_rate, subtype="PCM_24")
    return path


def sine(frequency: float, duration: float = 1.0, amplitude: float = 0.5) -> np.ndarray:
    times = np.arange(round(SAMPLE_RATE * duration)) / SAMPLE_RATE
    return amplitude * np.sin(2.0 * np.pi * frequency * times)


def test_silence_is_numerically_safe(tmp_path: Path) -> None:
    result = analyze_audio(write_wav(tmp_path / "silence.wav", np.zeros((SAMPLE_RATE, 2))), logical_name="silence")
    assert result.peak_dbfs is None
    assert result.rms_dbfs is None
    assert result.integrated_lufs is None
    assert result.dynamic_range_estimate_db is None
    assert result.silence_fraction == 1.0
    assert any("loudness_unavailable" in warning for warning in result.warnings)


def test_mono_sine_metrics(tmp_path: Path) -> None:
    result = analyze_audio(write_wav(tmp_path / "mono.wav", sine(440)), logical_name="mono")
    assert result.channels == 1
    assert result.sample_rate == SAMPLE_RATE
    assert result.rms == pytest.approx(0.5 / np.sqrt(2), rel=0.01)
    assert result.stereo_correlation is None
    assert any("mono audio" in warning for warning in result.warnings)


def test_ffmpeg_wave_extensible_is_supported(tmp_path: Path) -> None:
    path = tmp_path / "canonical.wav"
    sf.write(path, np.column_stack((sine(440, 0.1),) * 2), SAMPLE_RATE,
             format="WAVEX", subtype="PCM_24")
    assert analyze_audio(path, logical_name="canonical").sample_rate == SAMPLE_RATE


def test_identical_stereo_has_positive_correlation(tmp_path: Path) -> None:
    signal = sine(440)
    result = analyze_audio(write_wav(tmp_path / "same.wav", np.column_stack((signal, signal))), logical_name="same")
    assert result.stereo_correlation == pytest.approx(1.0, abs=1e-6)
    assert result.stereo_balance_db == pytest.approx(0.0, abs=1e-6)


def test_inverted_stereo_has_negative_correlation(tmp_path: Path) -> None:
    signal = sine(440)
    result = analyze_audio(write_wav(tmp_path / "inverted.wav", np.column_stack((signal, -signal))), logical_name="inverted")
    assert result.stereo_correlation == pytest.approx(-1.0, abs=1e-6)


def test_different_stereo_channels_are_finite(tmp_path: Path) -> None:
    audio = np.column_stack((sine(440), sine(673)))
    result = analyze_audio(write_wav(tmp_path / "different.wav", audio), logical_name="different")
    assert result.stereo_correlation is not None
    assert abs(result.stereo_correlation) < 0.05


def test_white_noise_metrics_are_finite(tmp_path: Path) -> None:
    noise = np.random.default_rng(7).normal(0.0, 0.1, (SAMPLE_RATE, 2))
    result = analyze_audio(write_wav(tmp_path / "noise.wav", noise), logical_name="noise")
    assert result.spectral_centroid_hz is not None
    assert result.estimated_noise_floor_dbfs is not None
    assert all(np.isfinite(value) for value in result.band_energy_fractions.values())


def test_clipped_signal_detection(tmp_path: Path) -> None:
    audio = np.ones((1000, 2))
    result = analyze_audio(write_wav(tmp_path / "clipped.wav", audio), logical_name="clipped")
    assert result.clipped_sample_count == 2000
    assert result.clipped_sample_fraction == 1.0


def test_dc_offset_detection(tmp_path: Path) -> None:
    audio = np.column_stack((sine(440, amplitude=0.2) + 0.1,) * 2)
    result = analyze_audio(write_wav(tmp_path / "dc.wav", audio), logical_name="dc")
    assert result.dc_offset == pytest.approx(0.1, abs=1e-4)


def test_very_short_audio_returns_warnings(tmp_path: Path) -> None:
    result = analyze_audio(write_wav(tmp_path / "short.wav", sine(440, duration=0.05)), logical_name="short", full_mix=True)
    assert result.integrated_lufs is None
    assert result.tempo_bpm is None
    assert result.key_estimate is None
    assert any("too short" in warning for warning in result.warnings)


def test_440_hz_spectral_centroid(tmp_path: Path) -> None:
    result = analyze_audio(write_wav(tmp_path / "a.wav", sine(440)), logical_name="a")
    assert result.spectral_centroid_hz == pytest.approx(440.0, abs=35.0)


def test_low_frequency_band_energy(tmp_path: Path) -> None:
    result = analyze_audio(write_wav(tmp_path / "low.wav", sine(40)), logical_name="low")
    assert result.band_energy_fractions["sub"] == max(result.band_energy_fractions.values())


def test_high_frequency_band_energy(tmp_path: Path) -> None:
    result = analyze_audio(write_wav(tmp_path / "high.wav", sine(10_000)), logical_name="high")
    assert result.band_energy_fractions["high"] == max(result.band_energy_fractions.values())


def test_json_serialization_has_no_nonstandard_numbers(tmp_path: Path) -> None:
    result = analyze_audio(write_wav(tmp_path / "silent.wav", np.zeros((1000, 2))), logical_name="silent")
    encoded = json.dumps(result.to_dict(), allow_nan=False)
    assert "NaN" not in encoded
    assert "Infinity" not in encoded


def project_fixture(tmp_path: Path, *, stems: tuple[str, ...] = ()) -> tuple[Path, Path, Path]:
    input_path = write_wav(tmp_path / "input.wav", np.column_stack((sine(440, 0.5), sine(660, 0.5))))
    output_root = tmp_path / "output"
    source = write_wav(output_root / "input" / "source" / "original_48k.wav", np.column_stack((sine(440, 0.5), sine(660, 0.5))))
    for stem in stems:
        write_wav(output_root / "input" / "stems" / f"{stem}.wav", np.column_stack((sine(220, 0.5),) * 2))
    return input_path, output_root, source


def test_existing_and_arbitrary_stems_are_discovered(tmp_path: Path) -> None:
    _, output_root, _ = project_fixture(tmp_path, stems=("vocals", "organ"))
    found = report.discover_stems(output_root / "input")
    assert set(found) == {"vocals", "organ"}


def test_source_only_analysis_and_output_generation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_path, output_root, source = project_fixture(tmp_path)
    monkeypatch.setattr(report, "_ensure_source", lambda *args: source)
    document, json_path, text_path = report.analyze_project(
        input_path, output_root=output_root, project_root=tmp_path, temp_root=tmp_path / "temp"
    )
    assert document["stems"] == {}
    assert json_path.is_file() and text_path.is_file()
    assert json.loads(json_path.read_text(encoding="utf-8"))["source"]["sample_rate"] == SAMPLE_RATE


def test_project_analyzes_arbitrary_future_stem(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_path, output_root, source = project_fixture(tmp_path, stems=("electric_piano",))
    monkeypatch.setattr(report, "_ensure_source", lambda *args: source)
    document, _, _ = report.analyze_project(
        input_path, output_root=output_root, project_root=tmp_path, temp_root=tmp_path / "temp"
    )
    assert "electric_piano" in document["stems"]
    assert document["stems"]["electric_piano"]["tempo_bpm"] is None


def test_force_behavior(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_path, output_root, source = project_fixture(tmp_path)
    monkeypatch.setattr(report, "_ensure_source", lambda *args: source)
    kwargs = {"output_root": output_root, "project_root": tmp_path, "temp_root": tmp_path / "temp"}
    report.analyze_project(input_path, **kwargs)
    with pytest.raises(AnalysisOutputExistsError, match="--force"):
        report.analyze_project(input_path, **kwargs)
    document, _, _ = report.analyze_project(input_path, force=True, **kwargs)
    assert document["schema_version"] == "1.0"


def test_failure_does_not_corrupt_existing_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_path, output_root, source = project_fixture(tmp_path)
    monkeypatch.setattr(report, "_ensure_source", lambda *args: source)
    kwargs = {"output_root": output_root, "project_root": tmp_path, "temp_root": tmp_path / "temp"}
    _, json_path, _ = report.analyze_project(input_path, **kwargs)
    previous = json_path.read_bytes()
    corrupt = output_root / "input" / "stems" / "broken.wav"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"not audio")
    with pytest.raises(UnsupportedAnalysisInputError):
        report.analyze_project(input_path, force=True, **kwargs)
    assert json_path.read_bytes() == previous

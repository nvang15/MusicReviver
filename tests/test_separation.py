from pathlib import Path
import shutil
import subprocess

import pytest

import app
from src.audio.metadata import probe_media
from src.separation import backends, diagnostics, separator
from src.separation.backends import AudioSeparatorBackend, DeviceMode
from src.separation.exceptions import DeviceUnavailableError, MissingStemError, OutputExistsError, SeparationError, UnknownModelError
from src.separation.models import HTDEMUCS_6S, MODEL_REGISTRY, UVR_MDX_NET_INST_HQ_5, SeparationModel, get_model
from src.separation.stems import StemType


def test_optional_dependency_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends.importlib.util, "find_spec", lambda name: object() if name == "present" else None)
    assert backends.is_optional_dependency_installed("present") is True
    assert backends.is_optional_dependency_installed("missing") is False


def test_backend_availability_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = AudioSeparatorBackend()
    monkeypatch.setattr(backends, "is_optional_dependency_installed", lambda name: False)
    assert backend.available is False
    monkeypatch.setattr(backends, "is_optional_dependency_installed", lambda name: name == "audio_separator")
    assert backend.available is True


def test_provider_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRuntime:
        @staticmethod
        def get_available_providers() -> list[str]:
            return ["DmlExecutionProvider", "CPUExecutionProvider"]

    monkeypatch.setattr(backends, "is_optional_dependency_installed", lambda name: True)
    monkeypatch.setattr(backends.importlib, "import_module", lambda name: FakeRuntime)
    assert backends.get_onnx_execution_providers() == (
        "DmlExecutionProvider", "CPUExecutionProvider"
    )
    assert backends.directml_available(("DmlExecutionProvider",)) is True
    assert backends.directml_available(("CPUExecutionProvider",)) is False


def test_auto_device_prefers_directml_when_available() -> None:
    assert backends.select_device("auto", providers=("DmlExecutionProvider",)) is DeviceMode.DIRECTML


def test_auto_device_falls_back_to_cpu() -> None:
    assert backends.select_device("auto", providers=("CPUExecutionProvider",)) is DeviceMode.CPU


def test_explicit_cpu_selection_ignores_provider_availability() -> None:
    assert backends.select_device("cpu", providers=()) is DeviceMode.CPU


def test_explicit_directml_success() -> None:
    assert backends.select_device("directml", providers=("DmlExecutionProvider",)) is DeviceMode.DIRECTML


def test_explicit_directml_unavailable_error() -> None:
    with pytest.raises(DeviceUnavailableError, match="DmlExecutionProvider"):
        backends.select_device("directml", providers=("CPUExecutionProvider",))


def test_model_registry() -> None:
    assert MODEL_REGISTRY["htdemucs_6s.yaml"] is HTDEMUCS_6S
    assert get_model("htdemucs_6s.yaml") is HTDEMUCS_6S
    assert get_model("UVR-MDX-NET-Inst_HQ_5.onnx") is UVR_MDX_NET_INST_HQ_5
    with pytest.raises(UnknownModelError, match="Unknown separation model"):
        get_model("missing")


def test_six_stem_model_metadata() -> None:
    assert tuple(HTDEMUCS_6S.expected_stems) == (
        "vocals", "drums", "bass", "guitar", "piano", "other"
    )
    assert HTDEMUCS_6S.backend == "audio-separator"
    assert HTDEMUCS_6S.experimental is True
    assert HTDEMUCS_6S.supported_devices == frozenset({"cpu"})
    assert "Piano/keys" in (HTDEMUCS_6S.notes or "")


def test_arbitrary_future_stem_compatibility() -> None:
    model = SeparationModel(
        identifier="future",
        display_name="Future model",
        backend="future-backend",
        filename="future.onnx",
        expected_stems=tuple(StemType(name) for name in ("organ", "synth", "strings", "brass")),
        supported_devices=frozenset({"cpu"}),
    )
    assert len(model.expected_stems) == 4
    assert model.expected_stems[0] == "organ"
    assert all(not stem.is_known for stem in model.expected_stems)


def test_mdx_model_directml_compatibility() -> None:
    assert UVR_MDX_NET_INST_HQ_5.expected_stems == ("vocals", "instrumental")
    assert UVR_MDX_NET_INST_HQ_5.supported_devices == frozenset({"cpu", "directml"})


def test_model_aware_auto_device_selection() -> None:
    providers = ("DmlExecutionProvider", "CPUExecutionProvider")
    assert backends.select_device("auto", model=HTDEMUCS_6S, providers=providers) is DeviceMode.CPU
    assert backends.select_device("auto", model=UVR_MDX_NET_INST_HQ_5, providers=providers) is DeviceMode.DIRECTML
    with pytest.raises(DeviceUnavailableError, match="does not support DirectML"):
        backends.select_device("directml", model=HTDEMUCS_6S, providers=providers)


def test_backend_invocation_and_normalized_stem_detection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {}

    class FakeSeparator:
        def __init__(self, **kwargs):
            calls["kwargs"] = kwargs

        def load_model(self, filename):
            calls["model"] = filename

        def separate(self, source):
            calls["source"] = source
            output = Path(calls["kwargs"]["output_dir"])
            names = ["song_(Vocals)_model.wav", "song_(Instrumental)_model.wav"]
            for name in names:
                (output / name).write_bytes(b"audio")
            return names

    monkeypatch.setattr(backends, "is_optional_dependency_installed", lambda name: True)
    monkeypatch.setattr(backends.importlib, "import_module", lambda name: type("Module", (), {"Separator": FakeSeparator}))
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    result = AudioSeparatorBackend(device=DeviceMode.DIRECTML, model_cache=tmp_path / "models").separate(
        source, tmp_path / "raw", UVR_MDX_NET_INST_HQ_5
    )
    assert set(result) == {StemType("vocals"), StemType("instrumental")}
    assert calls["kwargs"]["model_file_dir"] == str((tmp_path / "models").resolve())
    assert calls["kwargs"]["use_directml"] is True
    assert calls["model"] == "UVR-MDX-NET-Inst_HQ_5.onnx"


class FakeBackend:
    name = "audio-separator"
    available = True

    def __init__(self, stems: tuple[StemType, ...], *, fail: bool = False) -> None:
        self.stems = stems
        self.fail = fail

    def separate(self, input_path: Path, output_directory: Path, model: SeparationModel):
        if self.fail:
            raise SeparationError("mock inference failure")
        result = {}
        for stem in self.stems:
            path = output_directory / f"backend_({stem})_name.wav"
            path.write_bytes(b"mock audio")
            result[stem] = path
        return result


def _request(model: SeparationModel, *, force: bool = False) -> separator.SeparationRequest:
    return separator.SeparationRequest(
        Path("input.wav"), model, DeviceMode.AUTO, DeviceMode.CPU,
        "test selection", False, force,
    )


def _mock_orchestration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    source = tmp_path / "output" / "input" / "source" / "original_48k.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    monkeypatch.setattr(separator, "_standardized_source", lambda *args, **kwargs: source)
    monkeypatch.setattr(
        separator, "_normalize_stem", lambda source, destination: shutil.copy2(source, destination)
    )
    monkeypatch.setattr(separator, "_validate_stem", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        separator, "probe_media",
        lambda path: type("Metadata", (), {"duration_seconds": 1.0, "sample_rate": 44100})(),
    )
    return source


@pytest.mark.parametrize("model", [HTDEMUCS_6S, UVR_MDX_NET_INST_HQ_5])
def test_successful_mocked_separation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, model: SeparationModel
) -> None:
    _mock_orchestration(monkeypatch, tmp_path)
    result = separator.separate(
        _request(model), backend=FakeBackend(model.expected_stems),
        output_root=tmp_path / "output", temp_root=tmp_path / "temp", project_root=tmp_path,
    )
    assert set(result.stems) == set(model.expected_stems)
    assert all(path.name == f"{stem}.wav" and path.is_file() for stem, path in result.stems.items())
    document = __import__("json").loads(result.metadata_path.read_text(encoding="utf-8"))
    assert document["model_filename"] == model.filename
    assert document["actual_stems"] == [str(stem) for stem in model.expected_stems]
    assert document["backend_native_output_sample_rates"] == {
        str(stem): 44100 for stem in model.expected_stems
    }
    assert document["canonical_output_sample_rate"] == 48000
    assert document["canonical_output_codec"] == "pcm_s24le"
    assert document["canonical_output_channels"] == 2
    assert not Path(document["source_file"]).is_absolute()


def test_missing_stem_and_failure_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _mock_orchestration(monkeypatch, tmp_path)
    project_stems = tmp_path / "output" / "input" / "stems"
    with pytest.raises(MissingStemError, match="piano"):
        separator.separate(
            _request(HTDEMUCS_6S), backend=FakeBackend(HTDEMUCS_6S.expected_stems[:-2]),
            output_root=tmp_path / "output", temp_root=tmp_path / "temp", project_root=tmp_path,
        )
    assert not project_stems.exists()
    assert list((tmp_path / "temp").iterdir()) == []


def test_force_replaces_stale_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _mock_orchestration(monkeypatch, tmp_path)
    stems = tmp_path / "output" / "input" / "stems"
    stems.mkdir(parents=True)
    (stems / "stale.wav").write_bytes(b"stale")
    with pytest.raises(OutputExistsError, match="--force"):
        separator.separate(
            _request(UVR_MDX_NET_INST_HQ_5), backend=FakeBackend(UVR_MDX_NET_INST_HQ_5.expected_stems),
            output_root=tmp_path / "output", temp_root=tmp_path / "temp", project_root=tmp_path,
        )
    result = separator.separate(
        _request(UVR_MDX_NET_INST_HQ_5, force=True), backend=FakeBackend(UVR_MDX_NET_INST_HQ_5.expected_stems),
        output_root=tmp_path / "output", temp_root=tmp_path / "temp", project_root=tmp_path,
    )
    assert not (result.stems_directory / "stale.wav").exists()
    assert {path.name for path in result.stems_directory.glob("*.wav")} == {"vocals.wav", "instrumental.wav"}


def test_backend_failure_preserves_existing_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _mock_orchestration(monkeypatch, tmp_path)
    stems = tmp_path / "output" / "input" / "stems"
    stems.mkdir(parents=True)
    existing = stems / "keep.wav"
    existing.write_bytes(b"keep")
    with pytest.raises(SeparationError, match="mock inference failure"):
        separator.separate(
            _request(UVR_MDX_NET_INST_HQ_5, force=True), backend=FakeBackend((), fail=True),
            output_root=tmp_path / "output", temp_root=tmp_path / "temp", project_root=tmp_path,
        )
    assert existing.read_bytes() == b"keep"


def test_44100_backend_stem_is_normalized_to_internal_format(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required")
    native = tmp_path / "native.wav"
    canonical = tmp_path / "canonical.wav"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=44100:duration=0.2", "-ac", "1", str(native),
        ],
        check=True,
    )
    separator._normalize_stem(native, canonical)
    result = probe_media(canonical)
    assert result.audio_codec == "pcm_s24le"
    assert result.sample_rate == 48000
    assert result.channels == 2
    assert native.is_file()
    assert probe_media(native).sample_rate == 44100


def test_normalization_failure_rolls_back_safely(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_orchestration(monkeypatch, tmp_path)
    stems = tmp_path / "output" / "input" / "stems"
    stems.mkdir(parents=True)
    existing = stems / "keep.wav"
    existing.write_bytes(b"keep")
    monkeypatch.setattr(
        separator, "_normalize_stem",
        lambda source, destination: (_ for _ in ()).throw(SeparationError("normalization failed")),
    )
    with pytest.raises(SeparationError, match="normalization failed"):
        separator.separate(
            _request(UVR_MDX_NET_INST_HQ_5, force=True),
            backend=FakeBackend(UVR_MDX_NET_INST_HQ_5.expected_stems),
            output_root=tmp_path / "output", temp_root=tmp_path / "temp", project_root=tmp_path,
        )
    assert existing.read_bytes() == b"keep"
    assert list((tmp_path / "temp").iterdir()) == []


def test_cached_model_detection(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "model.onnx").write_bytes(b"placeholder")
    (tmp_path / "readme.txt").write_text("not a model", encoding="utf-8")
    assert diagnostics.detect_cached_models(tmp_path) == ("nested/model.onnx",)


def test_separation_info_without_ml_packages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(diagnostics, "is_optional_dependency_installed", lambda name: False)
    report = diagnostics.collect_diagnostics(tmp_path)
    monkeypatch.setattr(app, "collect_diagnostics", lambda: report)
    assert app.main(["separation-info"]) == 0
    output = capsys.readouterr().out
    assert "MusicReviver Separation Diagnostics" in output
    assert "audio-separator installed: NO" in output
    assert "ONNX Runtime installed: NO" in output
    assert "DirectML available: NO" in output
    assert "Default intended model: htdemucs_6s.yaml" in output
    assert all(stem in output for stem in ("vocals", "drums", "bass", "guitar", "piano", "other"))

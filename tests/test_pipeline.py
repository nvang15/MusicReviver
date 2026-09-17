import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from src.mastering.models import MasteringMode
from src.pipeline.exceptions import PipelineCancelled, PipelineError
from src.pipeline.models import PipelineConfig, PipelineStage, PipelineStatus
from src.pipeline.orchestrator import StageRunners, modernize
from src.restoration.models import RestorationStrength
from src.separation.backends import DeviceMode

RATE = 48_000


def tone() -> np.ndarray:
    t = np.arange(RATE) / RATE
    left = .05 * np.sin(2 * np.pi * 220 * t)
    return np.column_stack((left, left * .8))


def wav(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, tone(), RATE, subtype="PCM_24")
    return path


class FakeStages:
    def __init__(self, root: Path, stems=("vocals", "drums"), fail: str | None = None):
        self.root, self.stems, self.fail = root, stems, fail
        self.calls: list[str] = []

    def project(self, input_path):
        return self.root / "output" / Path(input_path).stem

    def check(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise RuntimeError(f"simulated {name} failure")

    def import_media(self, input_path, **kwargs):
        self.check("import")
        directory = self.project(input_path) / "source"
        audio = wav(directory / "original_48k.wav")
        metadata = directory / "metadata.json"
        metadata.write_text("{}", encoding="utf-8")
        return SimpleNamespace(audio_path=audio, metadata_path=metadata)

    def prepare(self, input_path, model_id, device, force):
        self.check("prepare")
        if model_id == "missing-model":
            raise RuntimeError("Unknown separation model 'missing-model'")
        if model_id == "demucs-directml" and device is DeviceMode.DIRECTML:
            raise RuntimeError("does not support DirectML")
        return SimpleNamespace(input_path=input_path, model_id=model_id, force=force)

    def separate(self, request, **kwargs):
        self.check("separation")
        directory = self.project(request.input_path) / "stems"
        stems = {name: wav(directory / f"{name}.wav") for name in self.stems}
        metadata = directory / "separation.json"
        metadata.write_text(json.dumps({"model_filename": request.model_id,
                                        "actual_stems": list(self.stems)}), encoding="utf-8")
        return SimpleNamespace(stems=stems, metadata_path=metadata)

    def analyze(self, input_path, **kwargs):
        self.check("analysis")
        directory = self.project(input_path) / "analysis"
        directory.mkdir(parents=True, exist_ok=True)
        document = {"stems": {name: {} for name in self.stems}}
        js, text = directory / "analysis.json", directory / "analysis.txt"
        js.write_text(json.dumps(document), encoding="utf-8")
        text.write_text("analysis", encoding="utf-8")
        return document, js, text

    def restore(self, input_path, strength, **kwargs):
        self.check("restoration")
        directory = self.project(input_path) / "restored"
        results = {}
        for name in self.stems:
            output = wav(directory / f"{name}_restored.wav")
            results[name] = {"output": output.as_posix()}
        document = {"restoration_strength": strength.value, "results": results}
        js, text = directory / "restoration.json", directory / "restoration.txt"
        js.write_text(json.dumps(document), encoding="utf-8")
        text.write_text("restoration", encoding="utf-8")
        return document, js, text

    def mix(self, input_path, **kwargs):
        self.check("mixing")
        directory = self.project(input_path) / "mix"
        audio = wav(directory / "restored_mix.wav")
        js, text = directory / "mix.json", directory / "mix.txt"
        js.write_text(json.dumps({"output_path": audio.as_posix()}), encoding="utf-8")
        text.write_text("mix", encoding="utf-8")
        return SimpleNamespace(audio_path=audio, metadata_path=js, text_path=text)

    def master(self, input_path, mode, **kwargs):
        self.check("mastering")
        directory = self.project(input_path) / "master"
        if kwargs.get("force") and directory.exists():
            for existing in directory.iterdir():
                existing.unlink()
        audio = wav(directory / f"{mode.value}_master.wav")
        js, text = directory / "master.json", directory / "master.txt"
        js.write_text(json.dumps({"mode": mode.value}), encoding="utf-8")
        text.write_text("master", encoding="utf-8")
        return SimpleNamespace(audio_path=audio, metadata_path=js, text_path=text)

    def runners(self):
        return StageRunners(self.import_media, self.prepare, self.separate, self.analyze,
                            self.restore, self.mix, self.master)


def setup(tmp_path: Path, stems=("vocals", "drums"), fail=None):
    source = tmp_path / "song.wav"
    source.write_bytes(b"deterministic source identity")
    fake = FakeStages(tmp_path, stems, fail)
    kwargs = {"output_root": tmp_path / "output", "project_root": tmp_path,
              "temp_root": tmp_path / "temp", "runners": fake.runners()}
    return source, fake, kwargs


def test_clean_pipeline_order_statuses_result_and_reports(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path)
    result = modernize(source, **kwargs)
    assert fake.calls == ["import", "prepare", "separation", "analysis", "restoration", "mixing", "mastering"]
    assert all(result.stage_records[s].status is PipelineStatus.COMPLETED for s in PipelineStage)
    assert result.mastered_output and result.mastered_output.is_file()
    assert result.pipeline_json.is_file() and result.pipeline_text.is_file()


def test_valid_outputs_reuse_all_stages(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path)
    modernize(source, **kwargs)
    fake.calls.clear()
    result = modernize(source, **kwargs)
    assert fake.calls == []
    assert result.reused_stages == tuple(PipelineStage(s) for s in ("import", "separation", "analysis", "restoration", "mixing", "mastering"))


def test_separation_model_change_invalidates_downstream(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path)
    modernize(source, **kwargs)
    fake.calls.clear()
    modernize(source, config=PipelineConfig(separation_model="new-model"), **kwargs)
    assert fake.calls == ["prepare", "separation", "analysis", "restoration", "mixing", "mastering"]


def test_restoration_change_invalidates_only_restoration_downstream(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path)
    modernize(source, **kwargs)
    fake.calls.clear()
    modernize(source, config=PipelineConfig(restoration_strength=RestorationStrength.STRONG), **kwargs)
    assert fake.calls == ["restoration", "mixing", "mastering"]


def test_mastering_change_invalidates_master_only(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path)
    modernize(source, **kwargs)
    fake.calls.clear()
    result = modernize(source, config=PipelineConfig(mastering_mode=MasteringMode.MODERN), **kwargs)
    assert fake.calls == ["mastering"]
    assert result.mastered_output.name == "modern_master.wav"


def test_device_change_does_not_invalidate_outputs(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path)
    modernize(source, **kwargs)
    fake.calls.clear()
    modernize(source, config=PipelineConfig(device_mode=DeviceMode.CPU), **kwargs)
    assert fake.calls == []


def test_changed_source_invalidates_every_stage(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path)
    modernize(source, **kwargs)
    source.write_bytes(b"changed source")
    fake.calls.clear()
    modernize(source, **kwargs)
    assert fake.calls[0] == "import" and fake.calls[-1] == "mastering"


def test_force_reruns_every_stage(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path)
    modernize(source, **kwargs)
    fake.calls.clear()
    modernize(source, config=PipelineConfig(force=True), **kwargs)
    assert len(fake.calls) == 7


@pytest.mark.parametrize("stems", [("vocals", "drums", "bass", "guitar", "piano", "other"),
                                    ("vocals", "instrumental"), ("organ", "future_texture", "brass")])
def test_dynamic_stem_sets(tmp_path: Path, stems: tuple[str, ...]) -> None:
    source, _, kwargs = setup(tmp_path, stems)
    result = modernize(source, **kwargs)
    assert set(result.separated_stems) == set(stems)
    assert set(result.restored_stems) == set(stems)


def test_failure_stops_downstream_records_failure_and_preserves_output(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path)
    previous = modernize(source, **kwargs).mastered_output.read_bytes()
    fake.fail, fake.calls = "analysis", []
    with pytest.raises(PipelineError) as caught:
        modernize(source, config=PipelineConfig(force=True), **kwargs)
    result = caught.value.result
    assert result.failed_stage is PipelineStage.ANALYSIS
    assert result.stage_records[PipelineStage.RESTORATION].status is PipelineStatus.SKIPPED
    assert "restoration" not in fake.calls and result.mastered_output.read_bytes() == previous


def test_progress_is_ordered_and_cancellation_occurs_between_stages(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path)
    events, cancelled = [], {"value": False}
    def callback(event):
        events.append((event.stage, event.status))
        if event.stage is PipelineStage.IMPORT and event.status is PipelineStatus.COMPLETED:
            cancelled["value"] = True
    with pytest.raises(PipelineCancelled) as caught:
        modernize(source, progress_callback=callback, cancellation_token=lambda: cancelled["value"], **kwargs)
    assert fake.calls == ["import"]
    assert events[:2] == [(PipelineStage.IMPORT, PipelineStatus.RUNNING), (PipelineStage.IMPORT, PipelineStatus.COMPLETED)]
    assert caught.value.result.stage_records[PipelineStage.SEPARATION].status is PipelineStatus.SKIPPED


def test_strict_relative_json_without_nonfinite_values(tmp_path: Path) -> None:
    source, _, kwargs = setup(tmp_path)
    result = modernize(source, **kwargs)
    raw = result.pipeline_json.read_text(encoding="utf-8")
    document = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    assert "NaN" not in raw and "Infinity" not in raw
    assert not Path(document["final_output"]).is_absolute()


@pytest.mark.parametrize("model,device,message", [
    ("missing-model", DeviceMode.AUTO, "Unknown separation model"),
    ("demucs-directml", DeviceMode.DIRECTML, "does not support DirectML"),
])
def test_model_and_device_errors_are_readable(tmp_path: Path, model: str, device: DeviceMode, message: str) -> None:
    source, _, kwargs = setup(tmp_path)
    with pytest.raises(PipelineError, match=message):
        modernize(source, config=PipelineConfig(separation_model=model, device_mode=device), **kwargs)


def test_resume_after_mid_pipeline_failure(tmp_path: Path) -> None:
    source, fake, kwargs = setup(tmp_path, fail="restoration")
    with pytest.raises(PipelineError):
        modernize(source, **kwargs)
    fake.fail, fake.calls = None, []
    result = modernize(source, **kwargs)
    assert fake.calls == ["restoration", "mixing", "mastering"]
    assert result.reused_stages[:3] == (PipelineStage.IMPORT, PipelineStage.SEPARATION, PipelineStage.ANALYSIS)

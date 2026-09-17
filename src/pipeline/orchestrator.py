"""Sequential orchestration of existing MusicReviver stage APIs."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import soundfile as sf

from src.analysis.report import analyze_project
from src.audio.converter import (INTERNAL_CHANNELS, INTERNAL_SAMPLE_RATE,
                                 convert_media, safe_project_name)
from src.config import OUTPUT_DIR, PROJECT_ROOT, TEMP_DIR
from src.mastering.processor import master_project
from src.mixing.mixer import mix_project
from src.pipeline.exceptions import PipelineCancelled, PipelineError
from src.pipeline.models import (PipelineConfig, PipelineResult, PipelineStage,
                                 PipelineStatus, StageRecord)
from src.pipeline.progress import PipelineProgress
from src.pipeline.report import render_pipeline_report
from src.restoration.processor import restore_project
from src.separation.separator import prepare_separation, separate

SCHEMA_VERSION = "1.0"
STAGES = (PipelineStage.IMPORT, PipelineStage.SEPARATION, PipelineStage.ANALYSIS,
          PipelineStage.RESTORATION, PipelineStage.MIXING, PipelineStage.MASTERING)
ProgressCallback = Callable[[PipelineProgress], None]


class CancellationToken(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True)
class StageRunners:
    """Injectable stage adapters used by tests and future alternate front ends."""

    import_media: Callable[..., Any] = convert_media
    prepare_separation: Callable[..., Any] = prepare_separation
    separate: Callable[..., Any] = separate
    analyze: Callable[..., Any] = analyze_project
    restore: Callable[..., Any] = restore_project
    mix: Callable[..., Any] = mix_project
    master: Callable[..., Any] = master_project


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _canonical(path: Path) -> bool:
    try:
        info = sf.info(path)
    except (OSError, RuntimeError, ValueError):
        return False
    return (info.samplerate == INTERNAL_SAMPLE_RATE and info.channels == INTERNAL_CHANNELS
            and info.subtype == "PCM_24" and info.frames > 0)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _valid_outputs(stage: PipelineStage, project: Path, config: PipelineConfig) -> list[Path]:
    if stage is PipelineStage.IMPORT:
        audio, metadata = project / "source" / "original_48k.wav", project / "source" / "metadata.json"
        return [audio, metadata] if _canonical(audio) and _read_json(metadata) is not None else []
    if stage is PipelineStage.SEPARATION:
        directory, metadata = project / "stems", project / "stems" / "separation.json"
        document = _read_json(metadata)
        if not document or document.get("model_filename") != config.separation_model:
            return []
        names = document.get("actual_stems")
        stems = [directory / f"{name}.wav" for name in names] if isinstance(names, list) else []
        return [*stems, metadata] if stems and all(_canonical(path) for path in stems) else []
    if stage is PipelineStage.ANALYSIS:
        metadata, text = project / "analysis" / "analysis.json", project / "analysis" / "analysis.txt"
        document = _read_json(metadata)
        stem_names = {path.stem for path in (project / "stems").glob("*.wav")}
        return [metadata, text] if document and text.is_file() and set(document.get("stems", {})) == stem_names else []
    if stage is PipelineStage.RESTORATION:
        directory, metadata = project / "restored", project / "restored" / "restoration.json"
        document = _read_json(metadata)
        if not document or document.get("restoration_strength") != config.restoration_strength.value:
            return []
        results = document.get("results", {})
        files = [directory / f"{name}_restored.wav" for name in results]
        return [*files, metadata, directory / "restoration.txt"] if files and all(_canonical(path) for path in files) else []
    if stage is PipelineStage.MIXING:
        metadata, text = project / "mix" / "mix.json", project / "mix" / "mix.txt"
        document = _read_json(metadata)
        candidates = list((project / "mix").glob("*_mix.wav"))
        return [candidates[0], metadata, text] if document and len(candidates) == 1 and _canonical(candidates[0]) and text.is_file() else []
    if stage is PipelineStage.MASTERING:
        metadata, text = project / "master" / "master.json", project / "master" / "master.txt"
        document = _read_json(metadata)
        audio = project / "master" / f"{config.mastering_mode.value}_master.wav"
        return [audio, metadata, text] if document and document.get("mode") == config.mastering_mode.value and _canonical(audio) and text.is_file() else []
    return []


def _cancelled(token: CancellationToken | Callable[[], bool] | None) -> bool:
    if token is None:
        return False
    return bool(token() if callable(token) else token.is_set())


def _make_result(input_path: Path, project_name: str, project: Path,
                 records: dict[PipelineStage, StageRecord], warnings: list[str],
                 total: float, failed: PipelineStage | None) -> PipelineResult:
    separated = {p.stem: p for p in (project / "stems").glob("*.wav") if p.is_file()}
    restored = {p.stem.removesuffix("_restored"): p for p in (project / "restored").glob("*_restored.wav") if p.is_file()}
    mixes = list((project / "mix").glob("*_mix.wav"))
    masters = list((project / "master").glob("*_master.wav"))
    return PipelineResult(project_name, input_path, (project / "source" / "original_48k.wav") if (project / "source" / "original_48k.wav").is_file() else None,
                          separated, tuple(p for p in (project / "analysis" / "analysis.json", project / "analysis" / "analysis.txt") if p.is_file()),
                          restored, mixes[0] if len(mixes) == 1 else None,
                          masters[0] if len(masters) == 1 else None, tuple(warnings), records,
                          total, tuple(stage for stage, record in records.items() if record.status is PipelineStatus.REUSED),
                          failed, project / "pipeline" / "pipeline.json", project / "pipeline" / "pipeline.txt")


def _document(result: PipelineResult, config: PipelineConfig, identity: dict[str, Any],
              project_root: Path) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "project": result.project_name,
            "input_identity": identity, "configuration": config.to_dict(),
            "stages": {stage.value: record.to_dict() for stage, record in result.stage_records.items()},
            "warnings": list(result.warnings), "failed_stage": result.failed_stage.value if result.failed_stage else None,
            "total_processing_time_seconds": result.total_duration,
            "reused_stages": [stage.value for stage in result.reused_stages],
            "final_output": _relative(result.mastered_output, project_root) if result.mastered_output else None,
            "output_paths": {
                "standardized_source": _relative(result.standardized_source_path, project_root) if result.standardized_source_path else None,
                "stems": {name: _relative(path, project_root) for name, path in result.separated_stems.items()},
                "analysis_reports": [_relative(path, project_root) for path in result.analysis_reports],
                "restored_stems": {name: _relative(path, project_root) for name, path in result.restored_stems.items()},
                "mix": _relative(result.mixed_output, project_root) if result.mixed_output else None,
                "master": _relative(result.mastered_output, project_root) if result.mastered_output else None,
            }, "updated_at": datetime.now(timezone.utc).isoformat()}


def _publish(result: PipelineResult, config: PipelineConfig, identity: dict[str, Any],
             project_root: Path) -> None:
    directory = result.pipeline_json.parent
    directory.mkdir(parents=True, exist_ok=True)
    document = _document(result, config, identity, project_root)
    json_temp, text_temp = directory / ".pipeline.tmp.json", directory / ".pipeline.tmp.txt"
    json_temp.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    text_temp.write_text(render_pipeline_report(document), encoding="utf-8")
    os.replace(json_temp, result.pipeline_json)
    os.replace(text_temp, result.pipeline_text)


def modernize(input_path: Path, *, config: PipelineConfig | None = None,
              progress_callback: ProgressCallback | None = None,
              cancellation_token: CancellationToken | Callable[[], bool] | None = None,
              output_root: Path = OUTPUT_DIR, project_root: Path = PROJECT_ROOT,
              temp_root: Path = TEMP_DIR, runners: StageRunners | None = None) -> PipelineResult:
    """Run or safely resume the complete pipeline through existing backend APIs."""
    config, runners = config or PipelineConfig(), runners or StageRunners()
    input_path = Path(input_path)
    if not input_path.is_file():
        raise PipelineError(f"Input media does not exist: {input_path}")
    started = time.perf_counter()
    project_name, project = safe_project_name(input_path), output_root / safe_project_name(input_path)
    pipeline_dir = project / "pipeline"
    prior = _read_json(pipeline_dir / "pipeline.json") if config.resume and not config.force else None
    identity = {"path": _relative(input_path, project_root), "size_bytes": input_path.stat().st_size,
                "sha256": _sha256(input_path)}
    source_key = identity["sha256"]
    fingerprints = {
        PipelineStage.IMPORT: _fingerprint(source_key, "import-v1"),
        PipelineStage.SEPARATION: _fingerprint(source_key, config.separation_model, "separation-v1"),
    }
    fingerprints[PipelineStage.ANALYSIS] = _fingerprint(fingerprints[PipelineStage.SEPARATION], "analysis-v1")
    fingerprints[PipelineStage.RESTORATION] = _fingerprint(fingerprints[PipelineStage.ANALYSIS], config.restoration_strength.value, "restoration-v1")
    fingerprints[PipelineStage.MIXING] = _fingerprint(fingerprints[PipelineStage.RESTORATION], "mixing-v1")
    fingerprints[PipelineStage.MASTERING] = _fingerprint(fingerprints[PipelineStage.MIXING], config.mastering_mode.value, "mastering-v1")
    records = {stage: StageRecord(stage) for stage in STAGES}
    records[PipelineStage.COMPLETE] = StageRecord(PipelineStage.COMPLETE)
    warnings: list[str] = []

    def emit(stage: PipelineStage, status: PipelineStatus, message: str) -> None:
        if progress_callback:
            progress_callback(PipelineProgress(stage, status, message, None, time.perf_counter() - started))

    def snapshot(failed: PipelineStage | None = None) -> PipelineResult:
        result = _make_result(input_path, project_name, project, records, warnings,
                              time.perf_counter() - started, failed)
        _publish(result, config, identity, project_root)
        return result

    previous_stages = prior.get("stages", {}) if prior else {}
    for index, stage in enumerate(STAGES):
        if _cancelled(cancellation_token):
            for remaining in STAGES[index:]:
                records[remaining].status = PipelineStatus.SKIPPED
                records[remaining].message = "Skipped after cancellation."
            result = snapshot()
            raise PipelineCancelled(f"Pipeline cancelled before {stage.value}.", result=result)
        prior_record = previous_stages.get(stage.value, {})
        valid = _valid_outputs(stage, project, config)
        reusable = (config.resume and not config.force and prior_record.get("fingerprint") == fingerprints[stage]
                    and bool(valid))
        if reusable:
            records[stage] = StageRecord(stage, PipelineStatus.REUSED, 0.0, fingerprints[stage],
                                         [_relative(path, project_root) for path in valid], "Valid compatible output reused.")
            emit(stage, PipelineStatus.REUSED, records[stage].message)
            continue
        records[stage].status, records[stage].fingerprint = PipelineStatus.RUNNING, fingerprints[stage]
        emit(stage, PipelineStatus.RUNNING, f"Running {stage.value} stage.")
        stage_started = time.perf_counter()
        replace = config.force or bool(valid) or any((project / name).exists() for name in {
            PipelineStage.IMPORT: ("source",), PipelineStage.SEPARATION: ("stems",),
            PipelineStage.ANALYSIS: ("analysis",), PipelineStage.RESTORATION: ("restored",),
            PipelineStage.MIXING: ("mix",), PipelineStage.MASTERING: ("master",)}[stage])
        try:
            if stage is PipelineStage.IMPORT:
                value = runners.import_media(input_path, output_root=output_root, project_root=project_root, force=replace)
                outputs = [value.audio_path, value.metadata_path]
            elif stage is PipelineStage.SEPARATION:
                request = runners.prepare_separation(input_path, model_id=config.separation_model,
                                                     device=config.device_mode, force=replace)
                value = runners.separate(request, output_root=output_root, project_root=project_root, temp_root=temp_root)
                outputs = [*value.stems.values(), value.metadata_path]
            elif stage is PipelineStage.ANALYSIS:
                _, json_path, text_path = runners.analyze(input_path, force=replace, output_root=output_root,
                                                         project_root=project_root, temp_root=temp_root)
                outputs = [json_path, text_path]
            elif stage is PipelineStage.RESTORATION:
                _, json_path, text_path = runners.restore(input_path, strength=config.restoration_strength,
                                                         force=replace, output_root=output_root,
                                                         project_root=project_root, temp_root=temp_root)
                outputs = [*_valid_outputs(stage, project, config), json_path, text_path]
            elif stage is PipelineStage.MIXING:
                value = runners.mix(input_path, force=replace, output_root=output_root,
                                    project_root=project_root, temp_root=temp_root)
                outputs = [value.audio_path, value.metadata_path, value.text_path]
            else:
                value = runners.master(input_path, mode=config.mastering_mode, force=replace,
                                       output_root=output_root, project_root=project_root, temp_root=temp_root)
                outputs = [value.audio_path, value.metadata_path, value.text_path]
            records[stage] = StageRecord(stage, PipelineStatus.COMPLETED, time.perf_counter() - stage_started,
                                         fingerprints[stage], list(dict.fromkeys(_relative(Path(path), project_root) for path in outputs)),
                                         f"{stage.value.title()} completed.")
            emit(stage, PipelineStatus.COMPLETED, records[stage].message)
            snapshot()
        except Exception as exc:
            records[stage].status = PipelineStatus.FAILED
            records[stage].duration_seconds = time.perf_counter() - stage_started
            records[stage].error = str(exc)
            records[stage].message = f"{stage.value.title()} failed."
            for remaining in STAGES[index + 1:]:
                records[remaining].status = PipelineStatus.SKIPPED
                records[remaining].message = "Skipped because an upstream stage failed."
            emit(stage, PipelineStatus.FAILED, records[stage].message)
            result = snapshot(stage)
            raise PipelineError(f"Pipeline failed during {stage.value}: {exc}", result=result) from exc
    records[PipelineStage.COMPLETE] = StageRecord(PipelineStage.COMPLETE, PipelineStatus.COMPLETED,
                                                  time.perf_counter() - started, message="Pipeline complete.")
    emit(PipelineStage.COMPLETE, PipelineStatus.COMPLETED, "Pipeline complete.")
    return snapshot()

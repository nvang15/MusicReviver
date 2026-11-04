import os
import threading
import time
from pathlib import Path

import pytest

from src.exporting import AudioFormat, ExportConfig, ExportResult, ExportCancelled
from src.gui.models import GuiResult, GuiTask, GuiJobConfig
from src.gui.export_worker import ExportWorker
from src.gui import main_window, worker
from src.gui.model_readiness import model_readiness


@pytest.fixture(scope="module")
def application():
    previous = os.environ.get("QT_QPA_PLATFORM")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from src.gui.app import create_application
    app = create_application(["export-tests"])
    yield app
    if previous is None:
        os.environ.pop("QT_QPA_PLATFORM", None)
    else:
        os.environ["QT_QPA_PLATFORM"] = previous


def test_dialog_defaults_selection_and_report_controls(application, tmp_path):
    from src.gui.export_dialog import ExportDialog
    from PySide6.QtCore import Qt
    master, stem = tmp_path / "master.wav", tmp_path / "unexpected instrument.wav"
    result = GuiResult(GuiTask.MODERNIZE, "song", 1, master, (master, stem), tmp_path, "done")
    dialog = ExportDialog(result, str(tmp_path))
    assert dialog.selected_files() == (master,)
    assert dialog.config().format is AudioFormat.WAV
    assert dialog.quality.isHidden()
    dialog.format.setCurrentIndex(dialog.format.findData(AudioFormat.MP3))
    assert not dialog.quality.isHidden() and dialog.config().bitrate_kbps == 320
    dialog.select_all(True)
    assert dialog.selected_files() == (master, stem)
    dialog.files.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.selected_files() == (stem,)
    reports = GuiResult(GuiTask.ANALYZE, "song", 1, None,
                        (tmp_path / "analysis.json", tmp_path / "analysis.txt"), tmp_path, "done")
    report_dialog = ExportDialog(reports)
    assert report_dialog.format.isHidden() and report_dialog.quality.isHidden()
    dialog.close()
    report_dialog.close()


def test_export_worker_success_failure_cancel(application, tmp_path):
    config = ExportConfig(tmp_path)
    expected = ExportResult((), .1)
    success, failure, cancelled, finished = [], [], [], []
    def run(files, config, **kwargs):
        assert callable(kwargs["progress_callback"]) and callable(kwargs["cancelled"])
        return expected
    instance = ExportWorker((), config, runner=run)
    instance.completed.connect(success.append)
    instance.finished.connect(lambda: finished.append(True))
    instance.run()
    assert success == [expected] and finished == [True]
    def fail(*args, **kwargs):
        raise RuntimeError("disk unavailable")
    instance = ExportWorker((), config, runner=fail)
    instance.failed.connect(lambda message, details: failure.append((message, details)))
    instance.run()
    assert failure[0][0] == "disk unavailable" and "RuntimeError" in failure[0][1]
    def cancel(*args, **kwargs):
        assert kwargs["cancelled"]()
        raise ExportCancelled("cancelled between files")
    instance = ExportWorker((), config, runner=cancel)
    instance.cancelled.connect(cancelled.append)
    instance.request_cancel()
    instance.run()
    assert cancelled == ["cancelled between files"]


def test_export_thread_blocks_conflicting_jobs_and_restores_controls(application, tmp_path, monkeypatch):
    from PySide6.QtCore import QObject, Signal, Slot
    started, release = threading.Event(), threading.Event()
    class SlowWorker(QObject):
        progress = Signal(object)
        completed = Signal(object)
        failed = Signal(str, str)
        cancelled = Signal(str)
        finished = Signal()
        def __init__(self, *args):
            super().__init__()
        @Slot()
        def run(self):
            started.set()
            release.wait(3)
            self.completed.emit(ExportResult((), .1))
            self.finished.emit()
        def request_cancel(self):
            release.set()
    class Dialog:
        calls = 0
        def __init__(self, *args):
            Dialog.calls += 1
        def exec(self): return True
        def config(self): return ExportConfig(tmp_path)
        def selected_files(self): return (tmp_path / "master.wav",)
    monkeypatch.setattr(main_window, "ExportDialog", Dialog)
    monkeypatch.setattr(main_window, "ExportWorker", SlowWorker)
    window = main_window.MainWindow(show_dialogs=False)
    window.current_result = GuiResult(GuiTask.MODERNIZE, "song", 1, tmp_path / "master.wav",
                                     (tmp_path / "master.wav",), tmp_path, "done")
    window.export_result()
    try:
        assert started.wait(1)
        assert not window.start_button.isEnabled() and not window.output_panel.export_button.isEnabled()
        window.export_result()
        window.start_processing()
        assert Dialog.calls == 1
        window.cancel_processing()
        deadline = time.monotonic() + 3
        while window.thread is not None and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(.01)
        assert window.thread is None and window.start_button.isEnabled()
        assert window.output_panel.export_button.isEnabled()
    finally:
        release.set()
        window.close()


def test_restored_paths_resolve_against_runtime_not_cwd(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(worker, "PROJECT_ROOT", runtime)
    monkeypatch.setattr(worker, "restore_project", lambda *args, **kwargs:
        ({"results": {"future": {"output": "output/song/restored/future.wav"}}},
         runtime / "restoration.json", runtime / "restoration.txt"))
    result = worker.run_gui_job(GuiJobConfig(tmp_path / "song.wav", task=GuiTask.RESTORE),
                               lambda event: None, threading.Event())
    assert result.files[0] == runtime / "output/song/restored/future.wav"


def test_model_readiness_is_honest_about_auxiliary_downloads(tmp_path):
    identifier = "UVR-MDX-NET-Inst_HQ_5.onnx"
    assert "missing" in model_readiness(identifier, tmp_path)
    (tmp_path / identifier).write_bytes(b"model")
    message = model_readiness(identifier, tmp_path)
    assert "present" in message and "does not guarantee" in message and str(tmp_path) in message

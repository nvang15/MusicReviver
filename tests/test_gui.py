import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QPalette

from src.gui.app import create_application
from src.gui import main_window
from src.gui.main_window import MainWindow
from src.gui.models import GuiJobConfig, GuiResult, GuiTask, export_files
from src.gui.worker import ProcessingWorker
from src.mastering.models import MasteringMode
from src.pipeline.models import PipelineStage, PipelineStatus
from src.pipeline.progress import PipelineProgress
from src.restoration.models import RestorationStrength
from src.separation.models import MODEL_REGISTRY


@pytest.fixture(scope="session")
def application():
    return create_application(["musicreviver-test"])


def pump(application, condition=lambda: True, timeout=1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if condition():
            return
        time.sleep(.01)
    assert condition()


def result(tmp_path: Path, task=GuiTask.MODERNIZE, names=("vocals", "future_texture")):
    files = tuple((tmp_path / f"{name}.wav") for name in names)
    for path in files:
        path.write_bytes(path.name.encode())
    return GuiResult(task, "project", .25, files[0] if task is GuiTask.MODERNIZE else None,
                     files, tmp_path, "Completed.")


class FakeWorker(QObject):
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str)
    finished = Signal()
    instances = []
    next_result = None
    auto_finish = True

    def __init__(self, config):
        super().__init__()
        self.config, self.cancel_requested = config, False
        self.__class__.instances.append(self)

    @Slot()
    def run(self):
        self.progress.emit(PipelineProgress(PipelineStage.IMPORT, PipelineStatus.RUNNING,
                                           "Importing", None, .1))
        if self.auto_finish:
            self.completed.emit(self.next_result)
            self.finished.emit()

    def request_cancel(self):
        self.cancel_requested = True


def window(application, tmp_path: Path):
    FakeWorker.instances.clear()
    FakeWorker.auto_finish = True
    FakeWorker.next_result = result(tmp_path)
    value = MainWindow(worker_factory=FakeWorker, show_dialogs=False)
    value.file_picker.set_path(tmp_path / "song.wav")
    (tmp_path / "song.wav").write_bytes(b"media")
    return value


def test_main_window_constructs_and_balanced_defaults(application, tmp_path: Path) -> None:
    value = window(application, tmp_path)
    assert value.windowTitle() == "MusicReviver"
    assert value.selected_task is GuiTask.MODERNIZE
    assert value.options_panel.restoration_combo.currentData() == RestorationStrength.BALANCED.value
    assert value.options_panel.mastering_combo.currentData() == MasteringMode.BALANCED.value
    value.close()


def test_application_dark_theme_has_readable_enabled_and_disabled_colors(application) -> None:
    palette = application.palette()
    assert palette.color(QPalette.ColorRole.Window).name() == "#1e1f22"
    assert palette.color(QPalette.ColorRole.WindowText).name() == "#f1f3f5"
    assert palette.color(QPalette.ColorRole.Base).name() == "#25282c"
    assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name() == "#9299a3"
    stylesheet = application.styleSheet()
    for selector in ("QLabel", "QLineEdit", "QPushButton", "QRadioButton", "QComboBox",
                     "QGroupBox", "QPlainTextEdit", "QTextEdit", "QProgressBar", "QListWidget"):
        assert selector in stylesheet


def test_input_model_and_task_option_visibility(application, tmp_path: Path) -> None:
    value = window(application, tmp_path)
    chosen = tmp_path / "other.flac"
    value.file_picker.set_path(chosen)
    assert value.file_picker.path == chosen
    value.task_buttons[GuiTask.ANALYZE].setChecked(True)
    assert value.options_panel.model_combo.isHidden()
    value.task_buttons[GuiTask.SEPARATE].setChecked(True)
    assert not value.options_panel.model_combo.isHidden() and value.options_panel.restoration_combo.isHidden()
    value.close()


def test_browse_action_updates_input(application, tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    value = window(application, tmp_path)
    chosen = tmp_path / "picked.wav"
    monkeypatch.setattr("src.gui.widgets.file_picker.QFileDialog.getOpenFileName",
                        lambda *args: (str(chosen), "Media files"))
    value.file_picker.browse()
    assert value.file_picker.path == chosen
    value.close()


def test_open_folder_dispatches_to_windows_startfile(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    opened = []
    monkeypatch.setattr(main_window.sys, "platform", "win32")
    monkeypatch.setattr(main_window.os, "startfile", lambda path: opened.append(path), raising=False)
    main_window.open_folder(tmp_path)
    assert opened == [str(tmp_path)]


@pytest.mark.parametrize("platform,command", [("linux", "xdg-open"), ("darwin", "open")])
def test_open_folder_dispatches_to_platform_command(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch,
                                                    platform: str, command: str) -> None:
    launched = []
    monkeypatch.setattr(main_window.sys, "platform", platform)
    monkeypatch.setattr(main_window.subprocess, "Popen", lambda args: launched.append(args))
    main_window.open_folder(tmp_path)
    assert launched == [[command, str(tmp_path)]]


def test_open_folder_failure_is_reported_readably(application, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    value = window(application, tmp_path)
    value.current_result = result(tmp_path)
    monkeypatch.setattr(main_window, "open_folder",
                        lambda path: (_ for _ in ()).throw(OSError("opener unavailable")))
    value.open_output_folder()
    assert "Could not open the output folder" in value.progress_panel.details.toPlainText()
    assert "opener unavailable" in value.progress_panel.details.toPlainText()
    value.close()


def test_mode_strength_and_dynamic_model_options(application, tmp_path: Path) -> None:
    value = window(application, tmp_path)
    assert value.options_panel.model_combo.count() == len(MODEL_REGISTRY)
    assert {value.options_panel.mastering_combo.itemData(i) for i in range(3)} == {mode.value for mode in MasteringMode}
    assert {value.options_panel.restoration_combo.itemData(i) for i in range(3)} == {mode.value for mode in RestorationStrength}
    value.options_panel.model_combo.setCurrentIndex(value.options_panel.model_combo.findData("htdemucs_6s.yaml"))
    directml = value.options_panel.device_combo.model().item(value.options_panel.device_combo.findData("directml"))
    assert not directml.isEnabled()
    value.close()


def test_unsupported_input_has_friendly_validation(application, tmp_path: Path) -> None:
    value = window(application, tmp_path)
    bad = tmp_path / "notes.txt"
    bad.write_text("x", encoding="utf-8")
    value.file_picker.set_path(bad)
    value.start_processing()
    assert "not supported" in value.progress_panel.details.toPlainText()
    assert value.thread is None
    value.close()


def test_worker_emits_completion_failure_and_progress(tmp_path: Path) -> None:
    source = tmp_path / "song.wav"
    source.write_bytes(b"x")
    config = GuiJobConfig(source)
    expected = result(tmp_path)
    completed, failed, progress = [], [], []
    worker = ProcessingWorker(config, runner=lambda c, cb, token: (cb(PipelineProgress(
        PipelineStage.IMPORT, PipelineStatus.RUNNING, "Working", None, .1)), expected)[1])
    worker.completed.connect(completed.append)
    worker.failed.connect(lambda summary, details: failed.append(summary))
    worker.progress.connect(progress.append)
    worker.run()
    assert completed == [expected] and not failed and progress[0].stage is PipelineStage.IMPORT
    broken = ProcessingWorker(config, runner=lambda *args: (_ for _ in ()).throw(RuntimeError("readable failure")))
    broken.failed.connect(lambda summary, details: failed.append(summary))
    broken.run()
    assert failed == ["readable failure"]


def test_progress_event_maps_to_stage_display(application, tmp_path: Path) -> None:
    value = window(application, tmp_path)
    value.progress_panel.apply_event(PipelineProgress(PipelineStage.SEPARATION,
        PipelineStatus.RUNNING, "Separating stems", None, 2.4))
    assert value.progress_panel.stage_label.text() == "Separation"
    assert value.progress_panel.bar.maximum() == 0
    assert "Separating stems" in value.progress_panel.message_label.text()
    value.close()


def test_processing_disables_restores_and_prevents_duplicates(application, tmp_path: Path) -> None:
    value = window(application, tmp_path)
    value.start_processing()
    assert not value.start_button.isEnabled() and not value.file_picker.browse_button.isEnabled()
    value.start_processing()
    assert len(FakeWorker.instances) == 1
    pump(application, lambda: value.thread is None)
    assert value.start_button.isEnabled() and value.file_picker.browse_button.isEnabled()
    value.close()


def test_cancellation_is_forwarded(application, tmp_path: Path) -> None:
    value = window(application, tmp_path)
    FakeWorker.auto_finish = False
    value.start_processing()
    pump(application, lambda: bool(FakeWorker.instances))
    value.cancel_processing()
    assert FakeWorker.instances[0].cancel_requested
    FakeWorker.instances[0].finished.emit()
    pump(application, lambda: value.thread is None)
    value.close()


def test_results_accept_arbitrary_stems_and_final_master(application, tmp_path: Path) -> None:
    value = window(application, tmp_path)
    expected = result(tmp_path, names=("organ", "future_texture", "brass"))
    value.output_panel.set_result(expected)
    assert value.output_panel.files_list.count() == 3
    assert str(expected.primary_output) in value.output_panel.primary_label.text()
    value.close()


def test_export_final_master_stems_and_collisions(tmp_path: Path) -> None:
    source_a, source_b = tmp_path / "a" / "master.wav", tmp_path / "b" / "organ.wav"
    source_a.parent.mkdir(); source_b.parent.mkdir()
    source_a.write_bytes(b"master"); source_b.write_bytes(b"organ")
    destination = tmp_path / "export"
    first = export_files((source_a, source_b), destination)
    second = export_files((source_a,), destination)
    assert [path.name for path in first] == ["master.wav", "organ.wav"]
    assert second[0].name == "master_2.wav" and second[0].read_bytes() == b"master"


def test_backend_error_is_readable_without_traceback_in_summary(application, tmp_path: Path) -> None:
    value = window(application, tmp_path)
    value._job_failed("No canonical stems were found.", "technical traceback")
    assert "Run Separate Instruments first" in value.progress_panel.message_label.text()
    assert "technical traceback" in value.progress_panel.details.toPlainText()
    value.close()


def test_offscreen_launch_smoke_and_import_is_idle(application, tmp_path: Path) -> None:
    value = window(application, tmp_path)
    value.show()
    pump(application)
    assert value.isVisible() and value.thread is None and not FakeWorker.instances
    value.close()


def test_gui_sources_do_not_use_argparse() -> None:
    gui_root = Path(__file__).parents[1] / "src" / "gui"
    assert all("argparse" not in path.read_text(encoding="utf-8") for path in gui_root.rglob("*.py"))

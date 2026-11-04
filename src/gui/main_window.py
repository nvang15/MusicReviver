"""MusicReviver main desktop window."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Qt
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QGroupBox, QHBoxLayout,
                               QLabel, QMainWindow, QMessageBox, QPushButton,
                               QRadioButton, QVBoxLayout, QWidget)

from src.gui.models import GuiJobConfig, GuiResult, GuiTask
from src.gui.widgets.file_picker import FilePicker
from src.gui.widgets.options_panel import OptionsPanel
from src.gui.widgets.output_panel import OutputPanel
from src.gui.widgets.progress_panel import ProgressPanel
from src.gui.worker import ProcessingWorker
from src.gui.export_dialog import ExportDialog
from src.gui.export_worker import ExportWorker
from src.gui.model_readiness import model_readiness
from src.mastering.models import MasteringMode
from src.restoration.models import RestorationStrength
from src.separation.backends import DeviceMode


TASK_LABELS = {
    GuiTask.SEPARATE: "Separate Instruments",
    GuiTask.ANALYZE: "Analyze Recording",
    GuiTask.RESTORE: "Restore Stems",
    GuiTask.MODERNIZE: "Modernize Recording",
}


class MainWindow(QMainWindow):
    def __init__(self, *, worker_factory=ProcessingWorker, show_dialogs: bool = True) -> None:
        super().__init__()
        self.worker_factory = worker_factory
        self.show_dialogs = show_dialogs
        self.thread: QThread | None = None
        self.worker: ProcessingWorker | None = None
        self.current_result: GuiResult | None = None
        self.settings = QSettings("MusicReviver", "MusicReviver")
        self.setWindowTitle("MusicReviver")
        self.resize(900, 680)
        self.setAcceptDrops(True)
        self._build_ui()

    def _build_ui(self) -> None:
        central, layout = QWidget(), QVBoxLayout()
        central.setLayout(layout)
        self.setCentralWidget(central)
        title = QLabel("MusicReviver")
        title.setObjectName("title")
        subtitle = QLabel("Restore and modernize older recordings while preserving the original performance.")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Input recording"))
        self.file_picker = FilePicker()
        layout.addWidget(self.file_picker)

        tasks = QGroupBox("What would you like to do?")
        task_layout = QHBoxLayout(tasks)
        self.task_group = QButtonGroup(self)
        self.task_buttons = {}
        for task, text in TASK_LABELS.items():
            button = QRadioButton(text)
            self.task_group.addButton(button)
            self.task_buttons[task] = button
            task_layout.addWidget(button)
            button.toggled.connect(lambda checked, value=task: checked and self.set_task(value))
        layout.addWidget(tasks)
        self.options_panel = OptionsPanel()
        layout.addWidget(self.options_panel)
        self.task_buttons[GuiTask.MODERNIZE].setChecked(True)
        controls = QHBoxLayout()
        controls.addStretch()
        self.start_button, self.cancel_button = QPushButton("Start Processing"), QPushButton("Cancel")
        self.start_button.setDefault(True)
        self.cancel_button.setEnabled(False)
        controls.addWidget(self.start_button)
        controls.addWidget(self.cancel_button)
        layout.addLayout(controls)
        self.cancel_note = QLabel("Cancellation will occur after the current processing stage completes.")
        self.cancel_note.setVisible(False)
        layout.addWidget(self.cancel_note)
        self.progress_panel, self.output_panel = ProgressPanel(), OutputPanel()
        layout.addWidget(self.progress_panel)
        layout.addWidget(self.output_panel, 1)
        self.start_button.clicked.connect(self.start_processing)
        self.cancel_button.clicked.connect(self.cancel_processing)
        self.output_panel.open_folder_requested.connect(self.open_output_folder)
        self.output_panel.export_requested.connect(self.export_result)

    @property
    def selected_task(self) -> GuiTask:
        return next(task for task, button in self.task_buttons.items() if button.isChecked())

    def set_task(self, task: GuiTask) -> None:
        self.options_panel.set_task(task)

    def job_config(self) -> GuiJobConfig:
        return GuiJobConfig(self.file_picker.path, self.selected_task,
                            self.options_panel.model_combo.currentData(),
                            DeviceMode(self.options_panel.device_combo.currentData()),
                            RestorationStrength(self.options_panel.restoration_combo.currentData()),
                            MasteringMode(self.options_panel.mastering_combo.currentData()))

    def _friendly_error(self, summary: str, details: str = "") -> None:
        self.progress_panel.details.appendPlainText(details or summary)
        if self.show_dialogs:
            box = QMessageBox(QMessageBox.Critical, "MusicReviver", summary, parent=self)
            if details:
                box.setDetailedText(details)
            box.exec()

    def start_processing(self) -> None:
        if self.thread is not None:
            return
        config = self.job_config()
        error = config.validate()
        if error:
            self._friendly_error(error)
            return
        if config.task in (GuiTask.MODERNIZE, GuiTask.SEPARATE) and self.show_dialogs:
            choice = QMessageBox.question(self, "Separation model",
                model_readiness(config.separation_model) + "\n\nContinue and allow any required model downloads?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes:
                return
        self.cancel_note.setText("Cancellation will occur after the current processing stage completes.")
        self._set_processing(True)
        self.progress_panel.begin()
        self.thread = QThread(self)
        self.worker = self.worker_factory(config)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress_panel.apply_event)
        self.worker.completed.connect(self._job_completed)
        self.worker.failed.connect(self._job_failed)
        self.worker.cancelled.connect(self._job_cancelled)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    def cancel_processing(self) -> None:
        if self.worker:
            self.worker.request_cancel()
            self.cancel_button.setEnabled(False)
            self.progress_panel.message_label.setText("Cancellation requested; waiting for the current stage or file to finish.")

    def _set_processing(self, active: bool) -> None:
        self.file_picker.set_controls_enabled(not active)
        for button in self.task_buttons.values():
            button.setEnabled(not active)
        self.options_panel.setEnabled(not active)
        self.start_button.setEnabled(not active)
        self.cancel_button.setEnabled(active)
        self.cancel_note.setVisible(active)
        self.output_panel.export_button.setEnabled(not active and bool(self.current_result and self.current_result.files))

    def _job_completed(self, result: GuiResult) -> None:
        self.current_result = result
        self.output_panel.set_result(result)
        self.output_panel.export_button.setEnabled(False)
        self.progress_panel.finish(result.summary, True)

    def _job_failed(self, summary: str, details: str) -> None:
        friendly = summary
        if "No canonical stems" in summary:
            friendly = "Stem separation has not been run for this project yet. Run Separate Instruments first, or use Modernize Recording."
        self.progress_panel.finish(friendly, False)
        self._friendly_error(friendly, details)

    def _job_cancelled(self, message: str) -> None:
        self.progress_panel.finish(message, False)

    def _thread_finished(self) -> None:
        if self.thread:
            self.thread.deleteLater()
        self.thread, self.worker = None, None
        self._set_processing(False)

    def open_output_folder(self) -> None:
        if not self.current_result or not self.current_result.output_folder:
            return
        try:
            open_folder(self.current_result.output_folder)
        except OSError as exc:
            self._friendly_error(f"Could not open the output folder: {exc}")

    def export_result(self) -> None:
        if not self.current_result or self.thread is not None:
            return
        initial = self.settings.value("last_export_directory", "", str)
        dialog = ExportDialog(self.current_result, initial, self)
        if not dialog.exec():
            return
        config = dialog.config()
        self.settings.setValue("last_export_directory", str(config.destination))
        self._set_processing(True)
        self.cancel_note.setText("Cancellation will occur after the current file completes, before publication.")
        self.progress_panel.begin()
        self.thread = QThread(self)
        self.worker = ExportWorker(dialog.selected_files(), config)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._export_progress)
        self.worker.completed.connect(self._export_completed)
        self.worker.failed.connect(self._job_failed)
        self.worker.cancelled.connect(self._job_cancelled)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    def _export_progress(self, event):
        self.progress_panel.stage_label.setText("Export")
        self.progress_panel.bar.setRange(0, 0)
        self.progress_panel.message_label.setText(f"{event.completed}/{event.total} files prepared. {event.message}")
        self.progress_panel.details.appendPlainText(event.message)

    def _export_completed(self, result):
        self.progress_panel.finish(f"Exported {len(result.files)} file(s) in {result.elapsed_seconds:.1f}s.", True)
        for item in result.files:
            self.progress_panel.details.appendPlainText(str(item.path))

    def closeEvent(self, event):
        if self.thread is not None:
            self._friendly_error("A job is still running. Cancel and wait for it to finish before closing.")
            event.ignore()
        else:
            event.accept()


def open_folder(path: Path) -> None:
    path = Path(path)
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])

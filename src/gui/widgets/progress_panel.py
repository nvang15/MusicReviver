"""Processing progress and technical detail display."""

from PySide6.QtWidgets import (QGroupBox, QLabel, QPlainTextEdit, QProgressBar,
                               QVBoxLayout)

from src.pipeline.models import PipelineStatus
from src.pipeline.progress import PipelineProgress


class ProgressPanel(QGroupBox):
    def __init__(self) -> None:
        super().__init__("Progress")
        self.stage_label = QLabel("Ready")
        self.message_label = QLabel("Choose a recording and task to begin.")
        self.elapsed_label = QLabel("Elapsed: 0.0s")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(115)
        self.details.setPlaceholderText("Technical stage messages appear here.")
        layout = QVBoxLayout(self)
        for widget in (self.stage_label, self.bar, self.message_label, self.elapsed_label, self.details):
            layout.addWidget(widget)

    def begin(self) -> None:
        self.stage_label.setText("Starting")
        self.message_label.setText("Preparing processing job…")
        self.bar.setRange(0, 0)
        self.details.clear()

    def apply_event(self, event: PipelineProgress) -> None:
        self.stage_label.setText(event.stage.value.title())
        self.message_label.setText(event.message)
        self.elapsed_label.setText(f"Elapsed: {event.elapsed_seconds:.1f}s")
        if event.progress_fraction is None and event.status is PipelineStatus.RUNNING:
            self.bar.setRange(0, 0)
        elif event.progress_fraction is not None:
            self.bar.setRange(0, 100)
            self.bar.setValue(round(event.progress_fraction * 100))
        self.details.appendPlainText(f"[{event.stage.value}] {event.status.value}: {event.message}")

    def finish(self, message: str, success: bool) -> None:
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if success else 0)
        self.stage_label.setText("Complete" if success else "Stopped")
        self.message_label.setText(message)


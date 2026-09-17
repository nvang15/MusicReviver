"""Dynamic output presentation and actions."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QPushButton, QVBoxLayout)

from src.gui.models import GuiResult


class OutputPanel(QGroupBox):
    open_folder_requested = Signal()
    export_requested = Signal()

    def __init__(self) -> None:
        super().__init__("Results")
        self.status_label = QLabel("No processing result yet.")
        self.primary_label = QLabel("")
        self.primary_label.setTextInteractionFlags(self.primary_label.textInteractionFlags())
        self.files_list = QListWidget()
        self.open_button = QPushButton("Open Output Folder")
        self.export_button = QPushButton("Export Result…")
        self.open_button.setEnabled(False)
        self.export_button.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.primary_label)
        layout.addWidget(self.files_list)
        layout.addLayout(buttons)
        self.open_button.clicked.connect(self.open_folder_requested)
        self.export_button.clicked.connect(self.export_requested)

    def set_result(self, result: GuiResult) -> None:
        self.status_label.setText(f"{result.summary} Project: {result.project_name}. Elapsed: {result.elapsed_seconds:.2f}s")
        self.primary_label.setText(f"Final: {result.primary_output}" if result.primary_output else "Generated files:")
        self.files_list.clear()
        for path in result.files:
            self.files_list.addItem(str(path))
        self.open_button.setEnabled(result.output_folder is not None)
        self.export_button.setEnabled(bool(result.files))


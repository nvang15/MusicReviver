"""Input media picker with drag-and-drop support."""

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QWidget

from src.audio.metadata import SUPPORTED_EXTENSIONS


class FilePicker(QWidget):
    path_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Choose an audio or video file…")
        self.path_edit.setAccessibleName("Input file path")
        self.browse_button = QPushButton("Browse…")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.path_edit, 1)
        layout.addWidget(self.browse_button)
        self.path_edit.textChanged.connect(self.path_changed)
        self.browse_button.clicked.connect(self.browse)

    @property
    def path(self) -> Path:
        return Path(self.path_edit.text().strip())

    def set_path(self, path: Path | str) -> None:
        self.path_edit.setText(str(path))

    def browse(self) -> None:
        patterns = " ".join(f"*{extension}" for extension in sorted(SUPPORTED_EXTENSIONS))
        filename, _ = QFileDialog.getOpenFileName(self, "Choose recording", "", f"Media files ({patterns});;All files (*)")
        if filename:
            self.set_path(filename)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.path_edit.setEnabled(enabled)
        self.browse_button.setEnabled(enabled)

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if len(urls) == 1 and Path(urls[0].toLocalFile()).suffix.lower() in SUPPORTED_EXTENSIONS:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.set_path(event.mimeData().urls()[0].toLocalFile())
        event.acceptProposedAction()

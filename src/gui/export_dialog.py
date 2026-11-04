"""Small export selection dialog; all conversion runs in the worker."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QListWidget, QListWidgetItem, QDialogButtonBox, QMessageBox)
from src.exporting import AudioFormat, ExportConfig
from src.gui.models import GuiTask


class ExportDialog(QDialog):
    def __init__(self, result, destination="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Result")
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        self.destination = QLineEdit(destination)
        browse = QPushButton("Choose Folder…")
        row = QHBoxLayout()
        row.addWidget(self.destination)
        row.addWidget(browse)
        layout.addWidget(QLabel("Destination folder"))
        layout.addLayout(row)
        browse.clicked.connect(self.browse)
        self.files = QListWidget()
        for path in dict.fromkeys(result.files):
            item = QListWidgetItem(f"{path.parent.name} / {path.name}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(str(path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            selected = result.task is not GuiTask.MODERNIZE or path == result.primary_output
            item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
            self.files.addItem(item)
        layout.addWidget(self.files)
        all_button = QPushButton("Select All")
        none_button = QPushButton("Clear Selection")
        selection = QHBoxLayout()
        selection.addWidget(all_button)
        selection.addWidget(none_button)
        layout.addLayout(selection)
        all_button.clicked.connect(lambda: self.select_all(True))
        none_button.clicked.connect(lambda: self.select_all(False))
        self.format_label = QLabel("Audio format (encoder availability checked before exporting)")
        self.format = QComboBox()
        for kind in AudioFormat:
            self.format.addItem(kind.value.upper(), kind)
        self.quality_label = QLabel("Bitrate (kbps)")
        self.quality = QComboBox()
        for rate in (192, 256, 320):
            self.quality.addItem(str(rate), rate)
        self.quality.setCurrentIndex(2)
        for widget in (self.format_label, self.format, self.quality_label, self.quality):
            layout.addWidget(widget)
        self.files.itemChanged.connect(self.update_controls)
        self.format.currentIndexChanged.connect(self.update_controls)
        layout.addWidget(QLabel("Existing files receive unique names. Cancellation occurs between files."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_controls()

    def browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Export destination", self.destination.text())
        if folder:
            self.destination.setText(folder)

    def select_all(self, selected):
        for index in range(self.files.count()):
            self.files.item(index).setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def selected_files(self):
        return tuple(self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())
                     if self.files.item(i).checkState() == Qt.CheckState.Checked)

    def update_controls(self):
        audio = any(path.suffix.lower() not in {".json", ".txt"} for path in self.selected_files())
        self.format_label.setVisible(audio)
        self.format.setVisible(audio)
        lossy = audio and self.format.currentData() in (AudioFormat.MP3, AudioFormat.M4A)
        self.quality_label.setVisible(lossy)
        self.quality.setVisible(lossy)

    def config(self):
        return ExportConfig(Path(self.destination.text()), self.format.currentData(), self.quality.currentData())

    def accept(self):
        if not self.destination.text().strip() or not self.selected_files():
            QMessageBox.warning(self, "Export Result", "Choose a destination and at least one file.")
            return
        super().accept()

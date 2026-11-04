"""Application creation and packaging-friendly GUI entry point."""

from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from src.gui.main_window import MainWindow
from src.runtime import configure_bundled_tools_path, ensure_runtime_directories


DARK_STYLESHEET = """
QWidget {
    color: #f1f3f5;
    background-color: #1e1f22;
    selection-background-color: #550816;
    selection-color: #ffffff;
}
QLabel { color: #e4e7eb; }
QLabel#title {
    color: #c23b55;
    font-size: 26px;
    font-weight: 700;
}
QGroupBox {
    color: #f1f3f5;
    background-color: #2a2d31;
    border: 1px solid #4b525c;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #f1f3f5;
    background-color: #2a2d31;
}
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit, QListWidget {
    color: #f1f3f5;
    background-color: #25282c;
    border: 1px solid #4b525c;
    border-radius: 4px;
    padding: 5px 7px;
    selection-background-color: #550816;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus,
QTextEdit:focus, QListWidget:focus {
    border-color: #8f2337;
}
QComboBox::drop-down {
    border-left: 1px solid #4b525c;
    width: 24px;
}
QComboBox QAbstractItemView {
    color: #f1f3f5;
    background-color: #25282c;
    border: 1px solid #59616c;
    selection-background-color: #550816;
}
QPushButton {
    color: #f1f3f5;
    background-color: #3a3f45;
    border: 1px solid #59616c;
    border-radius: 5px;
    min-height: 28px;
    padding: 3px 13px;
}
QPushButton:hover { background-color: #474d55; border-color: #747d89; }
QPushButton:pressed { background-color: #30343a; }
QPushButton:default {
    color: #ffffff;
    background-color: #550816;
    border-color: #8f2337;
    font-weight: 600;
}
QPushButton:default:hover { background-color: #701126; }
QPushButton:checked { background-color: #550816; border-color: #b3364e; font-weight: 600; }
QPushButton:checked:hover { background-color: #701126; }
QPushButton:disabled {
    color: #9299a3;
    background-color: #303339;
    border-color: #454a52;
}
QRadioButton { color: #e4e7eb; spacing: 7px; }
QRadioButton::indicator { width: 15px; height: 15px; }
QRadioButton::indicator:checked {
    background-color: #8f2337;
    border: 3px solid #34383e;
    border-radius: 7px;
}
QRadioButton::indicator:unchecked {
    background-color: #25282c;
    border: 1px solid #747d89;
    border-radius: 7px;
}
QProgressBar {
    color: #f1f3f5;
    background-color: #25282c;
    border: 1px solid #4b525c;
    border-radius: 4px;
    min-height: 18px;
    text-align: center;
}
QProgressBar::chunk { background-color: #8f2337; border-radius: 3px; }
QToolTip {
    color: #f1f3f5;
    background-color: #34383e;
    border: 1px solid #59616c;
}
"""


def apply_dark_theme(application: QApplication) -> None:
    """Apply one maintainable high-contrast theme across all GUI widgets."""
    application.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1e1f22"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f1f3f5"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#25282c"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2a2d31"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f1f3f5"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#3a3f45"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f1f3f5"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#550816"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#9299a3"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#9299a3"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#9299a3"))
    application.setPalette(palette)
    application.setStyleSheet(DARK_STYLESHEET)


def create_application(argv: list[str] | None = None) -> QApplication:
    ensure_runtime_directories()
    configure_bundled_tools_path()
    application = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    application.setApplicationName("MusicReviver")
    application.setOrganizationName("MusicReviver")
    apply_dark_theme(application)
    return application


def main(argv: list[str] | None = None) -> int:
    application = create_application(argv)
    window = MainWindow()
    window.show()
    return application.exec()

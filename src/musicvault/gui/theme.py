"""Application-wide Qt styling.

Dark is the default (``AppConfig.theme``). Light is a thin inverse so
Settings can toggle without a second hand-authored palette.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

_DARK_QSS = """
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #1e1e1e;
}
QListWidget {
    background-color: #252526;
    border: none;
    outline: none;
    padding: 4px;
}
QListWidget::item {
    padding: 8px 12px;
    border-radius: 4px;
}
QListWidget::item:selected {
    background-color: #0e639c;
    color: #ffffff;
}
QListWidget::item:hover:!selected {
    background-color: #2a2d2e;
}
QTableWidget, QTreeWidget, QTextEdit, QPlainTextEdit, QLineEdit, QSpinBox,
QDoubleSpinBox, QComboBox {
    background-color: #2d2d2d;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 4px;
    selection-background-color: #0e639c;
}
QHeaderView::section {
    background-color: #2d2d2d;
    color: #cccccc;
    border: none;
    border-bottom: 1px solid #3c3c3c;
    padding: 6px;
}
QPushButton {
    background-color: #0e639c;
    color: #ffffff;
    border: none;
    border-radius: 3px;
    padding: 6px 14px;
}
QPushButton:hover {
    background-color: #1177bb;
}
QPushButton:disabled {
    background-color: #3c3c3c;
    color: #888888;
}
QPushButton[secondary="true"] {
    background-color: #3c3c3c;
}
QPushButton[secondary="true"]:hover {
    background-color: #4a4a4a;
}
QGroupBox {
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QStatusBar {
    background-color: #007acc;
    color: #ffffff;
}
QTabWidget::pane {
    border: 1px solid #3c3c3c;
}
QTabBar::tab {
    background-color: #2d2d2d;
    padding: 6px 12px;
    border: 1px solid #3c3c3c;
    border-bottom: none;
}
QTabBar::tab:selected {
    background-color: #1e1e1e;
}
QLabel[heading="true"] {
    font-size: 18px;
    font-weight: 600;
    padding-bottom: 4px;
}
QScrollBar:vertical {
    background: #1e1e1e;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #5a5a5a;
    border-radius: 4px;
    min-height: 24px;
}
"""

_LIGHT_QSS = """
QWidget {
    background-color: #f5f5f5;
    color: #1e1e1e;
    font-size: 13px;
}
QListWidget {
    background-color: #e8e8e8;
    border: none;
}
QListWidget::item:selected {
    background-color: #0078d4;
    color: #ffffff;
}
QPushButton {
    background-color: #0078d4;
    color: #ffffff;
    border: none;
    border-radius: 3px;
    padding: 6px 14px;
}
QStatusBar {
    background-color: #0078d4;
    color: #ffffff;
}
QLabel[heading="true"] {
    font-size: 18px;
    font-weight: 600;
}
"""


def apply_theme(app: QApplication, theme: str = "dark") -> None:
    """Apply the named theme stylesheet to ``app``."""
    app.setStyleSheet(_LIGHT_QSS if theme == "light" else _DARK_QSS)

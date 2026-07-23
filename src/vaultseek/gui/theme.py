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
QTreeWidget#navSidebar {
    background-color: #252526;
    border: none;
    outline: none;
    padding: 4px;
    show-decoration-selected: 1;
}
QTreeWidget#navSidebar::item {
    padding: 6px 8px;
    border-radius: 4px;
    color: #cccccc;
}
QTreeWidget#navSidebar::item:selected {
    background-color: #0e639c;
    color: #ffffff;
}
QTreeWidget#navSidebar::item:hover:!selected {
    background-color: #2a2d2e;
}
QTreeWidget#navSidebar::branch {
    background: transparent;
}
QTableWidget, QTreeWidget, QTextEdit, QPlainTextEdit, QLineEdit, QComboBox {
    background-color: #2d2d2d;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 4px;
    selection-background-color: #1177bb;
    selection-color: #ffffff;
}
QSpinBox, QDoubleSpinBox {
    background-color: #2d2d2d;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 2px 20px 2px 6px;
    selection-background-color: #1177bb;
    selection-color: #ffffff;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid #3c3c3c;
    border-bottom: 1px solid #3c3c3c;
    background-color: #3c3c3c;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border-left: 1px solid #3c3c3c;
    background-color: #3c3c3c;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #4a4a4a;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    width: 8px;
    height: 8px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    width: 8px;
    height: 8px;
}
QTableWidget::item:selected, QTreeWidget::item:selected {
    background-color: #1177bb;
    color: #ffffff;
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
QLabel[muted="true"] {
    color: #9a9a9a;
}
QLabel[kpiValue="true"] {
    font-size: 28px;
    font-weight: 700;
}
QLabel[panelTitle="true"] {
    font-size: 14px;
    font-weight: 600;
}
QLabel[insight="true"] {
    background-color: #252526;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 10px 12px;
}
QLabel[stageTitle="true"] {
    font-size: 11px;
    font-weight: 600;
}
QLabel[stageCount="true"] {
    font-size: 20px;
    font-weight: 700;
}
QFrame[kpiCard="true"] {
    background-color: #252526;
    border: 1px solid #3c3c3c;
    border-radius: 6px;
    min-width: 110px;
}
QFrame[dashPanel="true"] {
    background-color: #252526;
    border: 1px solid #3c3c3c;
    border-radius: 6px;
    padding: 4px;
}
QFrame[pipelineStage="true"] {
    background-color: #2d2d2d;
    border: 1px solid #3c3c3c;
    border-radius: 6px;
    min-width: 72px;
}
QFrame[pipelineStage="true"][activeStage="true"] {
    border: 1px solid #0e639c;
}
QFrame[pipelineStage="true"][bottleneck="true"] {
    border: 1px solid #d7ba7d;
    background-color: #3a3420;
}
QProgressBar {
    background-color: #1e1e1e;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    height: 8px;
    max-height: 10px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #0e639c;
    border-radius: 2px;
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
QTreeWidget#navSidebar {
    background-color: #e8e8e8;
    border: none;
    outline: none;
    padding: 4px;
}
QTreeWidget#navSidebar::item {
    padding: 6px 8px;
    border-radius: 4px;
}
QTreeWidget#navSidebar::item:selected {
    background-color: #0078d4;
    color: #ffffff;
}
QTreeWidget#navSidebar::item:hover:!selected {
    background-color: #dddddd;
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
QLabel[muted="true"] {
    color: #666666;
}
QLabel[kpiValue="true"] {
    font-size: 28px;
    font-weight: 700;
}
QFrame[kpiCard="true"], QFrame[dashPanel="true"] {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 6px;
}
QFrame[pipelineStage="true"][bottleneck="true"] {
    border: 1px solid #b8952e;
    background-color: #fff8e4;
}
QProgressBar::chunk {
    background-color: #0078d4;
}
"""


def apply_theme(app: QApplication, theme: str = "dark") -> None:
    """Apply the named theme stylesheet to ``app``."""
    app.setStyleSheet(_LIGHT_QSS if theme == "light" else _DARK_QSS)

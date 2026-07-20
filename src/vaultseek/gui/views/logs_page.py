"""Logs page — open rotating log files and the crash folder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.widgets.desktop import open_path


class LogsPage(QWidget):
    """Quick access to on-disk logs (full in-app viewer is deferred)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        paths = container.paths

        layout = QVBoxLayout(self)
        heading = QLabel("Logs")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        body = QLabel(
            "A full log viewer is coming later. Use the buttons below to open "
            "the log folder or the latest log files in your default editor."
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        self._path_label = QLabel(str(paths.logs_dir))
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._path_label)

        buttons = QHBoxLayout()
        open_folder = QPushButton("Open log folder")
        open_app = QPushButton("Open vaultseek.log")
        open_debug = QPushButton("Open debug.log")
        open_crashes = QPushButton("Open crashes folder")
        for btn in (open_app, open_debug, open_crashes):
            btn.setProperty("secondary", True)
        open_folder.clicked.connect(lambda: open_path(paths.logs_dir))
        open_app.clicked.connect(lambda: self._open_file(paths.logs_dir / "vaultseek.log"))
        open_debug.clicked.connect(lambda: self._open_file(paths.logs_dir / "debug.log"))
        open_crashes.clicked.connect(lambda: open_path(paths.crashes_dir))
        buttons.addWidget(open_folder)
        buttons.addWidget(open_app)
        buttons.addWidget(open_debug)
        buttons.addWidget(open_crashes)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def _open_file(self, path: Path) -> None:
        if path.is_file():
            open_path(path)
        else:
            open_path(self._container.paths.logs_dir)

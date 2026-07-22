"""Logs page — preview recent vaultseek.log lines and open log files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.widgets.desktop import open_path

_MAX_LINES = 1000


class LogsPage(QWidget):
    """Show a summarized tail of vaultseek.log plus shortcuts to open log files."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        paths = container.paths

        layout = QVBoxLayout(self)
        heading = QLabel("Logs")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        body = QLabel(
            f"Last {_MAX_LINES} lines of vaultseek.log (noisy debug detail trimmed). "
            "Use the buttons to open full files."
        )
        body.setWordWrap(True)
        body.setProperty("muted", True)
        layout.addWidget(body)

        self._path_label = QLabel(str(paths.logs_dir / "vaultseek.log"))
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._path_label)

        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        open_folder = QPushButton("Open log folder")
        open_app = QPushButton("Open vaultseek.log")
        open_debug = QPushButton("Open debug.log")
        open_crashes = QPushButton("Open crashes folder")
        for btn in (open_folder, open_app, open_debug, open_crashes):
            btn.setProperty("secondary", True)
        refresh.clicked.connect(self.refresh)
        open_folder.clicked.connect(lambda: open_path(paths.logs_dir))
        open_app.clicked.connect(lambda: self._open_file(paths.logs_dir / "vaultseek.log"))
        open_debug.clicked.connect(lambda: self._open_file(paths.logs_dir / "debug.log"))
        open_crashes.clicked.connect(lambda: open_path(paths.crashes_dir))
        buttons.addWidget(refresh)
        buttons.addWidget(open_folder)
        buttons.addWidget(open_app)
        buttons.addWidget(open_debug)
        buttons.addWidget(open_crashes)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._preview.setPlaceholderText("Log preview appears here…")
        layout.addWidget(self._preview, stretch=1)

        self.refresh()

    def refresh(self) -> None:
        path = self._container.paths.logs_dir / "vaultseek.log"
        self._path_label.setText(str(path))
        if not path.is_file():
            self._preview.setPlainText("(vaultseek.log not found yet)")
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._preview.setPlainText(f"(could not read log: {exc})")
            return
        lines = text.splitlines()
        tail = lines[-_MAX_LINES:] if len(lines) > _MAX_LINES else lines
        summarized = [_summarize_line(line) for line in tail]
        # Drop empty consecutive blanks after summarizing.
        cleaned: list[str] = []
        for line in summarized:
            if not line and cleaned and not cleaned[-1]:
                continue
            cleaned.append(line)
        header = f"— last {len(tail)} of {len(lines)} lines —\n"
        self._preview.setPlainText(header + "\n".join(cleaned))
        cursor = self._preview.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._preview.setTextCursor(cursor)

    def _open_file(self, path: Path) -> None:
        if path.is_file():
            open_path(path)
        else:
            open_path(self._container.paths.logs_dir)


def _summarize_line(line: str) -> str:
    """Keep level + message; trim very long payloads."""
    text = line.rstrip()
    if len(text) > 400:
        text = text[:397] + "…"
    # Collapse repeated whitespace inside the message body.
    return " ".join(text.split())

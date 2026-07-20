"""Reusable path field with Browse / Open actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

from vaultseek.gui.widgets.desktop import open_path


class _DropLineEdit(QLineEdit):
    """Line edit that accepts a dropped local file/folder path."""

    path_dropped = Signal(str)

    def __init__(self, *, expect_directory: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._expect_directory = expect_directory
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        local = urls[0].toLocalFile()
        if not local:
            event.ignore()
            return
        path = Path(local)
        if self._expect_directory:
            if path.is_file():
                path = path.parent
            if not path.is_dir():
                event.ignore()
                return
        elif not path.is_file():
            event.ignore()
            return
        self.path_dropped.emit(str(path))
        event.acceptProposedAction()


class PathPickerRow(QWidget):
    """``QLineEdit`` plus Browse (and optional Open) for folders or files.

    Accepts drag-and-drop of a folder (or file when ``mode="file"``).
    """

    path_changed = Signal(str)

    def __init__(
        self,
        *,
        mode: str = "directory",
        placeholder: str = "",
        file_filter: str = "All files (*.*)",
        show_open: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if mode not in {"directory", "file"}:
            raise ValueError(f"Unsupported mode: {mode}")
        self._mode = mode
        self._file_filter = file_filter

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._edit = _DropLineEdit(expect_directory=(mode == "directory"))
        self._edit.setPlaceholderText(placeholder)
        self._edit.textChanged.connect(self.path_changed.emit)
        self._edit.path_dropped.connect(self._edit.setText)
        row.addWidget(self._edit, stretch=1)

        browse = QPushButton("Browse…")
        browse.setProperty("secondary", True)
        browse.setToolTip("Choose a folder" if mode == "directory" else "Choose a file")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)

        if show_open:
            open_btn = QPushButton("Open")
            open_btn.setProperty("secondary", True)
            open_btn.setToolTip("Open this path in the file manager")
            open_btn.clicked.connect(self._open)
            row.addWidget(open_btn)

    def text(self) -> str:
        return self._edit.text().strip()

    def setText(self, value: str) -> None:  # noqa: N802 — Qt naming
        self._edit.setText(value)

    def clear(self) -> None:
        self._edit.clear()

    def line_edit(self) -> QLineEdit:
        return self._edit

    def setToolTip(self, tip: str) -> None:  # noqa: N802
        super().setToolTip(tip)
        self._edit.setToolTip(tip)

    def _browse(self) -> None:
        start = self.text() or str(Path.home())
        if self._mode == "directory":
            chosen = QFileDialog.getExistingDirectory(
                self,
                "Select folder",
                start,
                QFileDialog.Option.ShowDirsOnly,
            )
        else:
            chosen, _ = QFileDialog.getOpenFileName(
                self,
                "Select file",
                start,
                self._file_filter,
            )
        if chosen:
            self._edit.setText(str(Path(chosen)))

    def _open(self) -> None:
        path = self.text()
        if path:
            open_path(path)

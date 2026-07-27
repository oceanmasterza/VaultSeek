"""In-app user help — locate bundled HELP.html and show it in a dialog."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

_HELP_RELATIVE = Path("help") / "HELP.html"


def help_html_path() -> Path | None:
    """Return the user help file, or None if it is missing from this install."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                exe_dir / _HELP_RELATIVE,
                exe_dir / "_internal" / _HELP_RELATIVE,
            ]
        )
    else:
        repo_root = Path(__file__).resolve().parents[3]
        candidates.extend(
            [
                repo_root / "docs" / "HELP.html",
                repo_root / _HELP_RELATIVE,
            ]
        )
    for path in candidates:
        if path.is_file():
            return path
    return None


def open_help_in_browser(parent: object | None = None) -> bool:
    """Open HELP.html in the default browser. Returns False if not found."""
    path = help_html_path()
    if path is None:
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))


class HelpDialog(QDialog):
    """Scrollable in-app help viewer (same HTML as the bundled file)."""

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("VaultSeek Help")
        self.resize(920, 720)
        self.setMinimumSize(640, 480)

        layout = QVBoxLayout(self)
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        layout.addWidget(self._browser, stretch=1)

        buttons = QHBoxLayout()
        open_ext = QPushButton("Open in browser")
        open_ext.setProperty("secondary", True)
        open_ext.clicked.connect(lambda: open_help_in_browser(self))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(open_ext)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        path = help_html_path()
        if path is None:
            self._browser.setHtml(
                "<h2>Help file not found</h2>"
                "<p>The bundled <code>HELP.html</code> is missing from this install. "
                "See the online documentation at "
                '<a href="https://github.com/oceanmasterza/VaultSeek">GitHub</a>.</p>'
            )
        else:
            self._browser.setSource(QUrl.fromLocalFile(str(path.resolve())))

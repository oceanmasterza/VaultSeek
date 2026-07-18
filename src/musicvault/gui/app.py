"""Qt application entry — create QApplication and run the main window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from musicvault.core.container import Container
from musicvault.gui.main_window import MainWindow
from musicvault.gui.theme import apply_theme


def run_gui(container: Container) -> int:
    """Show the MusicVault main window and run the Qt event loop.

    Owns the process lifetime for the GUI path: closes ``container`` when
    the window exits. Always runs ``QApplication.exec()`` so an already-
    existing application instance (tests) does not dispose the container
    while the window is still live. Returns a process exit code.
    """
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv)

    apply_theme(app, container.config.theme)
    window = MainWindow(container)
    window.show()

    try:
        return int(app.exec())
    finally:
        container.close()

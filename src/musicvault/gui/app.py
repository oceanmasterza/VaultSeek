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
    the window exits (or if startup fails after the container was passed
    in). Returns a process exit code.
    """
    existing = QApplication.instance()
    created_app = False
    if isinstance(existing, QApplication):
        app = existing
    else:
        app = QApplication(sys.argv)
        created_app = True

    apply_theme(app, container.config.theme)
    window = MainWindow(container)
    window.show()

    try:
        code = app.exec() if created_app else 0
    finally:
        container.close()
    return int(code)

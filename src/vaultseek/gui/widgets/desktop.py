"""Open paths in the OS file manager and related desktop helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_path(path: str | Path) -> bool:
    """Reveal ``path`` in the system file manager (creates dirs if missing).

    Returns True if the OS accepted the open request.
    """
    target = Path(path).expanduser()
    if not target.exists():
        try:
            if target.suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
                target = target.parent if target.parent.exists() else target
            else:
                target.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve())))


def reveal_in_explorer(path: str | Path) -> bool:
    """Select ``path`` in Explorer/Finder when possible; else open the parent."""
    target = Path(path).expanduser()
    if not target.exists():
        parent = target.parent
        return open_path(parent) if parent.exists() else False

    resolved = target.resolve()
    if sys.platform == "win32":
        # explorer /select,path — keeps the file highlighted
        subprocess.Popen(["explorer", f"/select,{resolved}"], shell=False)
        return True
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(resolved)])
        return True
    return open_path(resolved if resolved.is_dir() else resolved.parent)


def copy_text_to_clipboard(text: str) -> None:
    from PySide6.QtWidgets import QApplication

    clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(text)

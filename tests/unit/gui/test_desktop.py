"""Tests for GUI path helpers (no QApplication required)."""

from __future__ import annotations

from pathlib import Path

from vaultseek.gui.widgets.desktop import open_path


def test_open_path_creates_missing_directory(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "logs" / "nested"
    opened: list[str] = []

    monkeypatch.setattr(
        "vaultseek.gui.widgets.desktop.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    assert open_path(target) is True
    assert target.is_dir()
    assert opened and Path(opened[0]) == target.resolve()

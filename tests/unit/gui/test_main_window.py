"""GUI smoke tests (pytest-qt)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from vaultseek.core.container import Container
from vaultseek.db.uuid_utils import uuid7
from vaultseek.gui.bridge.qt_event_bridge import QtEventBridge
from vaultseek.gui.main_window import MainWindow
from vaultseek.gui.theme import apply_theme
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.review_item import ReviewType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.dto.review_dto import ReviewItemCreate

pytest.importorskip("pytestqt")


@pytest.fixture
def gui_library(container: Container, tmp_path: Path) -> Library:
    now = datetime.now(UTC)
    library = Library(
        id=uuid7(),
        name="Test Lib",
        incoming_path=str(tmp_path / "incoming"),
        staging_path=str(tmp_path / "staging"),
        library_path=str(tmp_path / "library"),
        archive_path=str(tmp_path / "archive"),
        created_at=now,
        updated_at=now,
    )
    for path in (
        library.incoming_path,
        library.staging_path,
        library.library_path,
        library.archive_path,
    ):
        Path(path).mkdir(parents=True, exist_ok=True)
    container.library_repo.upsert(library)
    return library


def test_main_window_opens(qtbot, container: Container, gui_library: Library) -> None:
    window = MainWindow(container)
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle() == "VaultSeek"
    assert window._library_combo.count() == 1  # noqa: SLF001
    assert window._library_combo.currentData() == gui_library.id  # noqa: SLF001


def test_review_badge_updates_via_bridge(qtbot, container: Container, gui_library: Library) -> None:
    window = MainWindow(container)
    qtbot.addWidget(window)
    assert isinstance(window._bridge, QtEventBridge)  # noqa: SLF001

    now = datetime.now(UTC)
    audio = Path(gui_library.incoming_path) / "06 - Point Of Know Return.mp3"
    audio.write_bytes(b"not-audio")
    track_id = uuid7()
    container.track_repo.upsert(
        Track(
            id=track_id,
            library_id=gui_library.id,
            zone=LibraryZone.INCOMING,
            file_path=str(audio),
            file_name=audio.name,
            file_size=audio.stat().st_size,
            file_modified=now,
            created_at=now,
            updated_at=now,
            title="01a090ad",
        )
    )
    container.review_queue.create_item(
        ReviewItemCreate(
            library_id=gui_library.id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="01a090ad",
            track_id=track_id,
            description="test",
            confidence=0.5,
        )
    )
    qtbot.waitUntil(lambda: len(window._review_page._rows) >= 1, timeout=2000)  # noqa: SLF001
    labels = [row.label for row in window._review_page._rows.values()]  # noqa: SLF001
    assert "Point Of Know Return" in labels


def test_apply_theme_dark(qapp) -> None:
    apply_theme(qapp, "dark")
    assert "1e1e1e" in qapp.styleSheet()


def test_headless_flag_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    from vaultseek.__main__ import _wants_headless

    monkeypatch.delenv("VAULTSEEK_HEADLESS", raising=False)
    assert _wants_headless(["--headless"])
    assert not _wants_headless([])
    monkeypatch.setenv("VAULTSEEK_HEADLESS", "1")
    assert _wants_headless([])

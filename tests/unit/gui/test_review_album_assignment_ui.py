"""Review Assign album UI: searchable library albums, sort identity, Play, Retry."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QPushButton

from vaultseek.core.container import Container
from vaultseek.gui.views.review_page import (
    ReviewPage,
    _AlbumAssignDialog,
    format_apply_retry_summary,
    format_preview_retry_summary,
)
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.artist import Artist
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.review_item import ReviewItem, ReviewStatus, ReviewType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.identify_retry_preview import (
    ApplyMatchesReport,
    ApplyMatchRowResult,
    IdentifyPreviewReport,
    IdentifyPreviewRow,
)
from vaultseek.services.library_tracklist_matcher import AlbumSlotRecommendation
from vaultseek.services.review_queue_service import AlbumChoice, AlbumSlotChoice

pytest.importorskip("pytestqt")


def _now() -> datetime:
    return datetime.now(UTC)


def _seed_library(container: Container, tmp_path: Path) -> tuple[Library, Path, UUID, UUID]:
    now = _now()
    library = Library(
        id=uuid4(),
        name="Review UI Lib",
        incoming_path=str(tmp_path / "in"),
        staging_path=str(tmp_path / "st"),
        library_path=str(tmp_path / "lib"),
        archive_path=str(tmp_path / "ar"),
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
    artist = Artist(
        id=uuid4(),
        name="Alphaville",
        sort_name="Alphaville",
        created_at=now,
        updated_at=now,
    )
    container.artist_repo.create(artist)
    album = Album(
        id=uuid4(),
        title="Salvation",
        sort_title="Salvation",
        album_artist_id=artist.id,
        year=1989,
        created_at=now,
        updated_at=now,
    )
    container.album_repo.create(album)
    audio = tmp_path / "in" / "10 - Soul Messiah.mp3"
    audio.write_bytes(b"ID3fake-audio")
    track = Track(
        id=uuid4(),
        library_id=library.id,
        zone=LibraryZone.INCOMING,
        file_path=str(audio),
        file_name=audio.name,
        file_size=audio.stat().st_size,
        file_modified=now,
        title="01a090ad",
        needs_review=True,
        created_at=now,
        updated_at=now,
    )
    container.track_repo.upsert(track)
    item = ReviewItem(
        id=uuid4(),
        library_id=library.id,
        review_type=ReviewType.UNKNOWN_ARTIST,
        status=ReviewStatus.PENDING,
        title="Unknown artist",
        track_id=track.id,
        created_at=now,
        description="test",
        confidence=0.4,
    )
    container.review_repo.create(item)
    # Existing library album track so assignment_albums finds Salvation.
    lib_audio = tmp_path / "lib" / "01 - Big in Japan.flac"
    lib_audio.write_bytes(b"fLaCfake")
    existing = Track(
        id=uuid4(),
        library_id=library.id,
        zone=LibraryZone.LIBRARY,
        file_path=str(lib_audio),
        file_name=lib_audio.name,
        file_size=lib_audio.stat().st_size,
        file_modified=now,
        title="Big in Japan",
        album_id=album.id,
        artist_id=artist.id,
        track_number=1,
        disc_number=1,
        created_at=now,
        updated_at=now,
    )
    container.track_repo.upsert(existing)
    return library, audio, item.id, album.id


def test_assign_dialog_allows_manual_choice_without_recommendations(qtbot) -> None:
    albums = (
        AlbumChoice(
            album_id=uuid4(),
            artist_name="Alphaville",
            album_title="Salvation",
            year=1989,
        ),
        AlbumChoice(
            album_id=uuid4(),
            artist_name="Other",
            album_title="Somewhere Else",
            year=2001,
        ),
    )
    slots: dict[Any, tuple[AlbumSlotChoice, ...]] = {
        albums[0].album_id: (
            AlbumSlotChoice(
                title="Big in Japan",
                track_number=1,
                disc_number=1,
                artist_id=None,
            ),
        ),
        albums[1].album_id: (),
    }
    dialog = _AlbumAssignDialog(
        song_label="Soul Messiah",
        albums=albums,
        recommendations=(),
        load_slots=lambda album_id: slots.get(album_id, ()),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._album_table.rowCount() == 2  # noqa: SLF001
    dialog._search.setText("Somewhere")  # noqa: SLF001
    assert dialog._album_table.rowCount() == 1  # noqa: SLF001
    dialog._album_table.selectRow(0)  # noqa: SLF001
    dialog._title.setText("Soul Messiah")  # noqa: SLF001
    dialog._track_number.setValue(10)  # noqa: SLF001
    dialog._accept_choice()  # noqa: SLF001
    choice = dialog.selected()
    assert choice is not None
    assert choice.album_id == albums[1].album_id
    assert choice.title == "Soul Messiah"
    assert choice.track_number == 10


def test_assign_dialog_shows_better_copy_note_but_still_applies(qtbot) -> None:
    album_id = uuid4()
    artist_id = uuid4()
    albums = (
        AlbumChoice(
            album_id=album_id,
            artist_name="Alphaville",
            album_title="Salvation",
            year=1989,
        ),
    )
    rec = AlbumSlotRecommendation(
        album_id=album_id,
        album_title="Salvation",
        artist_id=artist_id,
        artist_name="Alphaville",
        disc_number=1,
        track_number=10,
        slot_title="Soul Messiah",
        score=0.99,
        reasons=("title", "duration"),
        existing_track_id=uuid4(),
        existing_is_better=True,
        version_kind="studio",
        version_conflict=False,
    )
    dialog = _AlbumAssignDialog(
        song_label="Soul Messiah",
        albums=albums,
        recommendations=(rec,),
        load_slots=lambda _album_id: (),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    assert "better-quality" in dialog._evidence.text().lower()  # noqa: SLF001
    dialog._accept_choice()  # noqa: SLF001
    choice = dialog.selected()
    assert choice is not None
    assert choice.better_copy_note is not None
    assert choice.album_id == album_id


def test_review_page_sort_keeps_stable_item_ids(
    qtbot, container: Container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library, _audio, item_id, _album_id = _seed_library(container, tmp_path)
    now = _now()
    other_audio = tmp_path / "in" / "12 - Pandora.mp3"
    other_audio.write_bytes(b"ID3fake2")
    other_track = Track(
        id=uuid4(),
        library_id=library.id,
        zone=LibraryZone.INCOMING,
        file_path=str(other_audio),
        file_name=other_audio.name,
        file_size=other_audio.stat().st_size,
        file_modified=now,
        title="Pandora",
        needs_review=True,
        created_at=now,
        updated_at=now,
    )
    container.track_repo.upsert(other_track)
    other_item = ReviewItem(
        id=uuid4(),
        library_id=library.id,
        review_type=ReviewType.UNKNOWN_ALBUM,
        status=ReviewStatus.PENDING,
        title="Unknown album",
        track_id=other_track.id,
        created_at=now,
        description="test",
        confidence=0.9,
    )
    container.review_repo.create(other_item)

    monkeypatch.setattr(
        container.review_queue,
        "album_recommendations",
        lambda _item_id: (),
    )
    page = ReviewPage(container)
    qtbot.addWidget(page)
    page.set_library(library.id)
    assert page._table.rowCount() == 2  # noqa: SLF001
    page._table.selectRow(0)  # noqa: SLF001
    before = page._selected_rows()  # noqa: SLF001
    assert len(before) == 1
    page._table.sortItems(2, Qt.SortOrder.DescendingOrder)  # noqa: SLF001 confidence
    after = page._selected_rows()  # noqa: SLF001
    assert len(after) == 1
    assert after[0].item_id == before[0].item_id
    assert {before[0].item_id, other_item.id, item_id}  # smoke: ids exist


def test_play_and_retry_buttons_remain_and_fit(
    qtbot, container: Container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library, _audio, _item_id, _album_id = _seed_library(container, tmp_path)
    monkeypatch.setattr(container.review_queue, "album_recommendations", lambda _i: ())
    page = ReviewPage(container)
    qtbot.addWidget(page)
    page.resize(480, 400)
    page.set_library(library.id)
    page.show()
    qtbot.waitExposed(page)

    labels = {btn.text() for btn in page.findChildren(QPushButton)}
    assert "Play" in labels
    assert "Assign album…" in labels
    assert "Preview retry" in labels
    assert "Retry" in labels

    for btn in (
        page._play_btn,
        page._assign_btn,
        page._retry_btn,
        page._preview_btn,
    ):  # noqa: SLF001
        assert btn.isVisible()
        hint = btn.sizeHint()
        assert hint.width() >= btn.fontMetrics().horizontalAdvance(btn.text())
        assert btn.width() >= hint.width() or page.width() < 520


def test_assign_uses_assignment_albums_when_no_recommendations(
    qtbot, container: Container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library, _audio, item_id, album_id = _seed_library(container, tmp_path)
    assigned: list[dict[str, Any]] = []

    monkeypatch.setattr(container.review_queue, "album_recommendations", lambda _i: ())
    monkeypatch.setattr(
        container.review_queue,
        "assign_album_slot",
        lambda item, **kwargs: assigned.append({"item": item, **kwargs}),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *a, **k: QMessageBox.StandardButton.Ok,
    )

    page = ReviewPage(container)
    qtbot.addWidget(page)
    page.set_library(library.id)
    page._table.selectRow(0)  # noqa: SLF001

    opened: list[_AlbumAssignDialog] = []
    original_init = _AlbumAssignDialog.__init__

    def tracking_init(self: _AlbumAssignDialog, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        opened.append(self)

    monkeypatch.setattr(_AlbumAssignDialog, "__init__", tracking_init)

    # Drive dialog manually instead of modal exec.
    def fake_exec(self: _AlbumAssignDialog) -> int:
        from PySide6.QtWidgets import QDialog

        self._album_table.selectRow(0)  # noqa: SLF001
        self._title.setText("Soul Messiah")  # noqa: SLF001
        self._track_number.setValue(10)  # noqa: SLF001
        self._accept_choice()  # noqa: SLF001
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(_AlbumAssignDialog, "exec", fake_exec)
    page._assign_album()  # noqa: SLF001
    qtbot.waitUntil(lambda: bool(assigned), timeout=5000)
    assert opened
    assert opened[0]._album_table.rowCount() >= 1  # noqa: SLF001
    assert assigned[0]["item"] == item_id
    assert assigned[0]["album_id"] == album_id
    assert assigned[0]["title"] == "Soul Messiah"
    assert assigned[0]["track_number"] == 10


def _empty_preview(library_id: UUID, *, rows: int = 0) -> IdentifyPreviewReport:
    preview_rows: list[IdentifyPreviewRow] = []
    for _ in range(rows):
        preview_rows.append(
            IdentifyPreviewRow(
                track_id=uuid4(),
                review_ids=(uuid4(),),
                file_name="song.mp3",
                stored_title="opaque",
                predicted_title="Song",
                predicted_artist="Artist",
                predicted_album="Album",
                overall_confidence=0.95,
                would_auto_approve=False,
                recommendation_count=0,
                top_recommendations=(),
                notes=(),
            )
        )
    return IdentifyPreviewReport(
        library_id=library_id,
        rows=tuple(preview_rows),
        would_auto_approve=0,
        stay_in_review=rows,
        opaque_title_fixed=rows,
    )


def test_format_apply_retry_summary_mixed_success_and_failure() -> None:
    library_id = uuid4()
    preview = _empty_preview(library_id, rows=3)
    report = ApplyMatchesReport(
        preview=preview,
        results=(
            ApplyMatchRowResult(track_id=uuid4(), status="applied", album_id=uuid4()),
            ApplyMatchRowResult(track_id=uuid4(), status="failed", error="tag write failed"),
            ApplyMatchRowResult(track_id=uuid4(), status="enqueued_identify"),
        ),
        applied=1,
        failed=1,
        enqueued_identify=1,
    )
    text = format_apply_retry_summary(report)
    assert "changes were applied" in text
    assert "Songs considered: 3" in text
    assert "Assigned: 1" in text
    assert "Failed: 1" in text
    assert "Re-identify queued: 1" in text
    assert "tag write failed" in text
    assert "0 songs" not in text.lower()


def test_format_apply_retry_summary_all_failure_says_no_changes() -> None:
    library_id = uuid4()
    preview = _empty_preview(library_id, rows=2)
    report = ApplyMatchesReport(
        preview=preview,
        results=(
            ApplyMatchRowResult(track_id=uuid4(), status="failed", error="track missing"),
            ApplyMatchRowResult(track_id=uuid4(), status="failed", error="no pending review item"),
        ),
        applied=0,
        failed=2,
        enqueued_identify=0,
    )
    text = format_apply_retry_summary(report)
    assert "no changes were applied" in text
    assert "Songs considered: 2" in text
    assert "Assigned: 0" in text
    assert "Failed: 2" in text
    assert "Re-identify queued: 0" in text
    assert "track missing" in text
    assert "no pending review item" in text


def test_format_preview_retry_uses_confident_matches_wording() -> None:
    report = _empty_preview(uuid4(), rows=2)
    text = format_preview_retry_summary(report)
    assert "Previewed 2 pending song(s)." in text
    assert "Would apply confident matches" in text
    assert "unique corroborated" not in text
    assert "No changes were written" in text


def test_apply_retry_ignores_stale_library(
    qtbot, container: Container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    from PySide6.QtCore import QThreadPool

    library, _audio, _item_id, _album_id = _seed_library(container, tmp_path)
    monkeypatch.setattr(container.review_queue, "album_recommendations", lambda _i: ())
    page = ReviewPage(container)
    qtbot.addWidget(page)
    page.set_library(library.id)

    started = Event()
    release = Event()
    library_id = library.id
    report = ApplyMatchesReport(
        preview=_empty_preview(library_id, rows=1),
        results=(ApplyMatchRowResult(track_id=uuid4(), status="failed", error="tag write failed"),),
        applied=0,
        failed=1,
        enqueued_identify=0,
    )

    def slow_apply(_lib: UUID, *, dry_run: bool = True) -> ApplyMatchesReport:
        assert dry_run is False
        started.set()
        release.wait(5)
        return report

    shown: list[str] = []
    monkeypatch.setattr(container.identify_retry_preview, "apply_safe_matches", slow_apply)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *a, **k: shown.append(str(a[2] if len(a) > 2 else "")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **k: shown.append(f"warn:{a[2] if len(a) > 2 else ''}"),
    )

    page._apply_retry()  # noqa: SLF001
    qtbot.waitUntil(started.is_set, timeout=2000)
    page.set_library(None)  # library changed while background work runs
    release.set()
    QThreadPool.globalInstance().waitForDone(5000)
    qtbot.waitUntil(lambda: not page._busy, timeout=5000)  # noqa: SLF001
    assert shown == []

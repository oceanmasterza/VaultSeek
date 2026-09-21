"""Albums and artwork share one page, and cover identity follows the album id."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QTableWidgetItem

from vaultseek.core.container import Container
from vaultseek.gui.main_window import MainWindow, _jump_destinations
from vaultseek.gui.views.albums_page import AlbumsPage
from vaultseek.models.dto.browse_dto import AlbumBrowseRow
from vaultseek.models.entities.acquisition_job import AcquisitionJobType
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.artwork import Artwork
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.track import LibraryZone, Track


def _row(album_id: UUID, title: str, artist: str) -> AlbumBrowseRow:
    return AlbumBrowseRow(
        album_id=album_id,
        title=title,
        sort_title=title,
        artist_name=artist,
        artist_id=None,
        year=1991,
        track_count=1,
        has_cover=True,
    )


def _art(path: Path, *, width: int = 1000, height: int = 1000) -> Artwork:
    return Artwork(
        id=uuid4(),
        content_hash_sha256=path.name,
        source="embedded_art",
        mime_type="image/jpeg",
        width=width,
        height=height,
        file_size=path.stat().st_size,
        file_path=str(path),
        created_at=datetime.now(UTC),
    )


def _track(library_id: UUID) -> Track:
    now = datetime.now(UTC)
    return Track(
        id=uuid4(),
        library_id=library_id,
        zone=LibraryZone.LIBRARY,
        file_path="C:/music/no-limit.mp3",
        file_name="no-limit.mp3",
        file_size=1,
        file_modified=now,
        created_at=now,
        updated_at=now,
        title="No Limit",
    )


def test_sorted_selection_keeps_each_rows_cover(
    qtbot, container: Container, tmp_path: Path
) -> None:
    alpha_id = uuid4()
    zulu_id = uuid4()
    alpha_cover = tmp_path / "alpha.jpg"
    zulu_cover = tmp_path / "zulu.jpg"
    alpha_cover.write_bytes(b"alpha")
    zulu_cover.write_bytes(b"zulu")
    rows = {
        alpha_id: _row(alpha_id, "Alpha", "Alphaville"),
        zulu_id: _row(zulu_id, "Zulu", "2 Unlimited"),
    }
    covers = {
        alpha_id: _art(alpha_cover),
        zulu_id: _art(zulu_cover),
    }
    page = AlbumsPage(container)
    qtbot.addWidget(page)
    page._library_id = uuid4()  # noqa: SLF001
    page._container.album_repo.list_for_library = lambda *args, **kwargs: [  # type: ignore[method-assign]
        rows[zulu_id],
        rows[alpha_id],
    ]
    page._container.album_repo.get = lambda album_id: None  # type: ignore[method-assign]
    page._container.track_repo.list_by_album = lambda *args, **kwargs: []  # type: ignore[method-assign]
    page._container.artwork_repo.get_primary_for_album = (  # type: ignore[method-assign]
        lambda album_id: covers[album_id]
    )
    page.refresh()
    page._table.sortItems(0, Qt.SortOrder.AscendingOrder)  # noqa: SLF001
    page._table.selectRow(0)  # noqa: SLF001
    assert page._selected_album_id() == alpha_id  # noqa: SLF001
    assert page._selected_cover_path() == str(alpha_cover)  # noqa: SLF001
    table = page._table  # noqa: SLF001
    for column in range(table.columnCount()):
        item = table.item(0, column)
        assert item is not None
        assert item.data(Qt.ItemDataRole.UserRole) == str(alpha_id)
        assert item.data(Qt.ItemDataRole.UserRole + 1) == str(alpha_cover)
    page._cover_album_id = zulu_id  # noqa: SLF001
    page._full_cover = QPixmap(4, 4)  # noqa: SLF001
    page.resize(640, 480)
    shown = page._cover_image.pixmap()  # noqa: SLF001
    assert shown is None or shown.isNull()


def test_album_menu_separates_missing_songs_artwork_and_reacquire(
    qtbot, container: Container, monkeypatch
) -> None:
    page = AlbumsPage(container)
    qtbot.addWidget(page)
    library_id = uuid4()
    album_id = uuid4()
    page._library_id = library_id  # noqa: SLF001
    now = datetime.now(UTC)
    album = Album(
        id=album_id,
        title="No Limit - EP",
        sort_title="No Limit - EP",
        created_at=now,
        updated_at=now,
    )
    item = QTableWidgetItem("No Limit - EP")
    item.setData(Qt.ItemDataRole.UserRole, str(album_id))
    page._table.setRowCount(1)  # noqa: SLF001
    page._table.setItem(0, 0, item)  # noqa: SLF001
    page._table.selectRow(0)  # noqa: SLF001
    labels = [action.text() for action in page._build_album_menu().actions()]  # noqa: SLF001
    assert "Find missing songs" in labels
    assert "Find missing artwork" in labels
    assert "Reacquire whole album" in labels
    assert "Queue this album for download" not in labels

    missing: list[object] = []
    created: list[dict[str, object]] = []

    monkeypatch.setattr(
        "vaultseek.gui.views.albums_page.run_missing_scan_for_album",
        lambda _container, _library_id, target: missing.append(target) or 1,
    )

    def immediate(fn, *, on_finished, on_failed=None):  # type: ignore[no-untyped-def]
        del on_failed
        on_finished(fn())

    monkeypatch.setattr("vaultseek.gui.views.albums_page.run_in_background", immediate)
    monkeypatch.setattr(page, "refresh", lambda: None)
    monkeypatch.setattr(page._container.album_repo, "get", lambda _album_id: album)
    monkeypatch.setattr(
        page._container.acquisition_engine,
        "create_job",
        lambda **kwargs: created.append(kwargs) or type("Job", (), {"id": uuid4()})(),
    )
    monkeypatch.setattr(page._container.acquisition_engine, "queue", lambda _job_id: None)
    page._run_album_action("Find missing songs")  # noqa: SLF001
    assert missing == [album_id]
    assert created == []
    page._run_album_action("Reacquire whole album")  # noqa: SLF001
    assert created[0]["job_type"] is AcquisitionJobType.MISSING_ALBUM
    assert missing == [album_id]


def test_find_missing_artwork_does_not_replace_a_cover_file(
    qtbot, container: Container, tmp_path: Path, monkeypatch
) -> None:
    page = AlbumsPage(container)
    qtbot.addWidget(page)
    page._library_id = uuid4()  # noqa: SLF001
    album_id = uuid4()
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    enqueued: list[JobType] = []
    monkeypatch.setattr(
        page._container.artwork_repo,
        "get_primary_for_album",
        lambda _album_id: _art(cover, width=120, height=120),
    )
    monkeypatch.setattr(
        page._container.job_queue,
        "enqueue",
        lambda job_type, *_args, **_kwargs: enqueued.append(job_type) or uuid4(),
    )
    page._find_missing_artwork(album_id)  # noqa: SLF001
    assert enqueued == []
    assert "low-resolution" in page._status.text()  # noqa: SLF001
    assert "Not replacing" in page._status.text()  # noqa: SLF001


def test_find_missing_artwork_enqueues_fetch_when_cover_is_absent(
    qtbot, container: Container, monkeypatch
) -> None:
    page = AlbumsPage(container)
    qtbot.addWidget(page)
    library_id = uuid4()
    album_id = uuid4()
    track = _track(library_id)
    page._library_id = library_id  # noqa: SLF001
    enqueued: list[tuple[JobType, dict[str, object]]] = []
    monkeypatch.setattr(page._container.artwork_repo, "get_primary_for_album", lambda _id: None)
    monkeypatch.setattr(
        page._container.track_repo,
        "list_by_album",
        lambda *_args, **_kwargs: [track],
    )

    def enqueue(job_type, _library_id, payload, **_kwargs):  # type: ignore[no-untyped-def]
        enqueued.append((job_type, payload))
        return uuid4()

    monkeypatch.setattr(page._container.job_queue, "enqueue", enqueue)
    opened: list[str] = []
    page.navigate_requested.connect(opened.append)
    page._find_missing_artwork(album_id)  # noqa: SLF001
    assert enqueued == [(JobType.FETCH_ARTWORK, {"track_id": str(track.id)})]
    assert opened == ["jobs"]


def test_artwork_navigation_alias_opens_albums(qtbot, container: Container) -> None:
    from dataclasses import replace

    container.config = replace(container.config, setup_completed=True)
    window = MainWindow(container)
    qtbot.addWidget(window)
    assert "artwork" not in window._nav_items  # noqa: SLF001
    assert ("Library · Artwork", "artwork") in _jump_destinations()
    window._go_to("artwork")  # noqa: SLF001
    assert window._stack.currentWidget() is window._albums_page  # noqa: SLF001
    assert window._pages["artwork"] is window._albums_page  # noqa: SLF001
    assert window._albums_page._missing_only.isChecked()  # noqa: SLF001
    assert not window._albums_page._missing_only.isHidden()  # noqa: SLF001

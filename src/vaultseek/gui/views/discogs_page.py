"""Discogs catalog browse — search artist discography and queue downloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.async_task import run_in_background
from vaultseek.models.entities.acquisition_job import AcquisitionJobType
from vaultseek.plugins.builtin.discogs.provider import DiscogsProvider
from vaultseek.services.wanted import park_album_job


@dataclass(frozen=True, slots=True)
class _ReleaseRow:
    release_id: int
    title: str
    year: str
    kind: str
    role: str
    format: str
    label: str
    artist: str
    secondary: str
    thumb: str


class DiscogsPage(QWidget):
    """Search Discogs artists and queue selected releases for acquisition."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._artist_id: int | None = None
        self._artist_name: str = ""
        self._rows: list[_ReleaseRow] = []

        layout = QVBoxLayout(self)
        heading = QLabel("Discogs")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        help_lbl = QLabel(
            "Search an artist (e.g. Armin van Buuren), browse albums / singles / "
            "appearances by date, then select rows to queue for download via Acquisition."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addWidget(help_lbl)

        search_row = QHBoxLayout()
        self._query = QLineEdit()
        self._query.setPlaceholderText("Artist name…")
        self._query.returnPressed.connect(self._search_artist)
        search_btn = QPushButton("Search Discogs")
        search_btn.clicked.connect(self._search_artist)
        search_row.addWidget(self._query, stretch=1)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        self._status = QLabel("Enter an artist name and press Search.")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._artists = QTableWidget(0, 2)
        self._artists.setHorizontalHeaderLabels(["Artist", "Discogs ID"])
        self._artists.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._artists.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._artists.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._artists.horizontalHeader().setStretchLastSection(True)
        self._artists.setMaximumHeight(140)
        self._artists.itemSelectionChanged.connect(self._on_artist_picked)
        layout.addWidget(self._artists)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        albums_label = QLabel("Releases")
        albums_label.setProperty("panelTitle", True)
        left_layout.addWidget(albums_label)
        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            [
                "Year",
                "Title",
                "Type",
                "Role",
                "Format",
                "Label",
                "Main artist",
                "Extra / linked",
            ]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._on_release_selected)
        left_layout.addWidget(self._table)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._tracks_label = QLabel("Tracks")
        self._tracks_label.setProperty("panelTitle", True)
        right_layout.addWidget(self._tracks_label)
        self._tracks_hint = QLabel("Select a release to load its Discogs tracklist.")
        self._tracks_hint.setProperty("muted", True)
        self._tracks_hint.setWordWrap(True)
        right_layout.addWidget(self._tracks_hint)
        self._tracks = QTableWidget(0, 4)
        self._tracks.setHorizontalHeaderLabels(["#", "Title", "Duration", "Artists / credits"])
        self._tracks.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tracks.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tracks.horizontalHeader().setStretchLastSection(True)
        right_layout.addWidget(self._tracks)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, stretch=1)

        actions = QHBoxLayout()
        queue_btn = QPushButton("Queue selected for download")
        queue_btn.setToolTip(
            "Create missing-album jobs and search/download now (Wishlist)."
        )
        queue_btn.clicked.connect(self._queue_selected)
        wanted_btn = QPushButton("Add to Wanted")
        wanted_btn.setProperty("secondary", True)
        wanted_btn.setToolTip(
            "Park selected releases on the Wanted shelf without searching yet. "
            "Start download later from Albums → Wanted or Wishlist."
        )
        wanted_btn.clicked.connect(self._add_to_wanted)
        select_all = QPushButton("Select all")
        select_all.setProperty("secondary", True)
        select_all.clicked.connect(self._table.selectAll)
        clear_sel = QPushButton("Clear selection")
        clear_sel.setProperty("secondary", True)
        clear_sel.clicked.connect(self._table.clearSelection)
        actions.addWidget(queue_btn)
        actions.addWidget(wanted_btn)
        actions.addWidget(select_all)
        actions.addWidget(clear_sel)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._artist_hits: list[tuple[str, int]] = []

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id

    def refresh(self) -> None:
        token = (self._container.config.metadata.discogs_user_token or "").strip()
        if not token:
            self._status.setText(
                "Add a Discogs token in Settings → Application, then search an artist."
            )

    def _provider(self) -> DiscogsProvider:
        return DiscogsProvider(
            user_token=self._container.config.metadata.discogs_user_token or ""
        )

    def _search_artist(self) -> None:
        query = self._query.text().strip()
        if not query:
            QMessageBox.information(self, "Discogs", "Enter an artist name.")
            return
        if not (self._container.config.metadata.discogs_user_token or "").strip():
            QMessageBox.warning(
                self,
                "Discogs",
                "Set your Discogs personal access token in Settings first.",
            )
            return
        self._status.setText(f"Searching Discogs for “{query}”…")
        provider = self._provider()

        def work() -> list[tuple[str, int]]:
            results = provider.search(query, "artist", limit=15)
            hits: list[tuple[str, int]] = []
            for result in results:
                name = ""
                artist_id = None
                for field in result.fields:
                    if field.field == "artist":
                        name = str(field.value)
                    elif field.field == "discogs_artist_id":
                        try:
                            artist_id = int(str(field.value))
                        except ValueError:
                            artist_id = None
                if name and artist_id is not None:
                    hits.append((name, artist_id))
            return hits

        def done(hits: object) -> None:
            rows = hits if isinstance(hits, list) else []
            self._artist_hits = rows
            self._artists.setRowCount(len(rows))
            self._table.setRowCount(0)
            self._rows = []
            for index, (name, artist_id) in enumerate(rows):
                self._artists.setItem(index, 0, QTableWidgetItem(name))
                self._artists.setItem(index, 1, QTableWidgetItem(str(artist_id)))
            if not rows:
                self._status.setText("No Discogs artists found.")
                return
            self._status.setText(f"{len(rows)} artist match(es) — select one to load releases.")
            self._artists.selectRow(0)

        run_in_background(
            work,
            on_finished=done,
            on_failed=lambda msg: QMessageBox.warning(self, "Discogs", msg),
        )

    def _on_artist_picked(self) -> None:
        rows = {index.row() for index in self._artists.selectedIndexes()}
        if len(rows) != 1:
            return
        row = next(iter(rows))
        if not (0 <= row < len(self._artist_hits)):
            return
        name, artist_id = self._artist_hits[row]
        self._artist_name = name
        self._artist_id = artist_id
        self._load_releases(artist_id, name)

    def _load_releases(self, artist_id: int, name: str) -> None:
        self._status.setText(f"Loading Discogs releases for {name}…")
        provider = self._provider()

        def work() -> list[_ReleaseRow]:
            raw = provider.list_artist_releases(artist_id, per_page=100, max_pages=5)
            return [_to_row(item, fallback_artist=name) for item in raw]

        def done(rows: object) -> None:
            parsed = rows if isinstance(rows, list) else []
            self._rows = parsed
            self._table.setRowCount(len(parsed))
            self._tracks.setRowCount(0)
            self._tracks_hint.setText("Select a release to load its Discogs tracklist.")
            for index, row in enumerate(parsed):
                values = [
                    row.year,
                    row.title,
                    row.kind,
                    row.role,
                    row.format,
                    row.label,
                    row.artist,
                    row.secondary,
                ]
                for col, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    item.setData(Qt.ItemDataRole.UserRole, row.release_id)
                    self._table.setItem(index, col, item)
            self._status.setText(
                f"{name}: {len(parsed)} release(s) from Discogs (sorted by year). "
                "Select a release to see tracks, or multi-select and queue downloads."
            )
            if parsed:
                self._table.selectRow(0)

        run_in_background(
            work,
            on_finished=done,
            on_failed=lambda msg: QMessageBox.warning(self, "Discogs", msg),
        )

    def _on_release_selected(self) -> None:
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        if len(rows) != 1:
            if len(rows) > 1:
                self._tracks.setRowCount(0)
                self._tracks_hint.setText(
                    f"{len(rows)} releases selected — pick one row to preview tracks."
                )
            return
        row_index = rows[0]
        if not (0 <= row_index < len(self._rows)):
            return
        release = self._rows[row_index]
        self._tracks_hint.setText(f"Loading tracks for “{release.title}”…")
        provider = self._provider()
        kind = "master" if release.kind.casefold() == "master" else "release"
        release_id = release.release_id
        title = release.title

        def work() -> list[dict[str, Any]]:
            return provider.get_release_tracklist(release_id, kind=kind)

        def done(tracks: object) -> None:
            parsed = tracks if isinstance(tracks, list) else []
            # Ignore stale responses if selection changed.
            current = sorted({index.row() for index in self._table.selectedIndexes()})
            if current != [row_index]:
                return
            self._tracks.setRowCount(len(parsed))
            for index, track in enumerate(parsed):
                self._tracks.setItem(index, 0, QTableWidgetItem(str(track.get("position") or "")))
                self._tracks.setItem(index, 1, QTableWidgetItem(str(track.get("title") or "")))
                self._tracks.setItem(index, 2, QTableWidgetItem(str(track.get("duration") or "")))
                self._tracks.setItem(index, 3, QTableWidgetItem(str(track.get("artists") or "")))
            if parsed:
                self._tracks_hint.setText(f"{title}: {len(parsed)} track(s)")
            else:
                self._tracks_hint.setText(f"No tracklist returned for “{title}”.")

        run_in_background(
            work,
            on_finished=done,
            on_failed=lambda msg: QMessageBox.warning(self, "Discogs", msg),
        )

    def _queue_selected(self) -> None:
        if self._library_id is None:
            QMessageBox.warning(self, "Discogs", "Select a library first.")
            return
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        selected = [self._rows[row] for row in rows if 0 <= row < len(self._rows)]
        if not selected:
            QMessageBox.information(self, "Discogs", "Select one or more releases.")
            return

        engine = self._container.acquisition_engine
        auto_queue = self._container.config.acquisition.auto_queue_jobs
        created = 0
        for row in selected:
            artist = row.artist or self._artist_name
            job = engine.create_job(
                library_id=self._library_id,
                job_type=AcquisitionJobType.MISSING_ALBUM,
                artist=artist,
                album=row.title,
                year=int(row.year) if row.year.isdigit() else None,
                preferred_codec=self._container.config.acquisition.preferred_codec or None,
                priority=80,
            )
            engine.update_extra(
                job.id,
                {
                    "discogs_release_id": row.release_id,
                    "discogs_artist_id": self._artist_id,
                    "discogs_role": row.role,
                    "discogs_format": row.format,
                    "discogs_label": row.label,
                    "source": "discogs_browse",
                },
            )
            if auto_queue:
                engine.queue(job.id)
            created += 1

        extra = ""
        if not auto_queue:
            extra = " Jobs are created; use Acquisition → Auto-acquire to search/download."
        QMessageBox.information(
            self,
            "Discogs",
            f"Queued {created} album job(s).{extra}",
        )

    def _add_to_wanted(self) -> None:
        if self._library_id is None:
            QMessageBox.warning(self, "Discogs", "Select a library first.")
            return
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        selected = [self._rows[row] for row in rows if 0 <= row < len(self._rows)]
        if not selected:
            QMessageBox.information(self, "Discogs", "Select one or more releases.")
            return

        engine = self._container.acquisition_engine
        created = 0
        for row in selected:
            artist = row.artist or self._artist_name
            park_album_job(
                engine,
                library_id=self._library_id,
                artist=artist,
                album=row.title,
                year=int(row.year) if row.year.isdigit() else None,
                preferred_codec=self._container.config.acquisition.preferred_codec or None,
                priority=90,
                extra={
                    "discogs_release_id": row.release_id,
                    "discogs_artist_id": self._artist_id,
                    "discogs_role": row.role,
                    "discogs_format": row.format,
                    "discogs_label": row.label,
                    "source": "wanted",
                },
            )
            created += 1

        QMessageBox.information(
            self,
            "Discogs",
            f"Added {created} release(s) to Wanted. "
            "Open Albums → Wanted (or Wishlist → Show Wanted) and click Start download when ready.",
        )


def _to_row(item: dict[str, Any], *, fallback_artist: str) -> _ReleaseRow:
    title = str(item.get("title") or "").strip() or "(untitled)"
    year_val = item.get("year")
    year = str(year_val) if year_val not in (None, 0, "0") else ""
    kind = str(item.get("type") or item.get("format") or "release").strip()
    role = str(item.get("role") or "").strip()
    fmt = item.get("format")
    if isinstance(fmt, list):
        format_text = ", ".join(str(part) for part in fmt if part)
    else:
        format_text = str(fmt or "").strip()
    label = str(item.get("label") or "").strip()
    artist = str(item.get("artist") or fallback_artist).strip()
    # Extra linked artists / credits when Discogs provides them on the list payload.
    secondary_parts: list[str] = []
    if role and role.casefold() not in {"main", "primary"}:
        secondary_parts.append(f"role: {role}")
    stats = item.get("stats") or {}
    if isinstance(stats, dict) and stats.get("community"):
        community = stats["community"]
        if isinstance(community, dict):
            have = community.get("have")
            want = community.get("want")
            if have is not None or want is not None:
                secondary_parts.append(f"have {have or 0} / want {want or 0}")
    thumb = str(item.get("thumb") or "")
    release_id = int(item.get("id") or 0)
    return _ReleaseRow(
        release_id=release_id,
        title=title,
        year=year,
        kind=kind,
        role=role or "Main",
        format=format_text,
        label=label,
        artist=artist,
        secondary="; ".join(secondary_parts),
        thumb=thumb,
    )

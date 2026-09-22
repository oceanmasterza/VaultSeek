"""Review queue page — approve / reject / defer / assign album slot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.core.exceptions import ReviewError
from vaultseek.gui.async_task import run_in_background
from vaultseek.gui.widgets.empty_state import EmptyState
from vaultseek.gui.widgets.flow_host import FlowHost, ensure_control_labels
from vaultseek.gui.widgets.numeric_fields import fit_numeric_spinboxes
from vaultseek.gui.widgets.page_header import add_page_header
from vaultseek.gui.widgets.table_utils import (
    begin_table_update,
    configure_data_table,
    end_table_update,
)
from vaultseek.services.identify_retry_preview import (
    ApplyMatchesReport,
    IdentifyPreviewReport,
)
from vaultseek.services.library_tracklist_matcher import AlbumSlotRecommendation
from vaultseek.services.review_display import PlayableReview, select_playable_reviews
from vaultseek.services.review_queue_service import AlbumChoice, AlbumSlotChoice

_ITEM_ID_ROLE = Qt.ItemDataRole.UserRole
_TRACK_PATH_ROLE = Qt.ItemDataRole.UserRole + 1
_ALBUM_ID_ROLE = Qt.ItemDataRole.UserRole
_RECOMMENDED_ROLE = Qt.ItemDataRole.UserRole + 1


def format_preview_retry_summary(report: IdentifyPreviewReport) -> str:
    """Layperson summary for a dry-run identify retry preview."""
    lines = [
        f"Previewed {len(report.rows)} pending song(s).",
        f"Would apply confident matches: {report.would_auto_approve}",
        f"Would stay in Review / re-identify: {report.stay_in_review}",
        f"Opaque titles fixed by filename: {report.opaque_title_fixed}",
        "",
        "No changes were written. Use Retry to apply safe matches.",
    ]
    return "\n".join(lines)


def format_apply_retry_summary(report: ApplyMatchesReport) -> str:
    """Accurate completion text for ``apply_safe_matches`` (not a preview)."""
    considered = len(report.preview.rows)
    changed = report.applied > 0 or report.enqueued_identify > 0
    if changed:
        headline = "Retry finished — changes were applied."
    else:
        headline = "Retry finished — no changes were applied."
    lines = [
        headline,
        f"Songs considered: {considered}",
        f"Assigned: {report.applied}",
        f"Failed: {report.failed}",
        f"Re-identify queued: {report.enqueued_identify}",
    ]
    errors = [row.error for row in report.results if row.error]
    if errors:
        lines.append("")
        lines.append("Errors:")
        for message in errors[:8]:
            lines.append(f"• {message}")
        if len(errors) > 8:
            lines.append(f"• …and {len(errors) - 8} more")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _AssignChoice:
    """User-confirmed album assignment for one Review item."""

    album_id: UUID
    title: str
    track_number: int | None
    disc_number: int
    artist_id: UUID | None
    better_copy_note: str | None


class ReviewPage(QWidget):
    """Human approval gate for uncertain metadata and duplicates."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._rows: dict[UUID, PlayableReview] = {}
        self._busy = False
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(1.0)
        self._player.setAudioOutput(self._audio)

        layout = QVBoxLayout(self)
        self._heading = add_page_header(
            layout,
            "Review Queue",
            "Play a song, then approve, reject, or assign it to an album. "
            "Assign works for any album already in this library — not only the "
            "suggested matches. A better existing file does not block tagging; "
            "duplicates are archived safely afterward.",
        )

        self._empty = EmptyState(
            "Nothing to review",
            "Uncertain identifications with a playable file land here. "
            "Scan Incoming or wait for the pipeline.",
        )
        layout.addWidget(self._empty)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Type", "Track", "Confidence", "Album suggestions", "Reason"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_data_table(self._table)
        layout.addWidget(self._table)

        buttons = FlowHost(spacing=6)
        self._play_btn = QPushButton("Play")
        self._play_btn.setToolTip("Play the selected song so you can identify it")
        self._assign_btn = QPushButton("Assign album…")
        self._assign_btn.setToolTip(
            "Pick any album in this library (searchable), set the song title "
            "and track numbers, then apply"
        )
        self._approve_btn = QPushButton("Approve")
        self._approve_btn.setDefault(True)
        self._approve_btn.setToolTip("Approve selected items (Ctrl+Enter)")
        self._reject_btn = QPushButton("Reject")
        self._reject_btn.setToolTip("Reject selected items (Ctrl+Shift+R)")
        self._defer_btn = QPushButton("Defer")
        self._preview_btn = QPushButton("Preview retry")
        self._preview_btn.setToolTip(
            "Dry-run filename + library matching for pending songs (no writes)"
        )
        self._retry_btn = QPushButton("Retry")
        self._retry_btn.setToolTip(
            "Apply safe confident matches and re-queue the rest (writes tags; "
            "runs in the background)"
        )
        self._refresh_btn = QPushButton("Refresh")
        self._reject_btn.setProperty("secondary", True)
        self._defer_btn.setProperty("secondary", True)
        self._preview_btn.setProperty("secondary", True)
        self._retry_btn.setProperty("secondary", True)
        self._refresh_btn.setProperty("secondary", True)
        self._play_btn.clicked.connect(self._toggle_play)
        self._assign_btn.clicked.connect(self._assign_album)
        self._approve_btn.clicked.connect(self._approve_selected)
        self._reject_btn.clicked.connect(self._reject_selected)
        self._defer_btn.clicked.connect(self._defer_selected)
        self._preview_btn.clicked.connect(self._preview_retry)
        self._retry_btn.clicked.connect(self._apply_retry)
        self._refresh_btn.clicked.connect(self.refresh)
        buttons.add_widget(self._play_btn)
        buttons.add_widget(self._assign_btn)
        buttons.add_widget(self._approve_btn)
        buttons.add_widget(self._reject_btn)
        buttons.add_widget(self._defer_btn)
        buttons.add_widget(self._preview_btn)
        buttons.add_widget(self._retry_btn)
        buttons.add_widget(self._refresh_btn)
        layout.addWidget(buttons)
        ensure_control_labels(self)

        _approve_a = QShortcut(QKeySequence("Ctrl+Return"), self)
        _approve_a.activated.connect(self._approve_selected)
        _approve_b = QShortcut(QKeySequence("Ctrl+Enter"), self)
        _approve_b.activated.connect(self._approve_selected)
        _reject = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        _reject.activated.connect(self._reject_selected)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._stop_playback()
        self._rows = {}
        sorting = begin_table_update(self._table)
        self._table.setRowCount(0)
        try:
            if self._library_id is None:
                self._heading.setText("Review Queue")
                self._empty.setVisible(True)
                self._table.setVisible(False)
                return

            playable = self._playable_rows()
            self._rows = {row.item_id: row for row in playable}
            self._heading.setText(f"Review Queue ({len(playable)} pending)")
            empty = len(playable) == 0
            self._empty.setVisible(empty)
            self._table.setVisible(not empty)
            if empty:
                return
            self._table.setRowCount(len(playable))
            for row_index, item in enumerate(playable):
                suggestion = self._suggestion_summary(item.item_id)
                cells = [
                    QTableWidgetItem(item.review_type),
                    QTableWidgetItem(item.label),
                    QTableWidgetItem(
                        f"{item.confidence:.0%}" if item.confidence is not None else "—"
                    ),
                    QTableWidgetItem(suggestion),
                    QTableWidgetItem(item.reason),
                ]
                for cell in cells:
                    cell.setData(_ITEM_ID_ROLE, str(item.item_id))
                    cell.setData(_TRACK_PATH_ROLE, item.audio_path)
                for column, cell in enumerate(cells):
                    self._table.setItem(row_index, column, cell)
        finally:
            end_table_update(self._table, sorting=sorting)

    def pending_count(self) -> int:
        if self._library_id is None:
            return 0
        return len(self._playable_rows())

    def _playable_rows(self) -> list[PlayableReview]:
        if self._library_id is None:
            return []
        items = self._container.review_queue.get_pending(self._library_id)

        def artist_name(artist_id: UUID) -> str | None:
            artist = self._container.artist_repo.get(artist_id)
            return artist.name if artist is not None else None

        def duplicate_track_ids(group_id: UUID) -> list[UUID]:
            members = self._container.duplicate_repo.get_members(group_id)
            return [member.track_id for member in members]

        return select_playable_reviews(
            items,
            track_for=self._container.track_repo.get_by_id,
            artist_name=artist_name,
            duplicate_track_ids=duplicate_track_ids,
        )

    def _suggestion_summary(self, item_id: UUID) -> str:
        try:
            recs = self._container.review_queue.album_recommendations(item_id)
        except ReviewError:
            return "—"
        if not recs:
            return "—"
        top = recs[0]
        warn = " (better copy exists)" if top.existing_is_better else ""
        return f"{top.artist_name} — {top.album_title} / {top.slot_title}{warn}"

    def _selected_rows(self) -> list[PlayableReview]:
        """Resolve selection via stable item IDs (survives column sort)."""
        ids: list[UUID] = []
        seen: set[UUID] = set()
        for index in self._table.selectedIndexes():
            cell = self._table.item(index.row(), 0)
            if cell is None:
                continue
            raw = cell.data(_ITEM_ID_ROLE)
            if not raw:
                continue
            item_id = UUID(str(raw))
            if item_id in seen:
                continue
            seen.add(item_id)
            ids.append(item_id)
        return [self._rows[item_id] for item_id in ids if item_id in self._rows]

    def _toggle_play(self) -> None:
        selected = self._selected_rows()
        if len(selected) != 1:
            QMessageBox.information(self, "Review", "Select one song to play.")
            return
        path = selected[0].audio_path
        current = self._player.source().toLocalFile()
        if (
            current == path
            and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ):
            self._stop_playback()
            return
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()
        self._play_btn.setText("Stop")

    def _stop_playback(self) -> None:
        self._player.stop()
        self._play_btn.setText("Play")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in (
            self._assign_btn,
            self._approve_btn,
            self._reject_btn,
            self._defer_btn,
            self._preview_btn,
            self._retry_btn,
        ):
            button.setEnabled(not busy)

    def _assign_album(self) -> None:
        if self._busy:
            return
        selected = self._selected_rows()
        if len(selected) != 1:
            QMessageBox.information(self, "Review", "Select one song to assign.")
            return
        if self._library_id is None:
            return
        row = selected[0]
        library_id = self._library_id
        item_id = row.item_id
        try:
            albums = self._container.review_queue.assignment_albums(library_id)
            recommendations = self._container.review_queue.album_recommendations(item_id)
        except ReviewError as exc:
            QMessageBox.warning(self, "Review", str(exc))
            return
        if not albums and not recommendations:
            QMessageBox.information(
                self,
                "Assign album",
                "This library has no albums yet. Scan or organize some music first, "
                "then you can assign this song.",
            )
            return
        dialog = _AlbumAssignDialog(
            song_label=row.label,
            albums=albums,
            recommendations=recommendations,
            load_slots=lambda album_id: self._container.review_queue.assignment_slots(
                library_id, album_id
            ),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        choice = dialog.selected()
        if choice is None:
            return
        self._set_busy(True)

        def work() -> None:
            self._container.review_queue.assign_album_slot(
                item_id,
                album_id=choice.album_id,
                title=choice.title,
                track_number=choice.track_number,
                disc_number=choice.disc_number,
                artist_id=choice.artist_id,
            )

        def done(_: object) -> None:
            self._set_busy(False)
            if self._library_id != library_id:
                return
            note = choice.better_copy_note or ""
            if note:
                QMessageBox.information(
                    self,
                    "Assign album",
                    f"Song tagged and assigned.\n\n{note}",
                )
            self.refresh()

        def failed(message: str) -> None:
            self._set_busy(False)
            if self._library_id != library_id:
                return
            QMessageBox.warning(self, "Assign album", message)

        run_in_background(work, on_finished=done, on_failed=failed)

    def _preview_retry(self) -> None:
        if self._busy or self._library_id is None:
            return
        library_id = self._library_id
        self._set_busy(True)

        def work() -> IdentifyPreviewReport:
            return self._container.identify_retry_preview.preview_pending(library_id)

        def done(report: object) -> None:
            self._set_busy(False)
            if self._library_id != library_id:
                return
            if not isinstance(report, IdentifyPreviewReport):
                QMessageBox.warning(
                    self,
                    "Identify retry preview",
                    "Unexpected preview result type.",
                )
                return
            QMessageBox.information(
                self, "Identify retry preview", format_preview_retry_summary(report)
            )

        def failed(message: str) -> None:
            self._set_busy(False)
            if self._library_id != library_id:
                return
            QMessageBox.warning(self, "Identify retry preview", message)

        run_in_background(work, on_finished=done, on_failed=failed)

    def _apply_retry(self) -> None:
        if self._busy or self._library_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Retry identify",
            "Apply safe confident album matches and re-queue the rest for identify?\n\n"
            "This writes tags for confident matches. Preview first if unsure.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        library_id = self._library_id
        self._set_busy(True)

        def work() -> ApplyMatchesReport:
            return self._container.identify_retry_preview.apply_safe_matches(
                library_id, dry_run=False
            )

        def done(report: object) -> None:
            self._set_busy(False)
            if self._library_id != library_id:
                return
            if not isinstance(report, ApplyMatchesReport):
                QMessageBox.warning(
                    self,
                    "Identify retry",
                    "Unexpected retry result type.",
                )
                return
            QMessageBox.information(self, "Identify retry", format_apply_retry_summary(report))
            self.refresh()

        def failed(message: str) -> None:
            self._set_busy(False)
            if self._library_id != library_id:
                return
            QMessageBox.warning(self, "Identify retry", message)

        run_in_background(work, on_finished=done, on_failed=failed)

    def _approve_selected(self) -> None:
        self._act(self._container.review_queue.approve)

    def _reject_selected(self) -> None:
        self._act(self._container.review_queue.reject)

    def _defer_selected(self) -> None:
        self._act(self._container.review_queue.defer)

    def _act(self, action: object) -> None:
        if self._busy:
            return
        ids = [row.item_id for row in self._selected_rows()]
        if not ids:
            QMessageBox.information(self, "Review", "Select one or more items first.")
            return
        library_id = self._library_id
        self._set_busy(True)

        def work() -> None:
            for item_id in ids:
                action(item_id)  # type: ignore[operator]

        def done(_: object) -> None:
            self._set_busy(False)
            if self._library_id != library_id:
                return
            self.refresh()

        def failed(message: str) -> None:
            self._set_busy(False)
            if self._library_id != library_id:
                return
            QMessageBox.warning(self, "Review", message)
            self.refresh()

        run_in_background(work, on_finished=done, on_failed=failed)


class _AlbumAssignDialog(QDialog):
    """Searchable same-library album picker with optional slot + editable title."""

    def __init__(
        self,
        *,
        song_label: str,
        albums: tuple[AlbumChoice, ...],
        recommendations: tuple[AlbumSlotRecommendation, ...],
        load_slots: Callable[[UUID], tuple[AlbumSlotChoice, ...]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign album")
        self.setMinimumWidth(560)
        self._load_slots = load_slots
        self._recommendations = recommendations
        self._albums_by_id = {album.album_id: album for album in albums}
        self._rec_by_album: dict[UUID, AlbumSlotRecommendation] = {}
        for rec in recommendations:
            current = self._rec_by_album.get(rec.album_id)
            if current is None or rec.score > current.score:
                self._rec_by_album[rec.album_id] = rec
        for rec in recommendations:
            if rec.album_id not in self._albums_by_id:
                self._albums_by_id[rec.album_id] = AlbumChoice(
                    album_id=rec.album_id,
                    artist_name=rec.artist_name,
                    album_title=rec.album_title,
                    year=None,
                )
        self._slots: tuple[AlbumSlotChoice, ...] = ()
        self._choice: _AssignChoice | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Song: {song_label}"))
        layout.addWidget(
            QLabel(
                "Choose any album already in this library. Suggestions appear first when "
                "available. You can set a custom title for a missing song."
            )
        )

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search albums or artists…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._rebuild_album_table)
        layout.addWidget(self._search)

        self._album_table = QTableWidget(0, 4)
        self._album_table.setHorizontalHeaderLabels(
            ["Suggested", "Artist — Album", "Year", "Evidence"]
        )
        self._album_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._album_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._album_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        configure_data_table(self._album_table)
        self._album_table.itemSelectionChanged.connect(self._on_album_selected)
        layout.addWidget(self._album_table)

        form = QFormLayout()
        self._slot_combo = QComboBox()
        self._slot_combo.setEditable(False)
        self._slot_combo.currentIndexChanged.connect(self._on_slot_changed)
        form.addRow("Existing song slot", self._slot_combo)

        self._title = QLineEdit()
        self._title.setPlaceholderText("Correct song title")
        form.addRow("Song title", self._title)

        numbers = QHBoxLayout()
        self._track_number = QSpinBox()
        self._track_number.setRange(0, 999)
        self._track_number.setSpecialValueText("—")
        self._track_number.setToolTip("Track number on the album (0 = none)")
        self._disc_number = QSpinBox()
        self._disc_number.setRange(1, 99)
        self._disc_number.setValue(1)
        self._disc_number.setToolTip("Disc number")
        numbers.addWidget(QLabel("Track #"))
        numbers.addWidget(self._track_number)
        numbers.addWidget(QLabel("Disc #"))
        numbers.addWidget(self._disc_number)
        numbers.addStretch(1)
        form.addRow("Numbers", numbers)

        self._evidence = QLabel("")
        self._evidence.setWordWrap(True)
        self._evidence.setProperty("muted", True)
        form.addRow("Notes", self._evidence)
        layout.addLayout(form)
        fit_numeric_spinboxes(self)

        seed_title = song_label
        if " — " in song_label:
            seed_title = song_label.rsplit(" — ", 1)[-1].strip() or song_label
        self._title.setText(seed_title)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        buttons.accepted.connect(self._accept_choice)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._rebuild_album_table()
        if self._album_table.rowCount() > 0:
            self._album_table.selectRow(0)

    def _ordered_albums(self) -> list[AlbumChoice]:
        recommended_ids = [rec.album_id for rec in self._recommendations]
        seen: set[UUID] = set()
        ordered: list[AlbumChoice] = []
        for album_id in recommended_ids:
            if album_id in seen:
                continue
            album = self._albums_by_id.get(album_id)
            if album is None:
                continue
            seen.add(album_id)
            ordered.append(album)
        rest = sorted(
            (album for album in self._albums_by_id.values() if album.album_id not in seen),
            key=lambda album: (
                album.artist_name.casefold(),
                album.album_title.casefold(),
                album.year or 0,
            ),
        )
        ordered.extend(rest)
        return ordered

    def _rebuild_album_table(self) -> None:
        needle = self._search.text().strip().casefold()
        selected = self._selected_album_id()
        sorting = begin_table_update(self._album_table)
        self._album_table.setRowCount(0)
        rows: list[AlbumChoice] = []
        for album in self._ordered_albums():
            hay = f"{album.artist_name} {album.album_title}".casefold()
            if needle and needle not in hay:
                continue
            rows.append(album)
        self._album_table.setRowCount(len(rows))
        restore_row = 0
        for row, album in enumerate(rows):
            rec = self._rec_by_album.get(album.album_id)
            suggested = "Yes" if rec is not None else ""
            evidence = ", ".join(rec.reasons) if rec is not None else "—"
            year = str(album.year) if album.year is not None else "—"
            cells = [
                QTableWidgetItem(suggested),
                QTableWidgetItem(f"{album.artist_name} — {album.album_title}"),
                QTableWidgetItem(year),
                QTableWidgetItem(evidence),
            ]
            for cell in cells:
                cell.setData(_ALBUM_ID_ROLE, str(album.album_id))
                cell.setData(_RECOMMENDED_ROLE, bool(rec is not None))
            for column, cell in enumerate(cells):
                self._album_table.setItem(row, column, cell)
            if selected is not None and album.album_id == selected:
                restore_row = row
        end_table_update(self._album_table, sorting=sorting)
        if rows:
            self._album_table.selectRow(restore_row)

    def _selected_album_id(self) -> UUID | None:
        indexes = self._album_table.selectedIndexes()
        if not indexes:
            return None
        cell = self._album_table.item(indexes[0].row(), 0)
        if cell is None:
            return None
        raw = cell.data(_ALBUM_ID_ROLE)
        if not raw:
            return None
        return UUID(str(raw))

    def _on_album_selected(self) -> None:
        album_id = self._selected_album_id()
        self._slot_combo.blockSignals(True)
        self._slot_combo.clear()
        self._slots = ()
        self._slot_combo.addItem("(Custom title — missing song)", userData=None)
        if album_id is None:
            self._slot_combo.blockSignals(False)
            self._update_evidence(None)
            return
        try:
            slots = self._load_slots(album_id)
        except ReviewError as exc:
            self._slot_combo.blockSignals(False)
            self._evidence.setText(str(exc))
            return
        self._slots = tuple(slots)
        for index, slot in enumerate(self._slots):
            track = slot.track_number if slot.track_number is not None else "—"
            label = f"{track} · {slot.title} (disc {slot.disc_number})"
            self._slot_combo.addItem(label, userData=index)
        rec = self._rec_by_album.get(album_id)
        prefer_index = 0
        if rec is not None:
            for index, slot in enumerate(self._slots):
                if (
                    slot.title.casefold() == rec.slot_title.casefold()
                    and slot.track_number == rec.track_number
                    and slot.disc_number == rec.disc_number
                ):
                    prefer_index = index + 1
                    break
            else:
                self._title.setText(rec.slot_title)
                if rec.track_number is not None:
                    self._track_number.setValue(rec.track_number)
                else:
                    self._track_number.setValue(0)
                self._disc_number.setValue(rec.disc_number)
        self._slot_combo.setCurrentIndex(prefer_index)
        self._slot_combo.blockSignals(False)
        self._on_slot_changed(prefer_index)
        self._update_evidence(rec)

    def _on_slot_changed(self, index: int) -> None:
        if index <= 0:
            return
        raw = self._slot_combo.currentData()
        if raw is None:
            return
        try:
            slot_index = int(raw)
        except (TypeError, ValueError):
            return
        if not (0 <= slot_index < len(self._slots)):
            return
        slot = self._slots[slot_index]
        self._title.setText(slot.title)
        if slot.track_number is not None:
            self._track_number.setValue(slot.track_number)
        else:
            self._track_number.setValue(0)
        self._disc_number.setValue(slot.disc_number)

    def _update_evidence(self, rec: AlbumSlotRecommendation | None) -> None:
        if rec is None:
            self._evidence.setText(
                "No automatic match for this album. Enter the correct title and "
                "track numbers for the missing song."
            )
            return
        parts = [f"Match score {rec.score:.0%}: " + ", ".join(rec.reasons)]
        if rec.existing_is_better:
            parts.append(
                "A better-quality copy already exists in the library. Assigning "
                "still tags this song correctly; the duplicate/archive path keeps "
                "the better file."
            )
        if rec.version_conflict:
            parts.append("Version wording differs — confirm the title before applying.")
        if not rec.duration_ok:
            parts.append("Duration does not match the library slot closely.")
        self._evidence.setText(" ".join(parts))

    def _accept_choice(self) -> None:
        album_id = self._selected_album_id()
        if album_id is None:
            QMessageBox.information(self, "Assign album", "Select an album first.")
            return
        title = self._title.text().strip()
        if not title:
            QMessageBox.information(self, "Assign album", "Enter the correct song title.")
            return
        track_number = self._track_number.value() or None
        disc_number = self._disc_number.value()
        artist_id: UUID | None = None
        raw = self._slot_combo.currentData()
        if raw is not None:
            try:
                slot_index = int(raw)
            except (TypeError, ValueError):
                slot_index = -1
            if 0 <= slot_index < len(self._slots):
                artist_id = self._slots[slot_index].artist_id
        rec = self._rec_by_album.get(album_id)
        if artist_id is None and rec is not None:
            artist_id = rec.artist_id
        better_note = None
        if rec is not None and rec.existing_is_better:
            better_note = (
                "A better copy already exists. This song was tagged for identity; "
                "the better library file is kept."
            )
        self._choice = _AssignChoice(
            album_id=album_id,
            title=title,
            track_number=track_number,
            disc_number=disc_number,
            artist_id=artist_id,
            better_copy_note=better_note,
        )
        self.accept()

    def selected(self) -> _AssignChoice | None:
        return self._choice

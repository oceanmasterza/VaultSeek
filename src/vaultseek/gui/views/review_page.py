"""Review queue page — approve / reject / defer pending items."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.core.exceptions import ReviewError
from vaultseek.gui.widgets.empty_state import EmptyState
from vaultseek.gui.widgets.page_header import add_page_header
from vaultseek.gui.widgets.table_utils import (
    begin_table_update,
    configure_data_table,
    end_table_update,
)
from vaultseek.services.review_display import PlayableReview, select_playable_reviews


class ReviewPage(QWidget):
    """Human approval gate for uncertain metadata and duplicates."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._rows: list[PlayableReview] = []
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(1.0)
        self._player.setAudioOutput(self._audio)

        layout = QVBoxLayout(self)
        self._heading = add_page_header(
            layout,
            "Review Queue",
            "Approve, reject, or defer uncertain identifications. "
            "Play the selected file, then decide. Songs with no local audio file "
            "are left off this list. High-confidence matches auto-approve using "
            "Settings → Identify auto-approve.",
        )

        self._empty = EmptyState(
            "Nothing to review",
            "Uncertain identifications with a playable file land here. "
            "Scan Incoming or wait for the pipeline.",
        )
        layout.addWidget(self._empty)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Type", "Track", "Confidence", "Reason"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_data_table(self._table)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        self._play_btn = QPushButton("Play")
        self._play_btn.setToolTip("Play the selected song so you can identify it")
        self._approve_btn = QPushButton("Approve")
        self._approve_btn.setDefault(True)
        self._approve_btn.setToolTip("Approve selected items (Ctrl+Enter)")
        self._reject_btn = QPushButton("Reject")
        self._reject_btn.setToolTip("Reject selected items (Ctrl+Shift+R)")
        self._defer_btn = QPushButton("Defer")
        self._refresh_btn = QPushButton("Refresh")
        self._reject_btn.setProperty("secondary", True)
        self._defer_btn.setProperty("secondary", True)
        self._refresh_btn.setProperty("secondary", True)
        self._play_btn.clicked.connect(self._toggle_play)
        self._approve_btn.clicked.connect(self._approve_selected)
        self._reject_btn.clicked.connect(self._reject_selected)
        self._defer_btn.clicked.connect(self._defer_selected)
        self._refresh_btn.clicked.connect(self.refresh)
        buttons.addWidget(self._play_btn)
        buttons.addWidget(self._approve_btn)
        buttons.addWidget(self._reject_btn)
        buttons.addWidget(self._defer_btn)
        buttons.addWidget(self._refresh_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

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
        self._rows = []
        sorting = begin_table_update(self._table)
        self._table.setRowCount(0)
        try:
            if self._library_id is None:
                self._heading.setText("Review Queue")
                self._empty.setVisible(True)
                self._table.setVisible(False)
                return

            self._rows = self._playable_rows()
            self._heading.setText(f"Review Queue ({len(self._rows)} pending)")
            empty = len(self._rows) == 0
            self._empty.setVisible(empty)
            self._table.setVisible(not empty)
            if empty:
                return
            self._table.setRowCount(len(self._rows))
            for row, item in enumerate(self._rows):
                self._table.setItem(row, 0, QTableWidgetItem(item.review_type))
                self._table.setItem(row, 1, QTableWidgetItem(item.label))
                conf = f"{item.confidence:.0%}" if item.confidence is not None else "—"
                self._table.setItem(row, 2, QTableWidgetItem(conf))
                self._table.setItem(row, 3, QTableWidgetItem(item.reason))
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

    def _selected_rows(self) -> list[PlayableReview]:
        indexes = {index.row() for index in self._table.selectedIndexes()}
        return [self._rows[row] for row in sorted(indexes) if 0 <= row < len(self._rows)]

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

    def _approve_selected(self) -> None:
        self._act(self._container.review_queue.approve)

    def _reject_selected(self) -> None:
        self._act(self._container.review_queue.reject)

    def _defer_selected(self) -> None:
        self._act(self._container.review_queue.defer)

    def _act(self, action: object) -> None:
        ids = [row.item_id for row in self._selected_rows()]
        if not ids:
            QMessageBox.information(self, "Review", "Select one or more items first.")
            return
        try:
            for item_id in ids:
                action(item_id)  # type: ignore[operator]
        except ReviewError as exc:
            QMessageBox.warning(self, "Review", str(exc))
        self.refresh()

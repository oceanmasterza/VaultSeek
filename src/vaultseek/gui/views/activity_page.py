"""Activity page — combined pipeline + wishlist timeline."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.datetime_format import format_local_datetime
from vaultseek.gui.widgets.empty_state import EmptyState
from vaultseek.services.activity_feed import (
    ActivityItem,
    ActivitySource,
    build_activity_feed,
)


class ActivityPage(QWidget):
    """Read-mostly Lidarr-style activity feed. Act on Jobs / Wishlist pages."""

    navigate_requested = Signal(str)

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._items: list[ActivityItem] = []

        layout = QVBoxLayout(self)
        heading = QLabel("Activity")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        help_lbl = QLabel(
            "Pipeline jobs and wishlist downloads in one timeline. "
            "Double-click a row to open Jobs or Wishlist."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addWidget(help_lbl)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Show:"))
        self._filter = QComboBox()
        self._filter.addItem("All", None)
        self._filter.addItem("Pipeline", ActivitySource.PIPELINE)
        self._filter.addItem("Wishlist", ActivitySource.WISHLIST)
        self._filter.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self._filter)
        toolbar.addStretch(1)
        open_jobs = QPushButton("Open Jobs")
        open_jobs.setProperty("secondary", True)
        open_jobs.clicked.connect(lambda: self.navigate_requested.emit("jobs"))
        open_wishlist = QPushButton("Open Wishlist")
        open_wishlist.setProperty("secondary", True)
        open_wishlist.clicked.connect(lambda: self.navigate_requested.emit("acquisition"))
        find_music = QPushButton("Find music…")
        find_music.setProperty("secondary", True)
        find_music.clicked.connect(lambda: self.navigate_requested.emit("find"))
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("secondary", True)
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(open_jobs)
        toolbar.addWidget(open_wishlist)
        toolbar.addWidget(find_music)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        self._summary = QLabel("")
        self._summary.setProperty("muted", True)
        layout.addWidget(self._summary)

        self._empty = EmptyState(
            "Nothing running yet",
            "Scan Incoming to process files, or Find music to queue wishlist downloads.",
            primary_label="Scan Incoming",
            on_primary=lambda: self.navigate_requested.emit("scan"),
            secondary_label="Find music",
            on_secondary=lambda: self.navigate_requested.emit("find"),
        )
        layout.addWidget(self._empty)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["When", "Source", "Kind", "Status", "Summary", "Detail"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self._table, stretch=1)

        open_row = QHBoxLayout()
        open_btn = QPushButton("Open…")
        open_btn.setToolTip("Open Jobs or Wishlist for the selected row.")
        open_btn.clicked.connect(self._open_selected)
        open_row.addWidget(open_btn)
        open_row.addStretch(1)
        layout.addLayout(open_row)

        self._empty.setVisible(False)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._items = []
        self._table.setRowCount(0)
        if self._library_id is None:
            self._summary.setText("No library selected.")
            self._empty.setVisible(True)
            self._table.setVisible(False)
            return

        source = self._filter.currentData()
        source_filter = source if isinstance(source, ActivitySource) else None
        self._items = build_activity_feed(
            self._container,
            self._library_id,
            source_filter=source_filter,
        )
        pipeline_n = sum(1 for i in self._items if i.source is ActivitySource.PIPELINE)
        wishlist_n = sum(1 for i in self._items if i.source is ActivitySource.WISHLIST)
        self._summary.setText(
            f"{len(self._items)} event(s) · {pipeline_n} pipeline · {wishlist_n} wishlist"
        )

        empty = len(self._items) == 0
        self._empty.setVisible(empty)
        self._table.setVisible(not empty)
        if empty:
            return

        self._table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            source_label = "Pipeline" if item.source is ActivitySource.PIPELINE else "Wishlist"
            values = [
                format_local_datetime(item.when),
                source_label,
                item.kind,
                item.status,
                item.summary,
                item.detail,
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 4:
                    cell.setToolTip(item.detail or item.summary)
                self._table.setItem(row, col, cell)

    def _open_selected(self, *_args: object) -> None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        if len(rows) != 1:
            if self._items:
                self.navigate_requested.emit(self._items[0].navigate_key)
            return
        row = next(iter(rows))
        if 0 <= row < len(self._items):
            self.navigate_requested.emit(self._items[row].navigate_key)

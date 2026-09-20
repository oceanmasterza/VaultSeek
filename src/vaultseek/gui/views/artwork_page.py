"""Artwork browse page — cover status and the same album images as Albums."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImageReader, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.debounce import connect_debounced
from vaultseek.gui.widgets.flow_host import FlowHost, add_labeled_field, ensure_control_labels
from vaultseek.gui.widgets.table_utils import (
    begin_table_update,
    configure_data_table,
    end_table_update,
)
from vaultseek.models.dto.browse_dto import ArtworkBrowseRow

_THUMB = 72


class ArtworkPage(QWidget):
    """Album-centric artwork status (ok / low-res / missing) with cover images."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._rows: list[ArtworkBrowseRow] = []
        self._full_cover: QPixmap | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Artwork")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        help_lbl = QLabel(
            "Same album covers as the Albums page, from the artwork cache "
            "(embedded art and Cover Art Archive). Missing covers are fetched "
            "by the fetch_artwork pipeline jobs."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addWidget(help_lbl)

        toolbar = FlowHost(spacing=6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by album or artist…")
        self._search.setClearButtonEnabled(True)
        connect_debounced(self._search.textChanged, self.refresh, parent=self)
        add_labeled_field(toolbar, "Search", self._search, expand=True)
        self._missing_only = QCheckBox("Problems only")
        self._missing_only.setToolTip("Show missing and low-resolution covers only.")
        self._missing_only.toggled.connect(self.refresh)
        toolbar.add_widget(self._missing_only)
        layout.addWidget(toolbar)

        split = QSplitter()
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Cover", "Album", "Artist", "Tracks", "Status", "Source", "Size"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setIconSize(QSize(_THUMB, _THUMB))
        self._table.verticalHeader().setDefaultSectionSize(_THUMB + 8)
        configure_data_table(self._table)
        self._table.itemSelectionChanged.connect(self._show_selected_cover)
        split.addWidget(self._table)

        cover_panel = QFrame()
        cover_panel.setProperty("dashPanel", True)
        cover_layout = QVBoxLayout(cover_panel)
        self._cover_title = QLabel("Cover")
        self._cover_title.setProperty("panelTitle", True)
        self._cover_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_layout.addWidget(self._cover_title)
        self._cover_image = QLabel("Select an album")
        self._cover_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_image.setMinimumSize(220, 220)
        self._cover_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        cover_layout.addWidget(self._cover_image, stretch=1)
        self._cover_meta = QLabel("")
        self._cover_meta.setProperty("muted", True)
        self._cover_meta.setWordWrap(True)
        self._cover_meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_layout.addWidget(self._cover_meta)
        split.addWidget(cover_panel)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, stretch=1)

        self._status = QLabel("")
        layout.addWidget(self._status)
        ensure_control_labels(self)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        sorting = begin_table_update(self._table)
        self._table.setRowCount(0)
        self._rows = []
        try:
            if self._library_id is None:
                self._status.setText("No library selected — create one in Settings.")
                self._clear_cover()
                return
            min_w = self._container.config.artwork.min_width
            min_h = self._container.config.artwork.min_height
            needle = self._search.text().strip() or None
            rows = self._container.artwork_repo.list_browse_for_library(
                self._library_id,
                missing_only=False,
                query=needle,
                limit=500,
                min_width=min_w,
                min_height=min_h,
            )
            if self._missing_only.isChecked():
                rows = [row for row in rows if row.status != "ok"]
            self._rows = list(rows)
            status_label = {"ok": "OK", "missing": "Missing", "low_res": "Low-res"}
            self._table.setRowCount(len(self._rows))
            for i, row in enumerate(self._rows):
                cover = QTableWidgetItem()
                thumb = _thumbnail(row.cover_path)
                if thumb is not None:
                    cover.setIcon(QIcon(thumb))
                else:
                    cover.setText("—")
                self._table.setItem(i, 0, cover)
                self._table.setItem(i, 1, QTableWidgetItem(row.label))
                self._table.setItem(i, 2, QTableWidgetItem(row.artist_name or "—"))
                self._table.setItem(i, 3, QTableWidgetItem(str(row.track_count)))
                self._table.setItem(
                    i, 4, QTableWidgetItem(status_label.get(row.status, row.status))
                )
                self._table.setItem(i, 5, QTableWidgetItem(row.cover_source or "—"))
                size = (
                    f"{row.width}×{row.height}"
                    if row.width is not None and row.height is not None
                    else "—"
                )
                self._table.setItem(i, 6, QTableWidgetItem(size))
            ok = sum(1 for row in self._rows if row.status == "ok")
            missing = sum(1 for row in self._rows if row.status == "missing")
            low = sum(1 for row in self._rows if row.status == "low_res")
            self._status.setText(
                f"{len(self._rows)} album(s) · {ok} OK · {low} low-res · {missing} missing"
            )
        finally:
            end_table_update(self._table, sorting=sorting)
        if self._rows:
            self._table.selectRow(0)
        else:
            self._clear_cover()

    def _show_selected_cover(self) -> None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        if len(rows) != 1:
            return
        row_index = next(iter(rows))
        if not 0 <= row_index < len(self._rows):
            return
        row = self._rows[row_index]
        self._cover_title.setText(row.label)
        path = Path(row.cover_path) if row.cover_path else None
        if path is None or not path.is_file():
            self._cover_image.setPixmap(QPixmap())
            self._cover_image.setText("No cover")
            self._cover_meta.setText(row.artist_name or "")
            self._full_cover = None
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._cover_image.setPixmap(QPixmap())
            self._cover_image.setText("Invalid image")
            self._cover_meta.setText(str(path))
            self._full_cover = None
            return
        self._cover_image.setText("")
        source = row.cover_source or "cache"
        size = f"{row.width}×{row.height}" if row.width and row.height else ""
        self._cover_meta.setText(" · ".join(part for part in (source, size, path.name) if part))
        self._set_scaled_cover(pixmap)

    def _set_scaled_cover(self, pixmap: QPixmap) -> None:
        size = self._cover_image.size()
        if size.width() < 40 or size.height() < 40:
            size = self._cover_image.minimumSize()
        scaled = pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cover_image.setPixmap(scaled)
        self._full_cover = pixmap

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt
        super().resizeEvent(event)
        if self._full_cover is not None and not self._full_cover.isNull():
            self._set_scaled_cover(self._full_cover)

    def _clear_cover(self) -> None:
        self._cover_title.setText("Cover")
        self._cover_image.setPixmap(QPixmap())
        self._cover_image.setText("Select an album")
        self._cover_meta.setText("")
        self._full_cover = None


def _thumbnail(path: str | None) -> QPixmap | None:
    """Decode a small preview. The preview pane loads the full album image."""
    if not path or not Path(path).is_file():
        return None
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        size.scale(_THUMB, _THUMB, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(size)
    image = reader.read()
    if image.isNull():
        return None
    return QPixmap.fromImage(image)

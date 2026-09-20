"""Archive selection must follow displayed rows after sorting."""

from datetime import datetime
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

from vaultseek.gui.views.albums_page import AlbumsPage
from vaultseek.gui.views.library_page import LibraryPage
from vaultseek.models.entities.track import LibraryZone, Track


def test_library_archive_selection_after_sort(qtbot, container):
    page = LibraryPage(container)
    qtbot.addWidget(page)
    tracks = [
        Track(
            id=uuid4(),
            library_id=uuid4(),
            zone=LibraryZone.LIBRARY,
            file_path=f"C:/music/{title}.flac",
            file_name=f"{title}.flac",
            file_size=1,
            file_modified=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            title=title,
        )
        for title in ("Zulu", "Alpha")
    ]
    page._fill_table(tracks)
    page._table.sortItems(0, Qt.SortOrder.AscendingOrder)
    page._table.selectRow(0)
    assert page._selected_track_ids() == [tracks[1].id]
    assert page._selected_path() == tracks[1].file_path
    assert page._table.item(0, 2).text() == "Alpha.flac"


def test_album_archive_selection_after_sort_and_missing_rows(qtbot, container):
    page = AlbumsPage(container)
    qtbot.addWidget(page)
    ids = [uuid4(), uuid4()]
    page._table.setSortingEnabled(False)
    page._table.setRowCount(2)
    for row, title in enumerate(("Zulu", "Alpha")):
        item = QTableWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, str(ids[row]))
        page._table.setItem(row, 0, item)
    page._table.setSortingEnabled(True)
    page._table.sortItems(0, Qt.SortOrder.AscendingOrder)
    page._table.selectRow(0)
    assert page._selected_album_ids() == [ids[1]]
    page._tracks.setSortingEnabled(False)
    page._tracks.setRowCount(2)
    present = QTableWidgetItem("Zulu")
    present.setData(Qt.ItemDataRole.UserRole + 1, str(ids[0]))
    page._tracks.setItem(0, 0, present)
    page._tracks.setItem(1, 0, QTableWidgetItem("Missing"))
    page._tracks.setSortingEnabled(True)
    page._tracks.sortItems(0, Qt.SortOrder.AscendingOrder)
    page._tracks.selectAll()
    assert page._selected_track_ids() == [ids[0]]


def test_album_delete_cancel_does_not_call_service(qtbot, container, monkeypatch):
    from unittest.mock import Mock

    from PySide6.QtWidgets import QMessageBox

    page = AlbumsPage(container)
    qtbot.addWidget(page)
    page._library_id = uuid4()
    monkeypatch.setattr(page, "_selected_album_ids", lambda: [uuid4()])
    deletion = Mock()
    monkeypatch.setattr(container.album_deletion, "delete", deletion)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    page._delete_selected_albums()
    deletion.assert_not_called()

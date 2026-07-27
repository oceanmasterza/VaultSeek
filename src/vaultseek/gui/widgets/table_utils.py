"""Shared QTableWidget setup for browse / list pages."""

from __future__ import annotations

from PySide6.QtWidgets import QHeaderView, QTableWidget


def configure_data_table(table: QTableWidget, *, stretch_last: bool = True) -> None:
    """Sortable table with hidden row gutter and visible column-resize edges.

    Call once after creating the table. While filling rows, wrap the update in
    :func:`begin_table_update` / :func:`end_table_update` so sorting does not
    fight inserts.
    """
    table.setSortingEnabled(True)
    table.setAlternatingRowColors(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(28)
    header = table.horizontalHeader()
    header.setSectionsClickable(True)
    header.setSortIndicatorShown(True)
    header.setHighlightSections(False)
    header.setStretchLastSection(stretch_last)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    if stretch_last and table.columnCount() > 0:
        # Keep last column flexible while earlier columns stay user-resizable.
        header.setSectionResizeMode(table.columnCount() - 1, QHeaderView.ResizeMode.Stretch)


def begin_table_update(table: QTableWidget) -> bool:
    """Disable sorting for a bulk row rebuild. Returns prior enabled state."""
    was = table.isSortingEnabled()
    table.setSortingEnabled(False)
    return was


def end_table_update(table: QTableWidget, *, sorting: bool = True) -> None:
    """Re-enable sorting after :func:`begin_table_update`."""
    table.setSortingEnabled(sorting)

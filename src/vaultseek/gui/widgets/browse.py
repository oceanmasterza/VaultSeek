"""Shared helpers for browse pages (folder tree, track table fill)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
)

from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.library_quality import AlbumHealth, TrackHealth

# Stylesheets force QWidget color and ignore setForeground — paint via delegate
# and tint backgrounds so traffic lights stay visible on dark/light themes.
_HEALTH_ROLE = int(Qt.ItemDataRole.UserRole) + 40

# Green = OK; orange = quality gap OR missing/incomplete (user wants missing in orange).
_COLOR_OK = QColor(120, 200, 140)
_COLOR_QUALITY = QColor(255, 170, 60)
_COLOR_MISSING = QColor(255, 170, 60)  # same orange as quality gap
_COLOR_UNKNOWN = QColor(160, 160, 160)

_BG_OK = QColor(40, 90, 55, 55)
_BG_QUALITY = QColor(140, 90, 20, 70)
_BG_MISSING = QColor(140, 90, 20, 70)  # orange tint for missing too
_BG_UNKNOWN = QColor(80, 80, 80, 40)


def brush_for_track_health(health: TrackHealth) -> QBrush:
    if health is TrackHealth.OK:
        return QBrush(_COLOR_OK)
    if health is TrackHealth.QUALITY_GAP:
        return QBrush(_COLOR_QUALITY)
    if health is TrackHealth.MISSING:
        return QBrush(_COLOR_MISSING)
    return QBrush(_COLOR_UNKNOWN)


def brush_for_album_health(health: AlbumHealth) -> QBrush:
    if health is AlbumHealth.COMPLETE_OK:
        return QBrush(_COLOR_OK)
    if health is AlbumHealth.COMPLETE_QUALITY_GAP:
        return QBrush(_COLOR_QUALITY)
    if health is AlbumHealth.INCOMPLETE:
        return QBrush(_COLOR_MISSING)
    return QBrush(_COLOR_UNKNOWN)


def _bg_for_track_health(health: TrackHealth) -> QBrush:
    if health is TrackHealth.OK:
        return QBrush(_BG_OK)
    if health is TrackHealth.QUALITY_GAP:
        return QBrush(_BG_QUALITY)
    if health is TrackHealth.MISSING:
        return QBrush(_BG_MISSING)
    return QBrush(_BG_UNKNOWN)


def _bg_for_album_health(health: AlbumHealth) -> QBrush:
    if health is AlbumHealth.COMPLETE_OK:
        return QBrush(_BG_OK)
    if health is AlbumHealth.COMPLETE_QUALITY_GAP:
        return QBrush(_BG_QUALITY)
    if health is AlbumHealth.INCOMPLETE:
        return QBrush(_BG_MISSING)
    return QBrush(_BG_UNKNOWN)


def _fg_color_for_health_value(value: str | None) -> QColor | None:
    if not value:
        return None
    mapping = {
        TrackHealth.OK.value: _COLOR_OK,
        TrackHealth.QUALITY_GAP.value: _COLOR_QUALITY,
        TrackHealth.MISSING.value: _COLOR_MISSING,
        AlbumHealth.COMPLETE_OK.value: _COLOR_OK,
        AlbumHealth.COMPLETE_QUALITY_GAP.value: _COLOR_QUALITY,
        AlbumHealth.INCOMPLETE.value: _COLOR_MISSING,
        AlbumHealth.UNKNOWN.value: _COLOR_UNKNOWN,
    }
    return mapping.get(value)


def apply_track_health_style(item: QTableWidgetItem, health: TrackHealth) -> None:
    item.setData(_HEALTH_ROLE, health.value)
    item.setForeground(brush_for_track_health(health))
    item.setBackground(_bg_for_track_health(health))


def apply_album_health_style(item: QTableWidgetItem, health: AlbumHealth) -> None:
    item.setData(_HEALTH_ROLE, health.value)
    item.setForeground(brush_for_album_health(health))
    item.setBackground(_bg_for_album_health(health))


class HealthColorDelegate(QStyledItemDelegate):
    """Paint item text with traffic-light colors even when stylesheets override palette."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,  # noqa: ANN001 — Qt model index
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        health = index.data(_HEALTH_ROLE)
        color = _fg_color_for_health_value(str(health) if health is not None else None)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)

        style = opt.widget.style() if opt.widget is not None else None
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(bg, QBrush) and bg.style() != Qt.BrushStyle.NoBrush and not selected:
            painter.fillRect(opt.rect, bg)
        elif style is not None:
            style.drawPrimitive(
                QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, opt.widget
            )
        elif selected:
            painter.fillRect(opt.rect, opt.palette.highlight())

        text = opt.text
        if text:
            painter.save()
            if selected:
                painter.setPen(opt.palette.highlightedText().color())
            elif color is not None:
                painter.setPen(color)
            else:
                painter.setPen(opt.palette.text().color())
            text_rect = opt.rect.adjusted(6, 0, -6, 0)
            painter.drawText(text_rect, int(opt.displayAlignment), text)
            painter.restore()

    def install_on(self, table: QTableWidget) -> None:
        table.setItemDelegate(self)


def fill_track_table(
    table: QTableWidget,
    tracks: Sequence[Track],
    *,
    columns: Sequence[str] = ("Title", "Artist", "Album", "Zone", "File", "Confidence"),
    row_health: Sequence[TrackHealth] | None = None,
) -> list[str]:
    """Populate a track table; returns file paths aligned with row index."""
    labels = list(columns)
    if table.columnCount() != len(labels):
        table.setColumnCount(len(labels))
        table.setHorizontalHeaderLabels(labels)
    table.setRowCount(len(tracks))
    paths: list[str] = []
    for row, track in enumerate(tracks):
        paths.append(track.file_path)
        values = {
            "Title": track.title or "(untitled)",
            "Zone": track.zone.value,
            "File": track.file_name or track.file_path,
            "Confidence": (
                f"{track.overall_confidence:.0%}"
                if track.overall_confidence is not None
                else "—"
            ),
            "Quality": str(track.quality_score) if track.quality_score is not None else "—",
            "Artist": "—",
            "Album": "—",
        }
        health = row_health[row] if row_health is not None and row < len(row_health) else None
        for col, label in enumerate(labels):
            item = QTableWidgetItem(values.get(label, "—"))
            if label in {"Confidence", "Quality"}:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            if health is not None:
                apply_track_health_style(item, health)
            table.setItem(row, col, item)
    return paths


def zone_roots(library: Library) -> dict[str, Path]:
    return {
        LibraryZone.INCOMING.value: Path(library.incoming_path),
        LibraryZone.STAGING.value: Path(library.staging_path),
        LibraryZone.LIBRARY.value: Path(library.library_path),
        LibraryZone.ARCHIVE.value: Path(library.archive_path),
    }


def build_folder_tree(
    tree: QTreeWidget,
    library: Library,
    path_rows: Sequence[tuple[str, str]],
) -> None:
    """Populate ``tree`` with zone roots and relative folder segments from DB paths."""
    tree.clear()
    all_item = QTreeWidgetItem(["All folders"])
    all_item.setData(0, Qt.ItemDataRole.UserRole, {"kind": "all"})
    tree.addTopLevelItem(all_item)

    roots = zone_roots(library)
    forest: dict[str, dict] = {zone: {} for zone in roots}

    for zone, file_path in path_rows:
        root = roots.get(zone)
        if root is None:
            continue
        try:
            relative = Path(file_path).resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            relative = _relative_fallback(file_path, str(root))
            if relative is None:
                continue
        parts = relative.parts[:-1]
        node = forest[zone]
        for part in parts:
            node = node.setdefault(part, {})

    for zone, label in (
        (LibraryZone.INCOMING.value, "Incoming"),
        (LibraryZone.STAGING.value, "Staging"),
        (LibraryZone.LIBRARY.value, "Library"),
        (LibraryZone.ARCHIVE.value, "Archive"),
    ):
        zone_item = QTreeWidgetItem([label])
        zone_item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {"kind": "zone", "zone": zone, "prefix": str(roots[zone])},
        )
        _add_dict_children(zone_item, forest.get(zone, {}), str(roots[zone]), zone)
        tree.addTopLevelItem(zone_item)
        zone_item.setExpanded(zone == LibraryZone.LIBRARY.value)

    all_item.setExpanded(True)
    tree.setCurrentItem(all_item)


def _add_dict_children(
    parent: QTreeWidgetItem,
    node: Mapping[str, dict],
    prefix: str,
    zone: str,
) -> None:
    for name in sorted(node.keys(), key=str.casefold):
        child_prefix = str(Path(prefix) / name)
        item = QTreeWidgetItem([name])
        item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {"kind": "folder", "zone": zone, "prefix": child_prefix},
        )
        _add_dict_children(item, node[name], child_prefix, zone)
        parent.addChild(item)


def _relative_fallback(file_path: str, root: str) -> PureWindowsPath | None:
    left = file_path.replace("/", "\\").rstrip("\\").casefold()
    right = root.replace("/", "\\").rstrip("\\").casefold()
    if not left.startswith(right + "\\") and left != right:
        return None
    rest = file_path.replace("/", "\\")[len(root.rstrip("/\\")) :].lstrip("\\/")
    if not rest:
        return PureWindowsPath(".")
    return PureWindowsPath(rest)

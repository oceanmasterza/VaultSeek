"""Shared helpers for browse pages (folder tree, track table fill)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem

from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone, Track


def fill_track_table(
    table: QTableWidget,
    tracks: Sequence[Track],
    *,
    columns: Sequence[str] = ("Title", "Artist", "Album", "Zone", "File", "Confidence"),
) -> list[str]:
    """Populate a track table; returns file paths aligned with row index."""
    # Artist/album names are not on Track — show ids-less placeholders; callers
    # that need names should pass preformatted rows. Here we use title/zone/file.
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
        for col, label in enumerate(labels):
            item = QTableWidgetItem(values.get(label, "—"))
            if label in {"Confidence", "Quality"}:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
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
    # zone -> nested dict of segment -> ...
    forest: dict[str, dict] = {zone: {} for zone in roots}

    for zone, file_path in path_rows:
        root = roots.get(zone)
        if root is None:
            continue
        try:
            relative = Path(file_path).resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            # Fall back to string prefix match (paths may be on different drives / casing)
            relative = _relative_fallback(file_path, str(root))
            if relative is None:
                continue
        parts = relative.parts[:-1]  # drop filename
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

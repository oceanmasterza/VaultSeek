"""Discogs browse helpers — cover thumbnails and album title rendering."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget

_LINK = QColor("#6cb6ff")
_MUTED = QColor("#9a9a9a")
_SUBTITLE_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_RELEASE_ID_ROLE = Qt.ItemDataRole.UserRole


class AlbumTitleDelegate(QStyledItemDelegate):
    """Two-line album cell: blue title + muted format/type subtitle (Discogs-style)."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        painter.setClipRect(option.rect)
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        subtitle = str(index.data(_SUBTITLE_ROLE) or "")

        rect = option.rect.adjusted(6, 4, -6, -4)
        title_font = painter.font()
        title_font.setBold(True)
        painter.setFont(title_font)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(_LINK)

        if subtitle:
            title_rect = rect.adjusted(0, 0, 0, -rect.height() // 2)
            sub_rect = rect.adjusted(0, rect.height() // 2, 0, 0)
        else:
            title_rect = rect
            sub_rect = rect

        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            title,
        )
        if subtitle:
            sub_font = painter.font()
            sub_font.setBold(False)
            sub_font.setPointSize(max(sub_font.pointSize() - 1, 8))
            painter.setFont(sub_font)
            painter.setPen(option.palette.highlightedText().color() if selected else _MUTED)
            painter.drawText(
                sub_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                subtitle,
            )
        painter.restore()

    def sizeHint(  # noqa: N802
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        base = super().sizeHint(option, index)
        return QSize(base.width(), max(base.height(), 48))


class DiscogsThumbLoader:
    """Load Discogs cover URLs into a table's first column."""

    _CACHE: dict[str, QPixmap] = {}

    def __init__(self) -> None:
        self._nam = QNetworkAccessManager()
        self._generation = 0

    def reset(self) -> None:
        """Invalidate in-flight loads (e.g. when artist changes)."""
        self._generation += 1

    def load_row(self, table: QTableWidget, row: int, url: str, release_id: int) -> None:
        if not url:
            return
        cached = self._CACHE.get(url)
        if cached is not None:
            self._apply_pixmap(table, row, release_id, cached)
            return
        generation = self._generation
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(15_000)
        reply = self._nam.get(request)

        def finished() -> None:
            if generation != self._generation:
                reply.deleteLater()
                return
            try:
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    return
                data = reply.readAll()
                pixmap = QPixmap()
                if not pixmap.loadFromData(data):
                    return
                scaled = pixmap.scaled(
                    40,
                    40,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._CACHE[url] = scaled
                self._apply_pixmap(table, row, release_id, scaled)
            finally:
                reply.deleteLater()

        reply.finished.connect(finished)

    @staticmethod
    def _apply_pixmap(table: QTableWidget, row: int, release_id: int, pixmap: QPixmap) -> None:
        item = table.item(row, 0)
        if item is None:
            return
        if item.data(_RELEASE_ID_ROLE) != release_id:
            return
        item.setData(Qt.ItemDataRole.DecorationRole, pixmap)


def release_subtitle(*, kind: str, format_text: str, role: str) -> str:
    """Muted second line under the album title."""
    parts: list[str] = []
    kind_clean = kind.strip()
    if kind_clean and kind_clean.casefold() not in {"release", ""}:
        parts.append(kind_clean.title())
    if format_text.strip():
        parts.append(format_text.strip())
    if role.strip() and role.casefold() not in {"main", "primary", ""}:
        parts.append(role.strip())
    return " · ".join(parts)


def release_tooltip(
    *,
    artist: str,
    format_text: str,
    kind: str,
    role: str,
    secondary: str,
) -> str:
    lines = [artist]
    detail = release_subtitle(kind=kind, format_text=format_text, role=role)
    if detail:
        lines.append(detail)
    if secondary:
        lines.append(secondary)
    return "\n".join(lines)

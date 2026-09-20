"""Wrapping layout for toolbar controls that must stay fully visible."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    """Left-to-right flow that wraps instead of squeezing or clipping children.

    Signature matches ``FlowLayout(parent=None, margin=0, spacing=6)``.
    Expanding widgets (search fields, combos) absorb leftover space on a line.
    Line breaks use size hints, so ``heightForWidth`` stays stable.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items: list[QLayoutItem] = []

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 — Qt API
        self._items.append(item)
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 — Qt API
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 — Qt API
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 — Qt API
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 — Qt API
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 — Qt API
        margins = self.contentsMargins()
        inner = max(0, width - margins.left() - margins.right())
        return (
            self._do_layout(QRect(0, 0, inner, 0), test_only=True)
            + margins.top()
            + margins.bottom()
        )

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 — Qt API
        super().setGeometry(rect)
        self._do_layout(self.contentsRect(), test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt API
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 — Qt API
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        spacing = max(self.spacing(), 0)
        x = rect.x()
        y = rect.y()
        line_height = 0
        line: list[tuple[QLayoutItem, QSize]] = []

        def commit(items: list[tuple[QLayoutItem, QSize]], line_y: int, line_h: int) -> None:
            if test_only or not items:
                return
            widths = [hint.width() for _, hint in items]
            used = sum(widths) + spacing * max(0, len(items) - 1)
            extra = max(0, rect.width() - used)
            growable = [
                index for index, (item, _) in enumerate(items) if _expands_horizontally(item)
            ]
            if extra and growable:
                share, remainder = divmod(extra, len(growable))
                for index in growable:
                    widths[index] += share
                    if remainder:
                        widths[index] += 1
                        remainder -= 1
            cursor = rect.x()
            for (item, hint), width in zip(items, widths, strict=True):
                item.setGeometry(
                    QRect(QPoint(cursor, line_y), QSize(width, max(line_h, hint.height())))
                )
                cursor += width + spacing

        for item in self._items:
            hint = item.sizeHint().expandedTo(item.minimumSize())
            next_x = x + hint.width() + spacing
            if next_x - spacing > rect.right() and line_height > 0:
                commit(line, y, line_height)
                line = []
                x = rect.x()
                y = y + line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            line.append((item, hint))
            x = next_x
            line_height = max(line_height, hint.height())
        commit(line, y, line_height)
        if not self._items:
            return 0
        return y + line_height - rect.y()


def _expands_horizontally(item: QLayoutItem) -> bool:
    widget = item.widget()
    if widget is None:
        return False
    policy = widget.sizePolicy().horizontalPolicy()
    return policy in (
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.MinimumExpanding,
    )

"""Wrapping pipeline progress strip for the Dashboard."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vaultseek.gui.widgets.flow_layout import FlowLayout
from vaultseek.services.dashboard import PIPELINE_STAGES, PipelineStageStat

# Pipeline stage key → main-window nav key (click-through from Dashboard).
STAGE_NAV_KEYS: dict[str, str] = {
    "scan": "jobs",
    "hash": "jobs",
    "fingerprint": "jobs",
    "identify": "jobs",
    "review": "review",
    "duplicates": "duplicates",
    "rules": "settings",
    "organize": "jobs",
    "artwork": "artwork",
    "acquire": "acquisition",
    "sync": "settings",
}


def _idle_stages() -> tuple[PipelineStageStat, ...]:
    """Named stages with zero library/wishlist counts so the diagram never collapses."""
    return tuple(
        PipelineStageStat(
            key=key,
            label=label,
            backlog=0,
            running=0,
            is_active=False,
            is_bottleneck=False,
        )
        for key, label, _job_type in PIPELINE_STAGES
    )


class _StageCard(QFrame):
    clicked = Signal(str)

    def __init__(self, stage_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stage_key = stage_key
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._stage_key)
        super().mousePressEvent(event)


class PipelineFlowWidget(QWidget):
    """Beets/Picard-style processing journey that wraps instead of collapsing."""

    stage_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("processingPipeline")
        self._flow = FlowLayout(self, margin=0, spacing=6)
        self._syncing = False
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.set_stages(())

    def hasHeightForWidth(self) -> bool:  # noqa: N802 — Qt API
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 — Qt API
        return int(self._flow.heightForWidth(width))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        self._sync_height()

    def set_stages(self, stages: tuple[PipelineStageStat, ...]) -> None:
        shown = stages if stages else _idle_stages()
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        for index, stage in enumerate(shown):
            if index:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setProperty("muted", True)
                arrow.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                self._flow.addWidget(arrow)

            card = _StageCard(stage.key)
            card.setProperty("pipelineStage", True)
            if stage.is_bottleneck:
                card.setProperty("bottleneck", True)
            elif stage.is_active:
                card.setProperty("activeStage", True)
            card.setToolTip(
                f"{stage.label}: {stage.backlog} waiting"
                + (f", {stage.running} running" if stage.running else "")
            )
            card.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(8, 8, 8, 8)
            inner.setSpacing(4)
            title = QLabel(stage.label)
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setProperty("stageTitle", True)
            count = QLabel(str(stage.backlog))
            count.setAlignment(Qt.AlignmentFlag.AlignCenter)
            count.setProperty("stageCount", True)
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setMaximum(max(stage.backlog, 1))
            bar.setValue(stage.running if stage.backlog else 0)
            if stage.backlog == 0:
                bar.setMaximum(1)
                bar.setValue(0)
            elif stage.running:
                bar.setMaximum(stage.backlog)
                bar.setValue(min(stage.running, stage.backlog))
            else:
                bar.setMaximum(max(stage.backlog, 1))
                bar.setValue(0)
            status = QLabel("running" if stage.running else ("queued" if stage.backlog else "idle"))
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status.setProperty("muted", True)
            for child in (title, count, bar, status):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                inner.addWidget(child)
            card.setMinimumWidth(max(88, title.sizeHint().width() + 16))
            card.clicked.connect(self.stage_clicked.emit)
            self._flow.addWidget(card)

        for card in self.findChildren(_StageCard):
            card.style().unpolish(card)
            card.style().polish(card)
        self.updateGeometry()
        self._sync_height()

    def _sync_height(self) -> None:
        """Grow to the wrapped height so later rows are not clipped at 0."""
        if self._syncing:
            return
        width = self.width()
        if width < 40:
            return
        height = self.heightForWidth(width)
        if height <= 0 or height == self.minimumHeight():
            return
        self._syncing = True
        try:
            self.setMinimumHeight(height)
            self.updateGeometry()
        finally:
            self._syncing = False

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt API
        width = self.width() if self.width() > 40 else 720
        return QSize(width, max(self.heightForWidth(width), 1))

"""Horizontal pipeline progress strip for the Dashboard."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from vaultseek.services.dashboard import PipelineStageStat


class PipelineFlowWidget(QWidget):
    """Beets/Picard-style left-to-right processing journey."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(4)
        self._stage_widgets: list[QFrame] = []

    def set_stages(self, stages: tuple[PipelineStageStat, ...]) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._stage_widgets.clear()

        for index, stage in enumerate(stages):
            if index:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setProperty("muted", True)
                self._row.addWidget(arrow)

            card = QFrame()
            card.setProperty("pipelineStage", True)
            if stage.is_bottleneck:
                card.setProperty("bottleneck", True)
            elif stage.is_active:
                card.setProperty("activeStage", True)
            card.setToolTip(
                f"{stage.label}: {stage.backlog} waiting"
                + (f", {stage.running} running" if stage.running else "")
            )
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
            status = QLabel(
                "running" if stage.running else ("queued" if stage.backlog else "idle")
            )
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status.setProperty("muted", True)
            inner.addWidget(title)
            inner.addWidget(count)
            inner.addWidget(bar)
            inner.addWidget(status)
            self._row.addWidget(card, stretch=1)
            self._stage_widgets.append(card)

        # Force style re-polish for dynamic properties.
        for card in self._stage_widgets:
            card.style().unpolish(card)
            card.style().polish(card)

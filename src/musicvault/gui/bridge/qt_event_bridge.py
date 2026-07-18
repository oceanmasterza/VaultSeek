"""Marshals domain events from worker threads onto the Qt main thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from musicvault.core.event_bus import EventBus
from musicvault.services.events import ReviewItemAddedEvent


class QtEventBridge(QObject):
    """Subscribes to the process-wide :class:`EventBus` and re-emits
    selected events as Qt signals so views can refresh without polling
    every domain change.

    Signal emission from a worker thread uses Qt's auto-connection so
    slots on the main window run on the GUI thread.
    """

    review_item_added = Signal(object)

    def __init__(self, event_bus: EventBus, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bus = event_bus
        self._bus.subscribe(ReviewItemAddedEvent, self._on_review_item_added)

    def close(self) -> None:
        """Unsubscribe handlers. Safe to call more than once."""
        self._bus.unsubscribe(ReviewItemAddedEvent, self._on_review_item_added)

    def _on_review_item_added(self, event: ReviewItemAddedEvent) -> None:
        self.review_item_added.emit(event)

"""Thread-safe publish/subscribe event bus.

Background workers (running on worker threads or process pools) publish
:class:`DomainEvent` instances here. Subscribers — most importantly the
Qt event bridge in ``vaultseek.gui.bridge`` (added in Phase 14) — receive
them synchronously on the publishing thread and are responsible for
marshaling onto the Qt main thread themselves (e.g. via a queued signal
emission).

This bus has no dependency on Qt so it can be constructed, injected, and
unit tested without a running ``QApplication``. See
docs/architecture/12-pipeline-engine-v3.md for the surrounding design.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from loguru import logger

EventHandler = Callable[[Any], None]


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base class for all events published on the :class:`EventBus`."""

    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


TEvent = TypeVar("TEvent", bound=DomainEvent)


class EventBus:
    """In-process, thread-safe publish/subscribe dispatcher.

    Subscriptions match the *exact* event type — subscribing to
    :class:`DomainEvent` itself does not receive subclass events. This
    keeps handler signatures precise and avoids accidental catch-alls.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: dict[type[DomainEvent], list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: type[TEvent], handler: Callable[[TEvent], None]) -> None:
        """Register ``handler`` to be invoked whenever ``event_type`` is published."""
        with self._lock:
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type[TEvent], handler: Callable[[TEvent], None]) -> None:
        """Remove a previously registered handler. No-op if not registered."""
        with self._lock:
            handlers = self._handlers.get(event_type)
            if handlers is not None and handler in handlers:
                handlers.remove(handler)

    def publish(self, event: DomainEvent) -> None:
        """Synchronously invoke all handlers registered for ``type(event)``.

        Handlers run on the publishing thread. A handler that raises does
        not prevent other handlers from running — the exception is logged
        and swallowed so one broken subscriber cannot break the pipeline.
        """
        with self._lock:
            handlers = list(self._handlers.get(type(event), ()))

        for handler in handlers:
            try:
                handler(event)
            except Exception:  # noqa: BLE001 - isolate subscriber failures from the publisher
                logger.exception(
                    "Event handler {} raised while handling {}", handler, type(event).__name__
                )

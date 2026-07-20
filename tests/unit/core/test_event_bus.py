"""Unit tests for vaultseek.core.event_bus."""

from __future__ import annotations

from dataclasses import dataclass

from vaultseek.core.event_bus import DomainEvent, EventBus


@dataclass(frozen=True, kw_only=True)
class _SampleEvent(DomainEvent):
    message: str


@dataclass(frozen=True, kw_only=True)
class _OtherEvent(DomainEvent):
    payload: int


def test_publish_invokes_subscribed_handler() -> None:
    bus = EventBus()
    received: list[_SampleEvent] = []
    bus.subscribe(_SampleEvent, received.append)

    bus.publish(_SampleEvent(message="hello"))

    assert len(received) == 1
    assert received[0].message == "hello"


def test_publish_does_not_invoke_handlers_for_other_event_types() -> None:
    bus = EventBus()
    received: list[_SampleEvent] = []
    bus.subscribe(_SampleEvent, received.append)

    bus.publish(_OtherEvent(payload=1))

    assert received == []


def test_multiple_subscribers_all_receive_event() -> None:
    bus = EventBus()
    first: list[_SampleEvent] = []
    second: list[_SampleEvent] = []
    bus.subscribe(_SampleEvent, first.append)
    bus.subscribe(_SampleEvent, second.append)

    bus.publish(_SampleEvent(message="hi"))

    assert len(first) == 1
    assert len(second) == 1


def test_unsubscribe_stops_further_delivery() -> None:
    bus = EventBus()
    received: list[_SampleEvent] = []
    bus.subscribe(_SampleEvent, received.append)
    bus.unsubscribe(_SampleEvent, received.append)

    bus.publish(_SampleEvent(message="hello"))

    assert received == []


def test_unsubscribe_unknown_handler_does_not_raise() -> None:
    bus = EventBus()

    bus.unsubscribe(_SampleEvent, lambda _event: None)


def test_handler_exception_does_not_prevent_other_handlers() -> None:
    bus = EventBus()
    received: list[_SampleEvent] = []

    def _raises(_event: _SampleEvent) -> None:
        raise RuntimeError("boom")

    bus.subscribe(_SampleEvent, _raises)
    bus.subscribe(_SampleEvent, received.append)

    bus.publish(_SampleEvent(message="hello"))

    assert len(received) == 1


def test_event_records_occurred_at_timestamp() -> None:
    event = _SampleEvent(message="hello")

    assert event.occurred_at is not None

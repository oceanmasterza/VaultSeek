"""Tests for Soulseek search flood-protection gate."""

from __future__ import annotations

import time

from vaultseek.plugins.builtin.nicotine_plus.search_rate_gate import SearchRateGate


def test_try_acquire_is_non_blocking() -> None:
    gate = SearchRateGate(min_interval_seconds=30.0, max_per_minute=8)
    assert gate.try_acquire() is None
    delay = gate.try_acquire()
    assert delay is not None
    assert delay > 1.0


def test_search_rate_gate_spaces_consecutive_searches_when_blocking() -> None:
    gate = SearchRateGate(min_interval_seconds=0.15, max_per_minute=30)
    assert gate.acquire() == 0.0
    started = time.monotonic()
    waited = gate.acquire()
    elapsed = time.monotonic() - started
    assert waited >= 0.10
    assert elapsed >= 0.10


def test_search_rate_gate_minute_cap_requires_wait() -> None:
    gate = SearchRateGate(min_interval_seconds=0.0, max_per_minute=2)
    now = time.monotonic()
    with gate._lock:  # noqa: SLF001 — assert delay math for the rolling window
        gate._timestamps.append(now - 10.0)
        gate._timestamps.append(now - 5.0)
        delay = gate._required_delay(now)
    assert delay >= 49.0
    assert delay <= 55.0


def test_search_rate_gate_configure_updates_limits() -> None:
    gate = SearchRateGate(min_interval_seconds=5.0, max_per_minute=8)
    gate.configure(min_interval_seconds=7.5, max_per_minute=4)
    assert gate.min_interval_seconds == 7.5
    assert gate.max_per_minute == 4

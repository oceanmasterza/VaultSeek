"""Tests for GUI datetime formatting."""

from __future__ import annotations

from datetime import UTC, datetime

from vaultseek.gui.datetime_format import format_local_datetime


def test_format_local_datetime_converts_from_utc() -> None:
    value = datetime(2026, 7, 22, 10, 30, 0, tzinfo=UTC)
    formatted = format_local_datetime(value)
    local = value.astimezone()
    assert formatted == local.strftime("%Y-%m-%d %H:%M:%S")


def test_format_local_datetime_handles_naive_as_utc() -> None:
    value = datetime(2026, 7, 22, 10, 30, 0)
    assert format_local_datetime(value) == format_local_datetime(value.replace(tzinfo=UTC))


def test_format_local_datetime_none() -> None:
    assert format_local_datetime(None) == "—"

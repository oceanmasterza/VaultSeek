"""Display helpers for timezone-aware datetimes in the GUI."""

from __future__ import annotations

from datetime import UTC, datetime


def format_local_datetime(value: datetime | None) -> str:
    """Format ``value`` in the user's local timezone for table display."""
    if value is None:
        return "—"
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone().strftime("%Y-%m-%d %H:%M:%S")

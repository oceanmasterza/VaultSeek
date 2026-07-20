"""MediaServerState entity — one configured media-server connection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MediaServerState:
    """Persisted row from ``media_server_state``."""

    id: UUID
    library_id: UUID
    plugin_id: str
    created_at: datetime | None = None
    server_url: str | None = None
    db_path: str | None = None
    config: dict[str, Any] | None = None
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None

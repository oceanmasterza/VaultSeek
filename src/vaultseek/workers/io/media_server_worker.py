"""MediaServerWorker — runs `sync_media_server` jobs.

I/O-bound (Tier 2). Loads configured ``media_server_state`` rows for the
job's library, connects the matching plugin, triggers a rescan, records
sync status, and disconnects. Payload may optionally restrict to one
``plugin_id``; otherwise every configured server for the library is synced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from vaultseek.db.repositories.media_server_repo import MediaServerStateRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.models.entities.job import Job
from vaultseek.models.entities.media_server_state import MediaServerState
from vaultseek.models.interfaces.media_server import (
    LibrarySummary,
    MediaServerConfig,
    MediaServerPlugin,
)
from vaultseek.services.job_queue_service import JobQueueService


class MediaServerWorker:
    def __init__(
        self,
        media_server_repo: MediaServerStateRepository,
        track_repo: TrackRepository,
        plugins: list[MediaServerPlugin],
        job_queue: JobQueueService,
    ) -> None:
        self._states = media_server_repo
        self._tracks = track_repo
        self._plugins = {plugin.plugin_id: plugin for plugin in plugins}
        self._job_queue = job_queue

    def execute(self, job: Job) -> None:
        plugin_filter = job.payload.get("plugin_id")
        states = self._states.list_by_library(job.library_id)
        if plugin_filter:
            states = [state for state in states if state.plugin_id == plugin_filter]
        if not states:
            # Nothing configured — succeed so the pipeline stays terminal-clean.
            self._job_queue.mark_completed(job.id)
            return

        track_counts = self._tracks.count_by_zone(job.library_id)
        summary = LibrarySummary(track_count=sum(track_counts.values()))
        now = datetime.now(UTC)
        failures: list[str] = []

        for state in states:
            ok = self._sync_one(state, summary, now)
            if not ok:
                failures.append(state.plugin_id)

        if failures:
            self._job_queue.mark_failed(
                job.id, f"Media server sync failed for: {', '.join(failures)}"
            )
            return
        self._job_queue.mark_completed(job.id)

    def _sync_one(
        self,
        state: MediaServerState,
        summary: LibrarySummary,
        now: datetime,
    ) -> bool:
        plugin = self._plugins.get(state.plugin_id)
        if plugin is None:
            logger.warning("No media-server plugin registered for id {}", state.plugin_id)
            self._states.update_sync_status(state.id, status="unknown_plugin", synced_at=now)
            return False

        config = _to_config(state)
        try:
            if not plugin.connect(config):
                self._states.update_sync_status(state.id, status="connect_failed", synced_at=now)
                return False
            if not plugin.trigger_rescan():
                self._states.update_sync_status(state.id, status="rescan_failed", synced_at=now)
                return False
            # Optional validation — warnings only, never fail the job.
            for issue in plugin.validate_library(summary):
                logger.info(
                    "Media server {} validation {}: {}",
                    state.plugin_id,
                    issue.severity,
                    issue.message,
                )
            self._states.update_sync_status(state.id, status="ok", synced_at=now)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("Media server sync crashed for {}", state.plugin_id)
            self._states.update_sync_status(state.id, status=f"error:{exc}", synced_at=now)
            return False
        finally:
            plugin.disconnect()


def _to_config(state: MediaServerState) -> MediaServerConfig:
    raw: dict[str, Any] = dict(state.config or {})
    return MediaServerConfig(
        library_id=state.library_id,
        plugin_id=state.plugin_id,
        server_url=state.server_url or "",
        db_path=state.db_path,
        username=str(raw.get("username", "")),
        password=str(raw.get("password", "")),
        token=str(raw.get("token", "")),
        extra={k: v for k, v in raw.items() if k not in {"username", "password", "token"}},
    )

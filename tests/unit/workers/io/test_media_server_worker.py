"""Unit tests for MediaServerWorker and Subsonic client helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid7

import pytest
import responses
from sqlalchemy import Engine

from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.media_server_repo import MediaServerStateRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.models.entities.job import Job, JobStatus, JobType
from vaultseek.models.entities.media_server_state import MediaServerState
from vaultseek.models.interfaces.media_server import (
    LibrarySummary,
    MediaServerConfig,
    ServerCapabilities,
    ValidationIssue,
)
from vaultseek.plugins.builtin.subsonic.client import SubsonicClient
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.workers.io.media_server_worker import MediaServerWorker

_NOW = datetime(2026, 7, 18, tzinfo=UTC)


class _StubPlugin:
    plugin_id = "navidrome"
    display_name = "Navidrome"

    def __init__(self, *, connect_ok: bool = True, rescan_ok: bool = True) -> None:
        self.connect_ok = connect_ok
        self.rescan_ok = rescan_ok
        self.connected = False
        self.rescanned = False
        self.disconnected = False

    @property
    def capabilities(self) -> ServerCapabilities:
        return ServerCapabilities()

    def connect(self, config: MediaServerConfig) -> bool:
        _ = config
        self.connected = self.connect_ok
        return self.connect_ok

    def test_connection(self) -> bool:
        return self.connected

    def disconnect(self) -> None:
        self.disconnected = True

    def trigger_rescan(self) -> bool:
        self.rescanned = self.rescan_ok
        return self.rescan_ok

    def get_server_stats(self) -> dict[str, Any]:
        return {}

    def validate_library(self, local_library: LibrarySummary) -> list[ValidationIssue]:
        _ = local_library
        return []


@pytest.fixture
def media_repo(engine: Engine) -> MediaServerStateRepository:
    return MediaServerStateRepository(engine)


@pytest.fixture
def worker(
    media_repo: MediaServerStateRepository,
    track_repo: TrackRepository,
    job_queue: JobQueueService,
) -> tuple[MediaServerWorker, _StubPlugin]:
    plugin = _StubPlugin()
    return MediaServerWorker(media_repo, track_repo, [plugin], job_queue), plugin


def test_worker_completes_when_no_servers_configured(
    worker: tuple[MediaServerWorker, _StubPlugin],
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
) -> None:
    media_worker, _ = worker
    job_id = job_queue.enqueue(JobType.SYNC_MEDIA_SERVER, library_id, {}, now=_NOW)
    job = job_repo.get(job_id)
    assert job is not None
    claimed = Job(
        id=job.id,
        library_id=job.library_id,
        job_type=job.job_type,
        status=JobStatus.RUNNING,
        payload=job.payload,
        created_at=job.created_at,
    )
    media_worker.execute(claimed)
    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]


def test_worker_triggers_rescan_and_records_status(
    worker: tuple[MediaServerWorker, _StubPlugin],
    media_repo: MediaServerStateRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
) -> None:
    media_worker, plugin = worker
    state_id = uuid7()
    media_repo.upsert(
        MediaServerState(
            id=state_id,
            library_id=library_id,
            plugin_id="navidrome",
            server_url="http://localhost:4533",
            config={"username": "u", "password": "p"},
        )
    )
    job_id = job_queue.enqueue(JobType.SYNC_MEDIA_SERVER, library_id, {}, now=_NOW)
    job = job_repo.get(job_id)
    assert job is not None
    media_worker.execute(
        Job(
            id=job.id,
            library_id=job.library_id,
            job_type=job.job_type,
            status=JobStatus.RUNNING,
            payload=job.payload,
            created_at=job.created_at,
        )
    )
    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    assert plugin.connected and plugin.rescanned and plugin.disconnected
    updated = media_repo.get(state_id)
    assert updated is not None
    assert updated.last_sync_status == "ok"


@responses.activate
def test_subsonic_client_ping_and_scan() -> None:
    base = "http://nav.example/"
    responses.add(
        responses.GET,
        f"{base}rest/ping.view",
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{base}rest/startScan.view",
        json={"subsonic-response": {"status": "ok"}},
        status=200,
    )
    client = SubsonicClient(base, "user", "secret")
    assert client.ping() is True
    assert client.start_scan() is True

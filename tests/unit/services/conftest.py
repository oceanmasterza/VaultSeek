"""Shared fixtures for service-layer tests.

Mirrors tests/unit/db/repositories/conftest.py — services are tested
against a real, schema-initialized SQLite database (through the real
repositories they wrap), not mocks, so a bad SQL statement in a
repository is caught here too.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, event, insert

from musicvault.core.config import PipelineConfig
from musicvault.core.event_bus import EventBus
from musicvault.db.repositories.file_identity_repo import FileIdentityRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.tables import libraries, metadata, tracks
from musicvault.db.uuid_utils import generate_uuid7, uuid_to_blob
from musicvault.db.writer import DatabaseWriter
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.review_queue_service import ReviewQueueService


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    db_path = tmp_path / "service_test.db"
    eng = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(eng, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def library_id(engine: Engine) -> UUID:
    lib_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(libraries).values(
                id=uuid_to_blob(lib_id),
                name="Test Library",
                incoming_path="C:/incoming",
                staging_path="C:/staging",
                library_path="C:/library",
                archive_path="C:/archive",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    return lib_id


@pytest.fixture
def job_repo(engine: Engine) -> JobRepository:
    return JobRepository(engine)


@pytest.fixture
def pipeline_config() -> PipelineConfig:
    return PipelineConfig()


@pytest.fixture
def job_queue(job_repo: JobRepository, pipeline_config: PipelineConfig) -> JobQueueService:
    return JobQueueService(job_repo, pipeline_config)


@pytest.fixture
def track_repo(engine: Engine) -> TrackRepository:
    return TrackRepository(engine)


@pytest.fixture
def review_repo(engine: Engine) -> ReviewRepository:
    return ReviewRepository(engine)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def review_queue(
    review_repo: ReviewRepository, track_repo: TrackRepository, event_bus: EventBus
) -> ReviewQueueService:
    return ReviewQueueService(review_repo, track_repo, event_bus, confidence_threshold=0.90)


@pytest.fixture
def file_identity_repo(engine: Engine) -> FileIdentityRepository:
    return FileIdentityRepository(engine)


@pytest.fixture
def database_writer(engine: Engine) -> Iterator[DatabaseWriter]:
    writer = DatabaseWriter(engine)
    writer.start()
    yield writer
    writer.stop()


@pytest.fixture
def track_id(engine: Engine, library_id: UUID) -> UUID:
    trk_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(tracks).values(
                id=uuid_to_blob(trk_id),
                library_id=uuid_to_blob(library_id),
                zone="incoming",
                file_path=f"C:/incoming/{trk_id}.flac",
                file_name=f"{trk_id}.flac",
                file_size=1024,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    return trk_id

"""Unit tests for AcquisitionJobRepository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)

_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def _make_job(library_id: UUID, **overrides: object) -> AcquisitionJob:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": library_id,
        "job_type": AcquisitionJobType.MISSING_ALBUM,
        "state": AcquisitionJobState.CREATED,
        "created_at": _NOW,
        "updated_at": _NOW,
        "artist": "Pink Floyd",
        "album": "The Wall",
        "year": 1979,
        "mb_release_id": "release-mbid",
        "preferred_codec": "FLAC",
        "preferred_providers": ("nicotine_plus", "stub"),
        "history": ("2026-07-20T12:00:00+00:00 created",),
        "extra": {"source": "test"},
    }
    defaults.update(overrides)
    return AcquisitionJob(**defaults)  # type: ignore[arg-type]


def test_create_and_get_round_trips_every_field(engine: Engine, library_id: UUID) -> None:
    repo = AcquisitionJobRepository(engine)
    job = _make_job(
        library_id,
        state=AcquisitionJobState.QUEUED,
        selected_result_id="result-1",
        selected_provider_id="stub",
        retry_count=2,
        priority=50,
        progress=0.25,
        error_message="transient",
        preferred_bit_depth=24,
        preferred_country="US",
    )

    repo.create(job)
    loaded = repo.get(job.id)

    assert loaded == job


def test_get_returns_none_for_missing_job(engine: Engine) -> None:
    repo = AcquisitionJobRepository(engine)

    assert repo.get(generate_uuid7()) is None


def test_batch_create_persists_multiple_jobs(engine: Engine, library_id: UUID) -> None:
    repo = AcquisitionJobRepository(engine)
    batch = [_make_job(library_id, album=f"Album {index}") for index in range(5)]

    repo.batch_create(batch)

    loaded_ids = {loaded.id for job in batch if (loaded := repo.get(job.id)) is not None}
    assert loaded_ids == {job.id for job in batch}


def test_list_by_library_orders_by_priority(engine: Engine, library_id: UUID) -> None:
    repo = AcquisitionJobRepository(engine)
    high = _make_job(library_id, priority=10, album="High")
    low = _make_job(library_id, priority=200, album="Low")
    repo.batch_create([high, low])

    results = repo.list_by_library(library_id)

    assert [job.id for job in results] == [high.id, low.id]


def test_list_by_library_filters_by_state(engine: Engine, library_id: UUID) -> None:
    repo = AcquisitionJobRepository(engine)
    created = _make_job(library_id, state=AcquisitionJobState.CREATED)
    queued = _make_job(library_id, state=AcquisitionJobState.QUEUED)
    repo.batch_create([created, queued])

    results = repo.list_by_library(library_id, state=AcquisitionJobState.QUEUED)

    assert {job.id for job in results} == {queued.id}


def test_upsert_overwrites_existing_job(engine: Engine, library_id: UUID) -> None:
    repo = AcquisitionJobRepository(engine)
    job = _make_job(library_id)
    repo.create(job)

    updated = replace(
        job,
        state=AcquisitionJobState.COMPLETED,
        updated_at=datetime(2026, 7, 20, 13, 0, tzinfo=UTC),
        history=job.history + ("2026-07-20T13:00:00+00:00 completed",),
    )
    repo.create(updated)

    loaded = repo.get(job.id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.COMPLETED
    assert len(loaded.history) == 2

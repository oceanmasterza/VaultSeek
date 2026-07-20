"""Unit tests for AcquisitionJob state machine and AcquisitionEngine."""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

import pytest
from sqlalchemy import Engine

from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJobState,
    AcquisitionJobType,
    can_transition,
    validate_transition,
)
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.provider_manager import ProviderManager


@pytest.fixture
def acquisition_engine(engine: Engine) -> AcquisitionEngine:
    return AcquisitionEngine(
        ProviderManager([StubAcquisitionProvider()]),
        AcquisitionJobRepository(engine),
    )


def test_happy_path_transitions_are_legal() -> None:
    path = [
        AcquisitionJobState.CREATED,
        AcquisitionJobState.QUEUED,
        AcquisitionJobState.SEARCHING,
        AcquisitionJobState.COLLECTING_RESULTS,
        AcquisitionJobState.SCORING,
        AcquisitionJobState.DOWNLOADING,
        AcquisitionJobState.VERIFYING,
        AcquisitionJobState.IMPORTING,
        AcquisitionJobState.COMPLETED,
    ]
    for source, target in zip(path[:-1], path[1:], strict=True):
        assert can_transition(source, target)


def test_illegal_transition_raises() -> None:
    with pytest.raises(ValueError, match="Illegal AcquisitionJob transition"):
        validate_transition(AcquisitionJobState.CREATED, AcquisitionJobState.DOWNLOADING)


def test_engine_create_queue_and_cancel(
    acquisition_engine: AcquisitionEngine, library_id: UUID
) -> None:
    job = acquisition_engine.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_ALBUM,
        artist="Pink Floyd",
        album="The Wall",
        year=1979,
        preferred_codec="FLAC",
    )
    assert job.state is AcquisitionJobState.CREATED
    assert job.created_at.tzinfo is UTC

    queued = acquisition_engine.queue(job.id)
    assert queued.state is AcquisitionJobState.QUEUED

    cancelled = acquisition_engine.cancel(job.id)
    assert cancelled.state is AcquisitionJobState.CANCELLED
    assert cancelled.is_terminal


def test_engine_persists_jobs_across_instances(engine: Engine, library_id: UUID) -> None:
    repo = AcquisitionJobRepository(engine)
    first = AcquisitionEngine(ProviderManager([StubAcquisitionProvider()]), repo)
    job = first.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Artist",
        title="Missing Song",
    )
    first.queue(job.id)

    second = AcquisitionEngine(ProviderManager([StubAcquisitionProvider()]), repo)
    loaded = second.get(job.id)

    assert loaded is not None
    assert loaded.state is AcquisitionJobState.QUEUED
    assert loaded.title == "Missing Song"
    assert second.list_jobs(library_id=library_id) == [loaded]

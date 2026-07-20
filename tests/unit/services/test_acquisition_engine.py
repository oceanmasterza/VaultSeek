"""Unit tests for AcquisitionJob state machine and AcquisitionEngine."""

from __future__ import annotations

from datetime import UTC
from uuid import uuid4

import pytest

from vaultseek.models.entities.acquisition_job import (
    AcquisitionJobState,
    AcquisitionJobType,
    can_transition,
    validate_transition,
)
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.provider_manager import ProviderManager


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


def test_engine_create_queue_and_cancel() -> None:
    engine = AcquisitionEngine(ProviderManager([StubAcquisitionProvider()]))
    library_id = uuid4()
    job = engine.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_ALBUM,
        artist="Pink Floyd",
        album="The Wall",
        year=1979,
        preferred_codec="FLAC",
    )
    assert job.state is AcquisitionJobState.CREATED
    assert job.created_at.tzinfo is UTC

    queued = engine.queue(job.id)
    assert queued.state is AcquisitionJobState.QUEUED

    cancelled = engine.cancel(job.id)
    assert cancelled.state is AcquisitionJobState.CANCELLED
    assert cancelled.is_terminal

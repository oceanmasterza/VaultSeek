"""Unit tests for acquisition label helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from loguru import logger

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)
from vaultseek.services.acquisition_labels import (
    album_label,
    job_label,
    maybe_log_album_fully_acquired,
)

_NOW = datetime(2026, 7, 22, tzinfo=UTC)
_RELEASE_MBID = "11111111-2222-3333-4444-555555555555"


def _job(*, title: str, state: AcquisitionJobState, library_id: UUID | None = None) -> AcquisitionJob:
    lib = library_id or generate_uuid7()
    return AcquisitionJob(
        id=generate_uuid7(),
        library_id=lib,
        job_type=AcquisitionJobType.MISSING_TRACK,
        state=state,
        artist="Artist",
        album="Album",
        title=title,
        mb_release_id=_RELEASE_MBID,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_job_and_album_labels() -> None:
    job = _job(title="Track", state=AcquisitionJobState.QUEUED)
    assert job_label(job) == "Artist — Album — Track"
    assert album_label(job) == "Artist — Album"


def test_maybe_log_album_fully_acquired_when_last_track_completes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    library_id = generate_uuid7()
    job1 = _job(title="One", state=AcquisitionJobState.COMPLETED, library_id=library_id)
    job2 = _job(title="Two", state=AcquisitionJobState.DOWNLOADING, library_id=library_id)

    engine = MagicMock()
    engine.list_jobs.return_value = [job1, job2]

    with caplog.at_level("INFO"):
        logger.remove()
        logger.add(caplog.handler, format="{message}")
        maybe_log_album_fully_acquired(engine, job1)
        assert "Album fully acquired" not in caplog.text

        job2_done = _job(title="Two", state=AcquisitionJobState.COMPLETED, library_id=library_id)
        engine.list_jobs.return_value = [job1, job2_done]
        maybe_log_album_fully_acquired(engine, job2_done)
        assert "Album fully acquired: Artist — Album" in caplog.text

"""Tests for Wanted shelf parking / promote."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)
from vaultseek.services.wanted import (
    is_parked,
    list_wanted,
    park_album_job,
    promote_wanted,
    remove_wanted,
)


def _job(*, parked: bool = False, artist: str = "A", state: AcquisitionJobState = AcquisitionJobState.CREATED) -> AcquisitionJob:
    now = datetime.now(UTC)
    return AcquisitionJob(
        id=uuid4(),
        library_id=uuid4(),
        job_type=AcquisitionJobType.MISSING_ALBUM,
        state=state,
        created_at=now,
        updated_at=now,
        artist=artist,
        album="Album",
        extra={"parked": True} if parked else {},
    )


def test_is_parked() -> None:
    assert is_parked(_job(parked=True)) is True
    assert is_parked(_job(parked=False)) is False
    assert is_parked(None) is False


def test_list_wanted_filters_artist_and_cancelled() -> None:
    engine = MagicMock()
    parked_a = _job(parked=True, artist="Alpha")
    parked_b = _job(parked=True, artist="Beta")
    active = _job(parked=False, artist="Alpha")
    cancelled = _job(parked=True, artist="Alpha", state=AcquisitionJobState.CANCELLED)
    engine.list_jobs.return_value = [parked_a, parked_b, active, cancelled]
    rows = list_wanted(engine, uuid4(), artist="Alpha")
    assert [job.id for job in rows] == [parked_a.id]


def test_park_album_job_sets_flag_without_queue() -> None:
    engine = MagicMock()
    created = _job(parked=False)
    engine.create_job.return_value = created
    engine.update_extra.return_value = replace_parked(created)
    out = park_album_job(
        engine,
        library_id=created.library_id,
        artist="A",
        album="B",
        year=2001,
        extra={"discogs_release_id": 1},
    )
    engine.create_job.assert_called_once()
    engine.queue.assert_not_called()
    engine.update_extra.assert_called_once()
    args = engine.update_extra.call_args
    assert args[0][0] == created.id
    assert args[0][1]["parked"] is True
    assert args[0][1]["source"] == "wanted"
    assert out.extra.get("parked") is True


def replace_parked(job: AcquisitionJob) -> AcquisitionJob:
    from dataclasses import replace

    return replace(job, extra={**job.extra, "parked": True, "source": "wanted"})


def test_promote_wanted_clears_and_queues() -> None:
    engine = MagicMock()
    parked = _job(parked=True)
    cleared = AcquisitionJob(
        id=parked.id,
        library_id=parked.library_id,
        job_type=parked.job_type,
        state=AcquisitionJobState.CREATED,
        created_at=parked.created_at,
        updated_at=parked.updated_at,
        artist=parked.artist,
        album=parked.album,
        extra={"parked": False},
    )
    queued = AcquisitionJob(
        id=parked.id,
        library_id=parked.library_id,
        job_type=parked.job_type,
        state=AcquisitionJobState.QUEUED,
        created_at=parked.created_at,
        updated_at=parked.updated_at,
        artist=parked.artist,
        album=parked.album,
        extra={"parked": False},
    )
    engine.get.side_effect = [parked, cleared]
    engine.update_extra.return_value = cleared
    engine.queue.return_value = queued
    out = promote_wanted(engine, parked.id)
    engine.update_extra.assert_called_once_with(parked.id, {"parked": False})
    engine.queue.assert_called_once_with(parked.id)
    assert out.state is AcquisitionJobState.QUEUED


def test_remove_wanted_cancels() -> None:
    engine = MagicMock()
    parked = _job(parked=True)
    engine.get.return_value = parked
    engine.cancel.return_value = parked
    remove_wanted(engine, parked.id)
    engine.cancel.assert_called_once_with(parked.id)

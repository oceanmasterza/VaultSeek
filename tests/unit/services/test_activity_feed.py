"""Tests for the unified activity feed merge/sort."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)
from vaultseek.models.entities.job import Job, JobStatus, JobType
from vaultseek.services.activity_feed import (
    ActivitySource,
    merge_activity_items,
)


def _job(*, when: datetime, status: JobStatus = JobStatus.RUNNING) -> Job:
    return Job(
        id=uuid4(),
        library_id=uuid4(),
        job_type=JobType.SCAN_DIRECTORY,
        status=status,
        payload={"directory": r"D:\Incoming"},
        created_at=when,
        started_at=when,
    )


def _acq(*, when: datetime) -> AcquisitionJob:
    return AcquisitionJob(
        id=uuid4(),
        library_id=uuid4(),
        job_type=AcquisitionJobType.MISSING_ALBUM,
        state=AcquisitionJobState.SEARCHING,
        created_at=when,
        updated_at=when,
        artist="Artist",
        album="Album",
    )


def test_merge_sorts_newest_first_and_caps() -> None:
    now = datetime.now(UTC)
    pipeline = [
        _job(when=now - timedelta(minutes=5)),
        _job(when=now - timedelta(minutes=1), status=JobStatus.COMPLETED),
    ]
    wishlist = [_acq(when=now - timedelta(minutes=2))]
    items = merge_activity_items(
        pipeline_jobs=pipeline,
        wishlist_jobs=wishlist,
        cap=2,
    )
    assert len(items) == 2
    assert items[0].when >= items[1].when
    assert items[0].source is ActivitySource.PIPELINE
    assert items[0].status == JobStatus.COMPLETED.value


def test_source_filter_wishlist_only() -> None:
    now = datetime.now(UTC)
    items = merge_activity_items(
        pipeline_jobs=[_job(when=now)],
        wishlist_jobs=[_acq(when=now)],
        source_filter=ActivitySource.WISHLIST,
    )
    assert len(items) == 1
    assert items[0].source is ActivitySource.WISHLIST
    assert items[0].navigate_key == "acquisition"
    assert "Album" in items[0].summary

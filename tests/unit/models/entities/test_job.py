"""Unit tests for vaultseek.models.entities.job."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.job import Job, JobStatus, JobType

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": generate_uuid7(),
        "job_type": JobType.SCAN_DIRECTORY,
        "status": JobStatus.PENDING,
        "payload": {},
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def test_job_applies_documented_defaults() -> None:
    job = _make_job()

    assert job.priority == 100
    assert job.parent_job_id is None
    assert job.attempt_count == 0
    assert job.max_attempts == 3
    assert job.error_message is None
    assert job.started_at is None
    assert job.completed_at is None
    assert job.scheduled_at is None


def test_job_is_immutable() -> None:
    job = _make_job()

    with pytest.raises(dataclasses.FrozenInstanceError):
        job.status = JobStatus.RUNNING  # type: ignore[misc]


def test_job_type_covers_every_documented_pipeline_stage() -> None:
    expected = {
        "scan_directory",
        "hash_file",
        "fingerprint_file",
        "identify_metadata",
        "fetch_artwork",
        "detect_duplicates",
        "evaluate_rules",
        "organize_file",
        "sync_media_server",
        "generate_report",
    }

    assert {member.value for member in JobType} == expected


def test_job_status_covers_every_documented_state() -> None:
    expected = {"pending", "running", "completed", "failed", "retry", "cancelled"}

    assert {member.value for member in JobStatus} == expected


def test_job_payload_accepts_arbitrary_json_like_dict() -> None:
    job = _make_job(payload={"path": "C:/incoming", "recursive": True, "depth": 3})

    assert job.payload["path"] == "C:/incoming"
    assert job.payload["recursive"] is True

"""Unit tests for VerificationEngine and ImportPipeline."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine

from vaultseek.core.config import PipelineConfig
from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.acquisition_job import AcquisitionJobState, AcquisitionJobType
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.interfaces.acquisition import AcquisitionProviderConfig
from vaultseek.models.interfaces.fingerprint import FingerprintResult
from vaultseek.models.value_objects.file_identity import FileIdentity
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.import_pipeline import ImportPipeline
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.provider_manager import ProviderManager
from vaultseek.services.verification_engine import VerificationEngine


def _acq(engine: Engine) -> AcquisitionEngine:
    manager = ProviderManager([StubAcquisitionProvider()])
    manager.connect(AcquisitionProviderConfig(provider_id="stub", enabled=True))
    return AcquisitionEngine(manager, AcquisitionJobRepository(engine))


def _to_downloading(acq: AcquisitionEngine, library_id: UUID) -> UUID:
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Pink Floyd",
        album="The Wall",
        title="Hey You",
        mb_release_id="mb-release-1",
    )
    acq.queue(job.id)
    acq.advance(job.id, AcquisitionJobState.SEARCHING)
    acq.advance(job.id, AcquisitionJobState.COLLECTING_RESULTS)
    acq.advance(job.id, AcquisitionJobState.SCORING)
    acq.advance(job.id, AcquisitionJobState.DOWNLOADING)
    return job.id


def test_verification_passes_and_advances_to_importing(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    acq = _acq(engine)
    job_id = _to_downloading(acq, library_id)
    audio = tmp_path / "Hey You.flac"
    audio.write_bytes(b"fLaCfake")

    result = VerificationEngine(acq).verify(job_id, [audio])

    assert result.ok
    assert "paths_provided" in result.checks_passed
    assert "metadata_check" in result.checks_passed
    assert "release_id_present" in result.checks_passed
    assert any("duplicate_check_deferred" in n for n in result.notes)
    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.IMPORTING


def test_verification_fails_when_file_missing(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    acq = _acq(engine)
    job_id = _to_downloading(acq, library_id)
    missing = tmp_path / "missing.flac"

    result = VerificationEngine(acq).verify(job_id, [missing])

    assert not result.ok
    assert any(f.startswith("missing_file:") for f in result.failures)
    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.VERIFICATION_FAILED


def test_verification_fails_without_paths(engine: Engine, library_id: UUID) -> None:
    acq = _acq(engine)
    job_id = _to_downloading(acq, library_id)

    result = VerificationEngine(acq).verify(job_id, [])

    assert not result.ok
    assert "no_local_paths" in result.failures
    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.VERIFICATION_FAILED


def test_verification_rejects_content_hash_duplicate(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    acq = _acq(engine)
    job_id = _to_downloading(acq, library_id)
    audio = tmp_path / "Hey You.flac"
    payload = b"identical-bytes"
    audio.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    now = datetime.now(UTC)
    existing_id = generate_uuid7()
    TrackRepository(engine).upsert(
        Track(
            id=existing_id,
            library_id=library_id,
            zone=LibraryZone.LIBRARY,
            file_path=str(tmp_path / "existing.flac"),
            file_name="existing.flac",
            file_size=len(payload),
            file_modified=now,
            created_at=now,
            updated_at=now,
            codec="flac",
        )
    )
    FileIdentityRepository(engine).upsert(
        FileIdentity(
            track_id=existing_id,
            content_hash_sha256=digest,
            file_size=len(payload),
            file_modified=now,
        )
    )

    result = VerificationEngine(
        acq, duplicate_repo=DuplicateRepository(engine)
    ).verify(job_id, [audio])

    assert not result.ok
    assert any(f.startswith("duplicate_hash:") for f in result.failures)


def test_verification_fingerprint_duplicate(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    acq = _acq(engine)
    job_id = _to_downloading(acq, library_id)
    audio = tmp_path / "Hey You.flac"
    audio.write_bytes(b"audio")

    now = datetime.now(UTC)
    existing_id = generate_uuid7()
    TrackRepository(engine).upsert(
        Track(
            id=existing_id,
            library_id=library_id,
            zone=LibraryZone.LIBRARY,
            file_path=str(tmp_path / "lib.flac"),
            file_name="lib.flac",
            file_size=5,
            file_modified=now,
            created_at=now,
            updated_at=now,
            codec="flac",
        )
    )
    FileIdentityRepository(engine).upsert(
        FileIdentity(
            track_id=existing_id,
            content_hash_sha256="other",
            file_size=5,
            file_modified=now,
            fingerprint_hash="fp-same",
        )
    )

    class _Fp:
        def fingerprint_file(self, path: Path) -> FingerprintResult:
            return FingerprintResult(
                duration_seconds=1.0,
                fingerprint_data=b"fp",
                fingerprint_hash="fp-same",
            )

    result = VerificationEngine(
        acq,
        duplicate_repo=DuplicateRepository(engine),
        fingerprint_provider=_Fp(),
    ).verify(job_id, [audio])

    assert not result.ok
    assert any(f.startswith("duplicate_fingerprint:") for f in result.failures)


def test_import_pipeline_completes_after_verification(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    acq = _acq(engine)
    job_id = _to_downloading(acq, library_id)
    audio = tmp_path / "Hey You.flac"
    audio.write_bytes(b"audio")

    verification = VerificationEngine(acq).verify(job_id, [audio])
    imported = ImportPipeline(acq).run_after_verification(verification)

    assert imported.ok
    assert "incoming_stage_deferred" in imported.steps_completed
    assert "organize_handoff_deferred" in imported.steps_completed
    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.COMPLETED


def test_import_pipeline_stages_into_incoming_and_enqueues_scan(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    LibraryRepository(engine).upsert(
        Library(
            id=library_id,
            name="Test",
            incoming_path=str(incoming),
            staging_path=str(tmp_path / "staging"),
            library_path=str(tmp_path / "library"),
            archive_path=str(tmp_path / "archive"),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    job_queue = JobQueueService(JobRepository(engine), PipelineConfig())
    acq = _acq(engine)
    job_id = _to_downloading(acq, library_id)
    audio = tmp_path / "Hey You.flac"
    audio.write_bytes(b"audio")

    verification = VerificationEngine(acq).verify(job_id, [audio])
    imported = ImportPipeline(
        acq, library_repo=LibraryRepository(engine), job_queue=job_queue
    ).run_after_verification(verification)

    assert imported.ok
    assert imported.staged_paths
    assert imported.staged_paths[0].exists()
    staged_dir = imported.staged_paths[0].parent
    assert staged_dir.name == str(job_id) or "vaultseek-acquisition" in staged_dir.parts
    assert any(part == "vaultseek-acquisition" for part in staged_dir.parts)
    assert "scan_enqueued" in imported.steps_completed
    assert "organize_handoff" in imported.steps_completed
    assert len(imported.enqueued_job_ids) == 1
    job = JobRepository(engine).get(imported.enqueued_job_ids[0])
    assert job is not None
    assert job.job_type is JobType.SCAN_DIRECTORY
    assert Path(job.payload["directory"]).is_dir()


def test_import_refuses_failed_verification(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    acq = _acq(engine)
    job_id = _to_downloading(acq, library_id)
    verification = VerificationEngine(acq).verify(job_id, [tmp_path / "nope.flac"])

    with pytest.raises(ValueError, match="verification failed"):
        ImportPipeline(acq).run_after_verification(verification)


def test_import_requires_importing_state(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    acq = _acq(engine)
    job_id = _to_downloading(acq, library_id)
    audio = tmp_path / "track.flac"
    audio.write_bytes(b"x")

    with pytest.raises(ValueError, match="must be IMPORTING"):
        ImportPipeline(acq).run(job_id, [audio])

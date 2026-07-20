"""Unit tests for VerificationEngine and ImportPipeline skeletons."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine

from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJobState, AcquisitionJobType
from vaultseek.models.interfaces.acquisition import AcquisitionProviderConfig
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.import_pipeline import ImportPipeline
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
    assert "duplicate_check_stub" in result.checks_passed
    assert "release_id_present" in result.checks_passed
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
    assert "organize_stub" in imported.steps_completed
    assert "library_update_stub" in imported.steps_completed
    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.COMPLETED


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

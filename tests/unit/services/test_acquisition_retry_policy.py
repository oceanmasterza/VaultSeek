"""Unit tests for acquisition retry helpers."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJobState, AcquisitionJobType
from vaultseek.models.interfaces.acquisition import AcquisitionProviderConfig
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.provider_manager import ProviderManager


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
    )
    acq.queue(job.id)
    acq.advance(job.id, AcquisitionJobState.SEARCHING)
    acq.advance(job.id, AcquisitionJobState.COLLECTING_RESULTS)
    acq.advance(job.id, AcquisitionJobState.SCORING)
    acq.advance(job.id, AcquisitionJobState.DOWNLOADING)
    return job.id


def test_increment_retry_count_increments_only_counter(engine: Engine, library_id: UUID) -> None:
    acq = _acq(engine)
    job_id = _to_downloading(acq, library_id)
    # Move to a failed state (allowed from DOWNLOADING).
    acq.advance(job_id, AcquisitionJobState.DOWNLOAD_FAILED, note="fail")

    job = acq.get(job_id)
    assert job is not None
    assert job.state is AcquisitionJobState.DOWNLOAD_FAILED
    prior = job.retry_count
    assert prior == 0

    updated = acq.increment_retry_count(job_id)
    assert updated.retry_count == prior + 1
    assert updated.state is AcquisitionJobState.DOWNLOAD_FAILED
    assert any("retry_count++" in entry for entry in updated.history)


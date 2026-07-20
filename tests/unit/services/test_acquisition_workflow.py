"""Unit tests for DownloadManager.complete and AcquisitionWorkflow."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJobState, AcquisitionJobType
from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    DownloadHandle,
    DownloadStatus,
    SearchRequest,
    SearchResult,
)
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_workflow import AcquisitionWorkflow
from vaultseek.services.download_manager import DownloadManager
from vaultseek.services.import_pipeline import ImportPipeline
from vaultseek.services.provider_manager import ProviderManager
from vaultseek.services.verification_engine import VerificationEngine


class _CompletingProvider(StubAcquisitionProvider):
    provider_id = "completing"
    display_name = "Completing"

    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self._paths = paths

    def search(self, request: SearchRequest) -> list[SearchResult]:
        return [
            SearchResult(
                provider_id=self.provider_id,
                result_id="r1",
                display_name="r1",
                title=request.title,
            )
        ]

    def download(self, result: SearchResult) -> DownloadHandle:
        return DownloadHandle(
            provider_id=self.provider_id,
            download_id="d1",
            result_id=result.result_id,
        )

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        return DownloadStatus(
            download_id=handle.download_id,
            state="completed",
            progress=1.0,
            local_paths=tuple(self._paths),
        )


def _to_scoring(acq: AcquisitionEngine, library_id: UUID) -> UUID:
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Artist",
        album="Album",
        title="Song",
    )
    acq.queue(job.id)
    acq.advance(job.id, AcquisitionJobState.SEARCHING)
    acq.advance(job.id, AcquisitionJobState.COLLECTING_RESULTS)
    acq.advance(job.id, AcquisitionJobState.SCORING)
    return job.id


def test_download_complete_persists_paths_and_verifying(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    audio = tmp_path / "Song.flac"
    audio.write_bytes(b"data")
    provider = _CompletingProvider([audio])
    manager = ProviderManager([provider])
    manager.connect(AcquisitionProviderConfig(provider_id="completing", enabled=True))
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    job_id = _to_scoring(acq, library_id)
    dm = DownloadManager(manager, acq)
    result = SearchResult(provider_id="completing", result_id="r1", display_name="r1")
    dm.start(job_id, result)

    status = dm.complete(job_id)

    assert status is not None
    assert status.state == "completed"
    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.VERIFYING
    assert loaded.extra.get("local_paths") == [str(audio)]


def test_download_complete_with_explicit_paths_overrides_stub_status(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    audio = tmp_path / "Song.flac"
    audio.write_bytes(b"data")
    manager = ProviderManager([StubAcquisitionProvider()])
    manager.connect(AcquisitionProviderConfig(provider_id="stub", enabled=True))
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    job_id = _to_scoring(acq, library_id)
    dm = DownloadManager(manager, acq)
    result = SearchResult(provider_id="stub", result_id="x", display_name="x")
    dm.start(job_id, result)

    # Stub status is "failed"; explicit paths still allow manual complete.
    dm.complete(job_id, [audio])

    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.VERIFYING


def test_workflow_finish_download_verifies_and_imports(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    audio = tmp_path / "Song.flac"
    audio.write_bytes(b"data")
    provider = _CompletingProvider([audio])
    manager = ProviderManager([provider])
    manager.connect(AcquisitionProviderConfig(provider_id="completing", enabled=True))
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    job_id = _to_scoring(acq, library_id)
    dm = DownloadManager(manager, acq)
    ve = VerificationEngine(acq)
    ip = ImportPipeline(acq)
    workflow = AcquisitionWorkflow(acq, dm, ve, ip)
    dm.start(
        job_id,
        SearchResult(provider_id="completing", result_id="r1", display_name="r1"),
    )

    verification, imported = workflow.finish_download(job_id)

    assert verification is not None and verification.ok
    assert imported is not None and imported.ok
    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.COMPLETED

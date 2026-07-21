"""Unit tests for AcquisitionRunner auto-acquire flow."""

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
from vaultseek.services.acquisition_runner import AcquisitionRunner
from vaultseek.services.acquisition_workflow import AcquisitionWorkflow
from vaultseek.services.download_manager import DownloadManager
from vaultseek.services.import_pipeline import ImportPipeline
from vaultseek.services.provider_manager import ProviderManager
from vaultseek.services.scoring_engine import ScoringEngine
from vaultseek.services.search_dispatcher import SearchDispatcher
from vaultseek.services.verification_engine import VerificationEngine


class _HighScoreProvider(StubAcquisitionProvider):
    provider_id = "high"
    display_name = "High"

    def search(self, request: SearchRequest) -> list[SearchResult]:
        return [
            SearchResult(
                provider_id=self.provider_id,
                result_id="hit1",
                display_name="Artist - Song",
                artist=request.artist,
                album=request.album,
                title=request.title,
                format="FLAC",
                bit_depth=24,
                track_count=10,
            )
        ]

    def download(self, result: SearchResult) -> DownloadHandle:
        return DownloadHandle(
            provider_id=self.provider_id,
            download_id="dl-1",
            result_id=result.result_id,
        )

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        return DownloadStatus(
            download_id=handle.download_id,
            state="downloading",
            progress=0.5,
        )


def _runner(engine: Engine, *, threshold: float = 0.50) -> tuple[AcquisitionRunner, AcquisitionEngine]:
    manager = ProviderManager([_HighScoreProvider()])
    manager.connect(AcquisitionProviderConfig(provider_id="high", enabled=True))
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    search = SearchDispatcher(manager, acq)
    downloads = DownloadManager(manager, acq)
    verify = VerificationEngine(acq)
    imports = ImportPipeline(acq)
    workflow = AcquisitionWorkflow(acq, downloads, verify, imports)
    runner = AcquisitionRunner(
        acq, search, ScoringEngine(), downloads, workflow, auto_acquire_threshold=threshold
    )
    return runner, acq


def test_auto_acquire_starts_download_when_above_threshold(
    engine: Engine, library_id: UUID
) -> None:
    runner, acq = _runner(engine, threshold=0.50)
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Artist",
        album="Album",
        title="Song",
        preferred_codec="FLAC",
    )

    outcome = runner.try_auto_acquire(job.id)

    loaded = acq.get(job.id)
    assert loaded is not None
    assert outcome.state is AcquisitionJobState.DOWNLOADING
    assert loaded.state is AcquisitionJobState.DOWNLOADING
    assert loaded.extra.get("scored_results")


def test_auto_acquire_waits_for_user_when_below_threshold(
    engine: Engine, library_id: UUID
) -> None:
    runner, acq = _runner(engine, threshold=0.99)
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Artist",
        album="Album",
        title="Song",
        preferred_codec="FLAC",
    )

    outcome = runner.try_auto_acquire(job.id)

    loaded = acq.get(job.id)
    assert loaded is not None
    assert outcome.state is AcquisitionJobState.WAITING_FOR_USER
    assert loaded.state is AcquisitionJobState.WAITING_FOR_USER


def test_auto_acquire_if_ready_reuses_scoring_without_research(
    engine: Engine, library_id: UUID
) -> None:
    searches = {"count": 0}

    class _CountingProvider(_HighScoreProvider):
        def search(self, request: SearchRequest) -> list[SearchResult]:
            searches["count"] += 1
            return super().search(request)

    manager = ProviderManager([_CountingProvider()])
    manager.connect(AcquisitionProviderConfig(provider_id="high", enabled=True))
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    search = SearchDispatcher(manager, acq)
    downloads = DownloadManager(manager, acq)
    verify = VerificationEngine(acq)
    imports = ImportPipeline(acq)
    workflow = AcquisitionWorkflow(acq, downloads, verify, imports)
    runner = AcquisitionRunner(
        acq, search, ScoringEngine(), downloads, workflow, auto_acquire_threshold=0.50
    )
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Artist",
        album="Album",
        title="Song",
        preferred_codec="FLAC",
    )
    runner.search_and_score(job.id)
    assert searches["count"] == 1

    outcome = runner.try_auto_acquire_if_ready(job.id)
    assert outcome is not None
    assert outcome.state is AcquisitionJobState.DOWNLOADING
    assert searches["count"] == 1


def test_poll_active_jobs_finishes_download(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"flac")

    class _CompletingProvider(_HighScoreProvider):
        def __init__(self) -> None:
            self._polls = 0

        def get_status(self, handle: DownloadHandle) -> DownloadStatus:
            self._polls += 1
            if self._polls < 2:
                return DownloadStatus(
                    download_id=handle.download_id,
                    state="downloading",
                    progress=0.5,
                )
            return DownloadStatus(
                download_id=handle.download_id,
                state="completed",
                progress=1.0,
                local_paths=(audio,),
            )

    manager = ProviderManager([_CompletingProvider()])
    manager.connect(AcquisitionProviderConfig(provider_id="high", enabled=True))
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    search = SearchDispatcher(manager, acq)
    downloads = DownloadManager(manager, acq)
    verify = VerificationEngine(acq)
    imports = ImportPipeline(acq)
    workflow = AcquisitionWorkflow(acq, downloads, verify, imports)
    runner = AcquisitionRunner(
        acq, search, ScoringEngine(), downloads, workflow, auto_acquire_threshold=0.50
    )
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        title="Song",
        preferred_codec="FLAC",
    )
    runner.try_auto_acquire(job.id)

    updated = runner.poll_active_jobs(library_id)

    loaded = acq.get(job.id)
    assert updated == 1
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.COMPLETED

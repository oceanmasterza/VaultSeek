"""Tests for acquisition failure → Attention needed review items."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.app import bootstrap
from vaultseek.core.event_bus import EventBus
from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.acquisition_job import AcquisitionJobState, AcquisitionJobType
from vaultseek.models.entities.review_item import ReviewStatus, ReviewType
from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    SearchRequest,
    SearchResult,
)
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.services.acquisition_attention import park_acquisition_failure
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_runner import AcquisitionRunner
from vaultseek.services.acquisition_workflow import AcquisitionWorkflow
from vaultseek.services.download_manager import DownloadManager
from vaultseek.services.import_pipeline import ImportPipeline
from vaultseek.services.provider_manager import ProviderManager
from vaultseek.services.review_queue_service import ReviewQueueService
from vaultseek.services.scoring_engine import ScoringEngine
from vaultseek.services.search_dispatcher import SearchDispatcher
from vaultseek.services.verification_engine import VerificationEngine


class _EmptyProvider(StubAcquisitionProvider):
    provider_id = "empty"
    display_name = "Empty"

    def search(self, request: SearchRequest) -> list[SearchResult]:
        return []


def _review_queue(engine: Engine) -> ReviewQueueService:
    return ReviewQueueService(
        ReviewRepository(engine),
        TrackRepository(engine),
        EventBus(),
    )


def _runner(
    engine: Engine,
    *,
    threshold: float = 0.50,
    with_provider: bool = True,
) -> tuple[AcquisitionRunner, AcquisitionEngine, ReviewQueueService]:
    providers: list[StubAcquisitionProvider] = []
    if with_provider:
        providers.append(_EmptyProvider())
    manager = ProviderManager(providers)
    if with_provider:
        manager.connect(AcquisitionProviderConfig(provider_id="empty", enabled=True))
    reviews = _review_queue(engine)
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    search = SearchDispatcher(manager, acq)
    downloads = DownloadManager(manager, acq)
    workflow = AcquisitionWorkflow(
        acq, downloads, VerificationEngine(acq), ImportPipeline(acq)
    )
    runner = AcquisitionRunner(
        acq,
        search,
        ScoringEngine(),
        downloads,
        workflow,
        auto_acquire_threshold=threshold,
        review_queue=reviews,
    )
    return runner, acq, reviews


def test_no_results_creates_attention_review(engine: Engine, library_id: UUID) -> None:
    runner, acq, reviews = _runner(engine)
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Artist",
        album="Album",
        title="Missing Song",
    )

    outcome = runner.try_auto_acquire(job.id)

    assert outcome.state is AcquisitionJobState.NO_RESULTS
    pending = reviews.get_pending(library_id)
    assert len(pending) == 1
    assert pending[0].review_type is ReviewType.ACQUISITION_NO_RESULTS
    assert pending[0].payload is not None
    assert pending[0].payload.get("acquisition_job_id") == str(job.id)


def test_provider_offline_creates_acquisition_failed_review(
    engine: Engine, library_id: UUID
) -> None:
    runner, acq, reviews = _runner(engine, with_provider=False)
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Artist",
        album="Album",
        title="Song",
    )

    outcome = runner.try_auto_acquire(job.id)

    assert outcome.state is AcquisitionJobState.NO_RESULTS
    pending = reviews.get_pending(library_id)
    assert len(pending) == 1
    assert pending[0].review_type is ReviewType.ACQUISITION_FAILED
    assert pending[0].payload is not None
    assert pending[0].payload.get("provider_offline") is True


def test_acquisition_attention_dedupes_same_job(engine: Engine, library_id: UUID) -> None:
    reviews = _review_queue(engine)
    acq = AcquisitionEngine(ProviderManager(), AcquisitionJobRepository(engine))
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="A",
        title="T",
    )
    acq.queue(job.id)
    acq.advance(job.id, AcquisitionJobState.SEARCHING)
    acq.advance(job.id, AcquisitionJobState.NO_RESULTS)
    loaded = acq.get(job.id)
    assert loaded is not None

    first = park_acquisition_failure(reviews, loaded, message="first")
    second = park_acquisition_failure(reviews, loaded, message="second")

    assert first == second
    pending = reviews.get_pending(library_id)
    assert len(pending) == 1
    assert "second" in (pending[0].description or "")


def test_download_failed_parks_acquisition_failed(
    tmp_path: Path, engine: Engine, library_id: UUID
) -> None:
    del tmp_path
    reviews = _review_queue(engine)
    acq = AcquisitionEngine(ProviderManager(), AcquisitionJobRepository(engine))
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="A",
        title="T",
    )
    acq.queue(job.id)
    acq.advance(job.id, AcquisitionJobState.SEARCHING)
    acq.advance(job.id, AcquisitionJobState.COLLECTING_RESULTS)
    acq.advance(job.id, AcquisitionJobState.SCORING)
    acq.advance(job.id, AcquisitionJobState.DOWNLOADING)
    acq.advance(job.id, AcquisitionJobState.DOWNLOAD_FAILED, note="provider unavailable")
    loaded = acq.get(job.id)
    assert loaded is not None

    park_acquisition_failure(reviews, loaded, message="provider unavailable")

    pending = reviews.get_pending(library_id)
    assert len(pending) == 1
    assert pending[0].review_type is ReviewType.ACQUISITION_FAILED
    assert pending[0].status is ReviewStatus.PENDING


def test_waiting_for_user_creates_needs_choice_review(
    engine: Engine, library_id: UUID
) -> None:
    class _OneHitProvider(StubAcquisitionProvider):
        provider_id = "onehit"
        display_name = "OneHit"

        def search(self, request: SearchRequest) -> list[SearchResult]:
            return [
                SearchResult(
                    provider_id="onehit",
                    result_id="r1",
                    display_name="weak match",
                    artist=request.artist,
                    album=request.album,
                    title=request.title,
                )
            ]

    manager = ProviderManager([_OneHitProvider()])
    manager.connect(AcquisitionProviderConfig(provider_id="onehit", enabled=True))
    reviews = _review_queue(engine)
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    search = SearchDispatcher(manager, acq)
    downloads = DownloadManager(manager, acq)
    workflow = AcquisitionWorkflow(
        acq, downloads, VerificationEngine(acq), ImportPipeline(acq)
    )
    runner = AcquisitionRunner(
        acq,
        search,
        ScoringEngine(),
        downloads,
        workflow,
        auto_acquire_threshold=0.99,
        review_queue=reviews,
    )
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Artist",
        album="Album",
        title="Song",
    )

    outcome = runner.try_auto_acquire(job.id)

    assert outcome.state is AcquisitionJobState.WAITING_FOR_USER
    pending = reviews.get_pending(library_id)
    assert len(pending) == 1
    assert pending[0].review_type is ReviewType.ACQUISITION_NEEDS_CHOICE


def test_bootstrap_wires_review_into_runner(tmp_path: Path) -> None:
    container = bootstrap(base_dir_override=tmp_path, console_logging=False)
    try:
        assert container.acquisition_runner._reviews is container.review_queue  # noqa: SLF001
    finally:
        container.close()

"""Unit tests for SearchDispatcher, ScoringEngine, DownloadManager."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Engine

from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJobState, AcquisitionJobType
from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    SearchRequest,
    SearchResult,
)
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.download_manager import DownloadManager
from vaultseek.services.provider_manager import ProviderManager
from vaultseek.services.scoring_engine import ScoringEngine
from vaultseek.services.search_dispatcher import SearchDispatcher


class _FakeProvider(StubAcquisitionProvider):
    provider_id = "fake"
    display_name = "Fake"

    def search(self, request: SearchRequest) -> list[SearchResult]:
        return [
            SearchResult(
                provider_id=self.provider_id,
                result_id="low",
                display_name="low",
                title=request.title,
                album="Other",
                format="MP3",
                bit_depth=16,
                track_count=1,
            ),
            SearchResult(
                provider_id=self.provider_id,
                result_id="high",
                display_name="high",
                title=request.title,
                album=request.album,
                format="FLAC",
                bit_depth=24,
                track_count=10,
            ),
        ]


def _engine(db_engine: Engine) -> AcquisitionEngine:
    manager = ProviderManager([_FakeProvider()])
    manager.connect(AcquisitionProviderConfig(provider_id="fake", enabled=True))
    return AcquisitionEngine(manager, AcquisitionJobRepository(db_engine))


def test_search_dispatcher_advances_job_and_returns_results(
    engine: Engine, library_id: UUID
) -> None:
    acq = _engine(engine)
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Artist",
        album="Album",
        title="Song",
        preferred_codec="FLAC",
    )
    dispatcher = SearchDispatcher(acq._providers, acq)  # noqa: SLF001

    results = dispatcher.dispatch(job.id)

    assert len(results) == 2
    loaded = acq.get(job.id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.COLLECTING_RESULTS


def test_search_dispatcher_marks_no_results_when_empty(
    engine: Engine, library_id: UUID
) -> None:
    manager = ProviderManager([StubAcquisitionProvider()])
    manager.connect(AcquisitionProviderConfig(provider_id="stub", enabled=True))
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_ALBUM,
        artist="A",
        album="B",
    )
    dispatcher = SearchDispatcher(manager, acq)

    assert dispatcher.dispatch(job.id) == []
    loaded = acq.get(job.id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.NO_RESULTS


def test_scoring_engine_ranks_preferred_format_highest() -> None:
    from datetime import UTC, datetime
    from vaultseek.db.uuid_utils import generate_uuid7
    from vaultseek.models.entities.acquisition_job import AcquisitionJob

    job = AcquisitionJob(
        id=generate_uuid7(),
        library_id=generate_uuid7(),
        job_type=AcquisitionJobType.MISSING_ALBUM,
        state=AcquisitionJobState.SCORING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        album="The Wall",
        title="Hey You",
        preferred_codec="FLAC",
        preferred_bit_depth=24,
    )
    results = [
        SearchResult(
            provider_id="fake",
            result_id="mp3",
            display_name="mp3",
            title="Hey You",
            album="The Wall",
            format="MP3",
            bit_depth=16,
            track_count=1,
        ),
        SearchResult(
            provider_id="fake",
            result_id="flac",
            display_name="flac",
            title="Hey You",
            album="The Wall",
            format="FLAC",
            bit_depth=24,
            track_count=10,
        ),
    ]
    scored = ScoringEngine().score_results(job, results)
    assert scored[0][0].result_id == "flac"
    assert ScoringEngine().select_best(scored) is scored[0][0]


def test_download_manager_starts_from_scoring_state(
    engine: Engine, library_id: UUID
) -> None:
    acq = _engine(engine)
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        title="Song",
    )
    acq.queue(job.id)
    acq.advance(job.id, AcquisitionJobState.SEARCHING)
    acq.advance(job.id, AcquisitionJobState.COLLECTING_RESULTS)
    acq.advance(job.id, AcquisitionJobState.SCORING)

    manager = DownloadManager(acq._providers, acq)  # noqa: SLF001
    result = SearchResult(
        provider_id="fake",
        result_id="high",
        display_name="high",
        format="FLAC",
    )
    # Fake provider must be connected for download.
    acq._providers.connect(  # noqa: SLF001
        AcquisitionProviderConfig(provider_id="fake", enabled=True)
    )
    handle = manager.start(job.id, result)

    assert handle is not None
    loaded = acq.get(job.id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.DOWNLOADING

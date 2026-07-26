"""Tests for RecommendationService parking + de-duplication."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
)
from vaultseek.models.interfaces.recommender import Recommendation, RecommendationContext
from vaultseek.services.recommendation_service import RecommendationService


@dataclass
class _FakeEngine:
    jobs: list[AcquisitionJob] = field(default_factory=list)

    def create_job(self, **kwargs: object) -> AcquisitionJob:
        now = datetime.now(UTC)
        job = AcquisitionJob(
            id=uuid4(),
            library_id=kwargs["library_id"],  # type: ignore[arg-type]
            job_type=kwargs["job_type"],  # type: ignore[arg-type]
            state=AcquisitionJobState.CREATED,
            created_at=now,
            updated_at=now,
            artist=kwargs.get("artist"),  # type: ignore[arg-type]
            album=kwargs.get("album"),  # type: ignore[arg-type]
            year=kwargs.get("year"),  # type: ignore[arg-type]
        )
        self.jobs.append(job)
        return job

    def update_extra(self, job_id: UUID, updates: dict) -> AcquisitionJob:
        for i, job in enumerate(self.jobs):
            if job.id == job_id:
                from dataclasses import replace

                merged = replace(job, extra={**job.extra, **updates})
                self.jobs[i] = merged
                return merged
        raise KeyError(job_id)

    def list_jobs(self, *, library_id: UUID | None = None) -> list[AcquisitionJob]:
        return list(self.jobs)


@dataclass
class _Row:
    name: str = ""
    artist_name: str = ""
    title: str = ""


class _FakeArtistRepo:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    def list_for_library(self, library_id: UUID, *, limit: int = 500, offset: int = 0):
        return [_Row(name=n) for n in self._names]


class _FakeAlbumRepo:
    def __init__(self, owned: list[tuple[str, str]]) -> None:
        self._owned = owned

    def list_for_library(self, library_id: UUID, *, limit: int = 500, offset: int = 0, **_: object):
        return [_Row(artist_name=a, title=t) for a, t in self._owned]


class _FakeRecommender:
    def __init__(self, recommender_id: str, recs: list[Recommendation], configured: bool = True):
        self.recommender_id = recommender_id
        self.display_name = recommender_id
        self._recs = recs
        self._configured = configured

    def is_configured(self) -> bool:
        return self._configured

    def recommend(self, context: RecommendationContext) -> list[Recommendation]:
        return self._recs


def _make_service(engine, recommenders, *, owned=None, artists=None, cap=25):
    return RecommendationService(
        acquisition_engine=engine,
        artist_repo=_FakeArtistRepo(artists or []),  # type: ignore[arg-type]
        album_repo=_FakeAlbumRepo(owned or []),  # type: ignore[arg-type]
        recommenders=recommenders,
        max_new_per_run=cap,
    )


def test_parks_new_recommendations() -> None:
    engine = _FakeEngine()
    rec = _FakeRecommender(
        "r1",
        [
            Recommendation(artist="Boards of Canada", album="Music Has the Right"),
            Recommendation(artist="Aphex Twin", album="Selected Ambient Works"),
        ],
    )
    service = _make_service(engine, [rec])

    result = service.run(uuid4())

    assert result.added == 2
    assert len(engine.jobs) == 2
    assert all(job.extra.get("parked") is True for job in engine.jobs)
    assert engine.jobs[0].extra.get("recommender") == "r1"


def test_skips_already_owned_albums() -> None:
    engine = _FakeEngine()
    rec = _FakeRecommender(
        "r1",
        [
            Recommendation(artist="Aphex Twin", album="Drukqs"),
            Recommendation(artist="Aphex Twin", album="Windowlicker"),
        ],
    )
    service = _make_service(engine, [rec], owned=[("Aphex Twin", "Drukqs")])

    result = service.run(uuid4())

    assert result.added == 1
    assert result.skipped_owned == 1


def test_dedupes_within_and_across_run() -> None:
    engine = _FakeEngine()
    rec_a = _FakeRecommender("a", [Recommendation(artist="X", album="Y")])
    rec_b = _FakeRecommender("b", [Recommendation(artist="x", album="y")])
    service = _make_service(engine, [rec_a, rec_b])

    result = service.run(uuid4())

    assert result.added == 1
    assert result.skipped_duplicate == 1


def test_respects_max_new_per_run_cap() -> None:
    engine = _FakeEngine()
    recs = [Recommendation(artist=f"A{i}", album=f"B{i}") for i in range(10)]
    service = _make_service(engine, [_FakeRecommender("r", recs)], cap=3)

    result = service.run(uuid4())

    assert result.added == 3
    assert len(engine.jobs) == 3


def test_skips_unconfigured_and_records_errors() -> None:
    engine = _FakeEngine()

    class _Boom:
        recommender_id = "boom"
        display_name = "boom"

        def is_configured(self) -> bool:
            return True

        def recommend(self, context: RecommendationContext):
            raise ConnectionError("api down")

    unconfigured = _FakeRecommender(
        "off", [Recommendation(artist="Z", album="W")], configured=False
    )
    service = _make_service(engine, [unconfigured, _Boom()])

    result = service.run(uuid4())

    assert result.added == 0
    assert "boom" in result.errors
    assert engine.jobs == []


def test_ignores_recommendations_missing_artist_or_album() -> None:
    engine = _FakeEngine()
    rec = _FakeRecommender(
        "r",
        [
            Recommendation(artist="", album="Nameless"),
            Recommendation(artist="Real", album=""),
            Recommendation(artist="Real", album="Album"),
        ],
    )
    service = _make_service(engine, [rec])

    result = service.run(uuid4())

    assert result.added == 1

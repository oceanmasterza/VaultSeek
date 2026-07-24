"""RecommendationService — turn recommender suggestions into Wanted jobs.

The service collects :class:`Recommendation` values from every enabled
recommender, drops anything already owned or already parked, and creates
new parked (Wanted) acquisition jobs up to a safety cap. It never queues
or downloads — the user (or automation) promotes Wanted entries later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from loguru import logger

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.models.interfaces.recommender import (
    Recommendation,
    RecommendationContext,
    Recommender,
)
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.wanted import list_wanted, park_album_job

SOURCE_RECOMMENDER = "recommender"


@dataclass(frozen=True, slots=True)
class RecommendationRunResult:
    """Outcome of a single recommendation pass over the library."""

    added: int = 0
    skipped_owned: int = 0
    skipped_duplicate: int = 0
    by_recommender: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def considered(self) -> int:
        return self.added + self.skipped_owned + self.skipped_duplicate


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


class RecommendationService:
    """Runs enabled recommenders and parks fresh suggestions as Wanted."""

    def __init__(
        self,
        *,
        acquisition_engine: AcquisitionEngine,
        artist_repo: ArtistRepository,
        album_repo: AlbumRepository,
        recommenders: list[Recommender],
        max_new_per_run: int = 25,
    ) -> None:
        self._engine = acquisition_engine
        self._artists = artist_repo
        self._albums = album_repo
        self._recommenders = list(recommenders)
        self._max_new_per_run = max(0, int(max_new_per_run))

    def available_recommenders(self) -> list[Recommender]:
        """Recommenders wired in — regardless of whether they are configured."""
        return list(self._recommenders)

    def build_context(self, library_id: UUID) -> RecommendationContext:
        """Seed artists + owned albums drawn from the active library."""
        artists = tuple(
            row.name for row in self._artists.list_for_library(library_id, limit=1000) if row.name
        )
        owned = frozenset(
            (_norm(row.artist_name), _norm(row.title))
            for row in self._albums.list_for_library(library_id, limit=5000)
            if row.title
        )
        return RecommendationContext(seed_artists=artists, owned_albums=owned)

    def run(self, library_id: UUID) -> RecommendationRunResult:
        """Collect suggestions from enabled recommenders and park new ones."""
        context = self.build_context(library_id)
        owned = context.owned_albums
        parked = {
            (_norm(job.artist), _norm(job.album)) for job in list_wanted(self._engine, library_id)
        }

        added = 0
        skipped_owned = 0
        skipped_duplicate = 0
        by_recommender: dict[str, int] = {}
        errors: dict[str, str] = {}
        seen_this_run: set[tuple[str, str]] = set()

        for recommender in self._recommenders:
            if not recommender.is_configured():
                continue
            try:
                suggestions = recommender.recommend(context)
            except Exception as exc:  # noqa: BLE001 - surface, do not crash the run
                logger.warning("Recommender {} failed: {}", recommender.recommender_id, exc)
                errors[recommender.recommender_id] = str(exc)
                continue

            for suggestion in suggestions:
                if added >= self._max_new_per_run:
                    break
                key = (_norm(suggestion.artist), _norm(suggestion.album))
                if not key[0] or not key[1]:
                    continue
                if key in owned:
                    skipped_owned += 1
                    continue
                if key in parked or key in seen_this_run:
                    skipped_duplicate += 1
                    continue
                self._park(library_id, recommender.recommender_id, suggestion)
                seen_this_run.add(key)
                added += 1
                by_recommender[recommender.recommender_id] = (
                    by_recommender.get(recommender.recommender_id, 0) + 1
                )
            if added >= self._max_new_per_run:
                logger.info(
                    "Recommendation run hit cap of {} new Wanted entries",
                    self._max_new_per_run,
                )
                break

        logger.info(
            "Recommendation run: +{} wanted, {} owned, {} duplicate",
            added,
            skipped_owned,
            skipped_duplicate,
        )
        return RecommendationRunResult(
            added=added,
            skipped_owned=skipped_owned,
            skipped_duplicate=skipped_duplicate,
            by_recommender=by_recommender,
            errors=errors,
        )

    def _park(self, library_id: UUID, recommender_id: str, suggestion: Recommendation) -> None:
        park_album_job(
            self._engine,
            library_id=library_id,
            artist=suggestion.artist,
            album=suggestion.album,
            year=suggestion.year,
            extra={
                "source": SOURCE_RECOMMENDER,
                "recommender": recommender_id,
                "recommendation_reason": suggestion.reason,
            },
        )

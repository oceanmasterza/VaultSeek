"""Recommender protocol — discovery sources that feed the Wanted shelf.

Recommenders are strictly *suggestion* engines. They never touch the
library, download anything, or advance the acquisition state machine.
They return :class:`Recommendation` values that the
:class:`~vaultseek.services.recommendation_service.RecommendationService`
de-duplicates against the library and parks as Wanted jobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class RecommendationContext:
    """Inputs a recommender may use to generate suggestions.

    ``seed_artists`` are the distinct artist names already in the active
    library — the basis for "more like what you own" recommenders. Sources
    that pull from external lists (e.g. a Spotify playlist) can ignore it.
    """

    seed_artists: tuple[str, ...] = ()
    owned_albums: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True, slots=True)
class Recommendation:
    """One suggested album (or track) to add to the Wanted shelf."""

    artist: str | None = None
    album: str | None = None
    title: str | None = None
    year: int | None = None
    source: str = ""
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class Recommender(Protocol):
    """Pluggable source of Wanted-shelf suggestions."""

    recommender_id: str
    display_name: str

    def is_configured(self) -> bool:
        """True when the recommender has the credentials/settings it needs."""
        ...

    def recommend(self, context: RecommendationContext) -> list[Recommendation]: ...

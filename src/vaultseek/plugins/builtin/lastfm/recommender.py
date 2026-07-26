"""Last.fm similar-music recommender.

For each seed artist already in the library, pull Last.fm's similar
artists and their top albums, then suggest the ones the library does not
already own. Seed artists that are themselves suggestions are skipped so
recommendations lean toward *new* artists.
"""

from __future__ import annotations

from loguru import logger

from vaultseek.models.interfaces.recommender import Recommendation, RecommendationContext
from vaultseek.plugins.builtin.lastfm.client import LastfmClient

# Cap seed artists per run so a huge library does not fan out into thousands
# of Last.fm calls in one pass.
_MAX_SEED_ARTISTS = 40


class LastfmSimilarRecommender:
    """Suggests albums by artists similar to those already in the library."""

    recommender_id = "lastfm_similar"
    display_name = "Similar music (Last.fm)"

    def __init__(
        self,
        *,
        api_key: str = "",
        similar_artist_limit: int = 5,
        top_albums_per_artist: int = 2,
        client: LastfmClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._similar_limit = max(1, similar_artist_limit)
        self._top_albums = max(1, top_albums_per_artist)
        self._client = client

    def is_configured(self) -> bool:
        return bool(self._client) or bool(self._api_key.strip())

    def _resolve_client(self) -> LastfmClient:
        if self._client is not None:
            return self._client
        return LastfmClient(self._api_key)

    def recommend(self, context: RecommendationContext) -> list[Recommendation]:
        if not self.is_configured():
            return []
        client = self._resolve_client()
        owned_artists = {name.strip().casefold() for name in context.seed_artists}
        recommendations: list[Recommendation] = []
        seen: set[tuple[str, str]] = set()

        for seed in context.seed_artists[:_MAX_SEED_ARTISTS]:
            try:
                similar = client.similar_artists(seed, limit=self._similar_limit)
            except ConnectionError as exc:
                logger.debug("Last.fm similar lookup failed for {}: {}", seed, exc)
                continue
            for candidate in similar:
                if candidate.name.strip().casefold() in owned_artists:
                    continue
                try:
                    albums = client.top_albums(candidate.name, limit=self._top_albums)
                except ConnectionError as exc:
                    logger.debug("Last.fm top-albums failed for {}: {}", candidate.name, exc)
                    continue
                for album in albums:
                    key = (album.artist.strip().casefold(), album.album.strip().casefold())
                    if key in seen:
                        continue
                    seen.add(key)
                    recommendations.append(
                        Recommendation(
                            artist=album.artist,
                            album=album.album,
                            source=self.recommender_id,
                            reason=f"Similar to {seed} (Last.fm)",
                        )
                    )
        return recommendations

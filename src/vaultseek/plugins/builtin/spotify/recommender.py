"""Spotify playlist-sync recommender.

Mirrors the albums referenced by one or more public Spotify playlists into
the Wanted shelf. Playlists are track-based, so tracks are collapsed to
their distinct albums (owning the album is how VaultSeek acquires tracks).
"""

from __future__ import annotations

from loguru import logger

from vaultseek.models.interfaces.recommender import Recommendation, RecommendationContext
from vaultseek.plugins.builtin.spotify.client import SpotifyClient, parse_playlist_id


class SpotifyPlaylistRecommender:
    """Suggests the albums that appear in configured public playlists."""

    recommender_id = "spotify_playlists"
    display_name = "Spotify playlist sync"

    def __init__(
        self,
        *,
        client_id: str = "",
        client_secret: str = "",
        playlist_urls: tuple[str, ...] = (),
        client: SpotifyClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._playlist_urls = tuple(playlist_urls)
        self._client = client

    def is_configured(self) -> bool:
        has_creds = bool(self._client) or bool(
            self._client_id.strip() and self._client_secret.strip()
        )
        return has_creds and bool(self._playlist_urls)

    def _resolve_client(self) -> SpotifyClient:
        if self._client is not None:
            return self._client
        return SpotifyClient(self._client_id, self._client_secret)

    def recommend(self, context: RecommendationContext) -> list[Recommendation]:
        if not self.is_configured():
            return []
        client = self._resolve_client()
        recommendations: list[Recommendation] = []
        seen: set[tuple[str, str]] = set()

        for raw_url in self._playlist_urls:
            playlist_id = parse_playlist_id(raw_url)
            if not playlist_id:
                logger.debug("Skipping unparseable Spotify playlist ref: {}", raw_url)
                continue
            try:
                tracks = client.playlist_tracks(playlist_id)
            except ConnectionError as exc:
                logger.warning("Spotify playlist {} failed: {}", playlist_id, exc)
                continue
            for track in tracks:
                key = (track.artist.strip().casefold(), track.album.strip().casefold())
                if key in seen:
                    continue
                seen.add(key)
                recommendations.append(
                    Recommendation(
                        artist=track.artist,
                        album=track.album,
                        year=track.year,
                        source=self.recommender_id,
                        reason="From Spotify playlist",
                    )
                )
        return recommendations

"""Built-in Spotify playlist-sync recommender."""

from vaultseek.plugins.builtin.spotify.client import SpotifyClient, parse_playlist_id
from vaultseek.plugins.builtin.spotify.recommender import SpotifyPlaylistRecommender

__all__ = ["SpotifyClient", "SpotifyPlaylistRecommender", "parse_playlist_id"]

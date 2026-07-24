"""Built-in Last.fm similar-music recommender."""

from vaultseek.plugins.builtin.lastfm.client import LastfmClient
from vaultseek.plugins.builtin.lastfm.recommender import LastfmSimilarRecommender

__all__ = ["LastfmClient", "LastfmSimilarRecommender"]

"""Built-in Discogs metadata and artwork providers."""

from vaultseek.plugins.builtin.discogs.artwork import DiscogsArtworkProvider
from vaultseek.plugins.builtin.discogs.provider import DiscogsProvider

__all__ = ["DiscogsArtworkProvider", "DiscogsProvider"]

"""Built-in Shazamio audio-recognition metadata provider (AcoustID fallback)."""

from vaultseek.plugins.builtin.shazamio.pool import ShazamioProviderPool, build_shazam_routes
from vaultseek.plugins.builtin.shazamio.provider import ShazamioProvider

__all__ = ["ShazamioProvider", "ShazamioProviderPool", "build_shazam_routes"]

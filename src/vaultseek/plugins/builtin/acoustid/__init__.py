"""Built-in AcoustID HTTP metadata provider."""

from vaultseek.plugins.builtin.acoustid.pool import AcoustIdProviderPool, build_acoustid_endpoints
from vaultseek.plugins.builtin.acoustid.provider import AcoustIdProvider

__all__ = ["AcoustIdProvider", "AcoustIdProviderPool", "build_acoustid_endpoints"]

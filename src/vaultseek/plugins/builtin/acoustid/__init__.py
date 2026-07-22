"""Built-in AcoustID HTTP metadata provider."""

from vaultseek.plugins.builtin.acoustid.provider import AcoustIdProvider
from vaultseek.plugins.builtin.acoustid.pool import AcoustIdProviderPool, build_acoustid_endpoints

__all__ = ["AcoustIdProvider", "AcoustIdProviderPool", "build_acoustid_endpoints"]

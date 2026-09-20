"""Built-in NZBGet download client (optional Usenet downloader for Prowlarr NZBs)."""

from vaultseek.plugins.builtin.nzbget.client import (
    NzbgetAccess,
    NzbgetClient,
    NzbgetItem,
    NzbgetMappedStatus,
    NzbgetRpcError,
)

__all__ = [
    "NzbgetAccess",
    "NzbgetClient",
    "NzbgetItem",
    "NzbgetMappedStatus",
    "NzbgetRpcError",
]

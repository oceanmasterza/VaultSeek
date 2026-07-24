"""Built-in Prowlarr (search) + qBittorrent (download) acquisition provider."""

from vaultseek.plugins.builtin.prowlarr_qbit.provider import ProwlarrQbittorrentProvider
from vaultseek.plugins.builtin.prowlarr_qbit.prowlarr_client import (
    ProwlarrClient,
    ProwlarrResult,
)
from vaultseek.plugins.builtin.prowlarr_qbit.qbittorrent_client import (
    QbittorrentClient,
    QbittorrentTorrent,
    infohash_from_magnet,
)

__all__ = [
    "ProwlarrClient",
    "ProwlarrResult",
    "ProwlarrQbittorrentProvider",
    "QbittorrentClient",
    "QbittorrentTorrent",
    "infohash_from_magnet",
]

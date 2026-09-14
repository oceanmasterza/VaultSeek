"""Isolated connection diagnostics; never reconfigure active acquisition clients."""

from collections.abc import Callable

import requests

from vaultseek.core.config import AcquisitionConfig
from vaultseek.models.interfaces.media_server import MediaServerConfig, MediaServerPlugin
from vaultseek.plugins.builtin.prowlarr_qbit import ProwlarrClient, QbittorrentClient
from vaultseek.plugins.builtin.sabnzbd import SabnzbdClient


class ConnectionChecks:
    """Use disposable clients so checks cannot disrupt downloads or server syncs."""

    def __init__(self, media_factory: Callable[[], list[MediaServerPlugin]]) -> None:
        self._media_factory = media_factory

    def download(self, name: str, config: AcquisitionConfig) -> bool:
        """Check supplied, unsaved settings with bounded network timeouts."""
        with requests.Session() as session:
            if name == "Prowlarr":
                return ProwlarrClient(
                    config.prowlarr.base_url,
                    config.prowlarr.api_key,
                    session=session,
                    timeout_seconds=5.0,
                ).probe()
            if name == "qBittorrent":
                return QbittorrentClient(
                    config.qbittorrent.base_url,
                    config.qbittorrent.username,
                    config.qbittorrent.password,
                    session=session,
                    timeout_seconds=5.0,
                ).probe()
            if name == "SABnzbd":
                client = SabnzbdClient(
                    config.sabnzbd.base_url,
                    config.sabnzbd.api_key,
                    session=session,
                    timeout_seconds=5.0,
                )
                return client.probe_authenticated()
        return False

    def media(self, config: MediaServerConfig) -> bool:
        """Check a separate plugin instance; never trigger a library rescan."""
        for plugin in self._media_factory():
            if plugin.plugin_id == config.plugin_id:
                try:
                    return plugin.connect(config)
                finally:
                    plugin.disconnect()
        return False

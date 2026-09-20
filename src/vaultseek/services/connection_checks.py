"""Isolated connection diagnostics; never reconfigure active acquisition clients."""

from collections.abc import Callable

import requests
from loguru import logger

from vaultseek.core.config import AcquisitionConfig
from vaultseek.models.interfaces.media_server import MediaServerConfig, MediaServerPlugin
from vaultseek.plugins.builtin.nzbget import NzbgetAccess, NzbgetClient
from vaultseek.plugins.builtin.prowlarr_qbit import ProwlarrClient, QbittorrentClient
from vaultseek.plugins.builtin.sabnzbd import SabnzbdClient
from vaultseek.services.connection_status import (
    PROBE_NZBGET,
    PROBE_PROWLARR,
    PROBE_QBITTORRENT,
    PROBE_SABNZBD,
    configured_dashboard_probe_ids,
)

_DASHBOARD_PROBE_NAMES = (
    (PROBE_PROWLARR, "Prowlarr"),
    (PROBE_QBITTORRENT, "qBittorrent"),
    (PROBE_SABNZBD, "SABnzbd"),
    (PROBE_NZBGET, "NZBGet"),
)


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
            if name == "NZBGet":
                return NzbgetClient(
                    config.nzbget.base_url,
                    config.nzbget.username,
                    config.nzbget.password,
                    session=session,
                    timeout_seconds=5.0,
                ).probe_authenticated()
        return False

    def probe_dashboard_clients(self, config: AcquisitionConfig) -> dict[str, bool]:
        """Read-only probes for configured Dashboard clients.

        Unconfigured clients are omitted so the tile stays Off or unverified.
        One failure does not cancel the other clients. Callers must not run
        this on the UI thread: each check uses a bounded timeout.
        """
        wanted = set(configured_dashboard_probe_ids(config))
        results: dict[str, bool] = {}
        for probe_id, name in _DASHBOARD_PROBE_NAMES:
            if probe_id not in wanted:
                continue
            try:
                results[probe_id] = bool(self.download(name, config))
            except Exception as exc:  # noqa: BLE001 — keep the other clients independent
                logger.warning(
                    "Dashboard client probe failed for {}: {}",
                    name,
                    type(exc).__name__,
                )
                results[probe_id] = False
        return results

    def nzbget_access(self, config: AcquisitionConfig) -> NzbgetAccess:
        """Classify NZBGet credentials without appending an NZB."""
        with requests.Session() as session:
            return NzbgetClient(
                config.nzbget.base_url,
                config.nzbget.username,
                config.nzbget.password,
                session=session,
                timeout_seconds=5.0,
            ).probe_access()

    def media(self, config: MediaServerConfig) -> bool:
        """Check a separate plugin instance; never trigger a library rescan."""
        for plugin in self._media_factory():
            if plugin.plugin_id == config.plugin_id:
                try:
                    return plugin.connect(config)
                finally:
                    plugin.disconnect()
        return False

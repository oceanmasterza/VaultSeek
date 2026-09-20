"""Human-readable status of identification, download, and media-server tools."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from vaultseek.core.config import AcquisitionConfig, MetadataConfig, RecommendationConfig

_DOWNLOAD_IDS = frozenset({"nicotine_plus", "usenet", "prowlarr_public", "prowlarr_private"})


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """One row for Dashboard / setup checklists. Never includes secrets."""

    name: str
    state: str
    detail: str
    location: str


def has_connected_download_source(connected_ids: Iterable[str]) -> bool:
    """True when a real search provider (not the stub) is connected."""
    return bool(set(connected_ids) & _DOWNLOAD_IDS)


def summarize_music_tools(
    *,
    acquisition: AcquisitionConfig,
    metadata: MetadataConfig,
    recommendations: RecommendationConfig | None = None,
    connected_ids: Iterable[str],
    media_plugins: Sequence[str] = (),
) -> tuple[ToolStatus, ...]:
    """Describe each tool from saved config plus ProviderManager connections."""
    connected = set(connected_ids)
    nic = acquisition.nicotine_plus
    torrents = acquisition.prowlarr.enabled and acquisition.qbittorrent.enabled
    usenet = acquisition.prowlarr.enabled and acquisition.sabnzbd.enabled
    prowlarr_connected = bool(connected & {"usenet", "prowlarr_public", "prowlarr_private"})
    torrents_connected = bool(connected & {"prowlarr_public", "prowlarr_private"})
    acoustid = bool(metadata.acoustid_api_key) or any(
        endpoint.api_key for endpoint in metadata.acoustid_endpoints
    )
    plugins = tuple(plugin for plugin in media_plugins if plugin)
    recommenders = recommendations or RecommendationConfig()
    proxy_count = sum(1 for endpoint in metadata.acoustid_endpoints if endpoint.proxy_url)
    fingerprinting_enabled = "acoustid" in metadata.enabled_providers
    shazam_enabled = "shazamio" in metadata.enabled_providers
    return (
        _download_row(
            "Nicotine+ (Soulseek)",
            enabled=nic.enabled,
            connected="nicotine_plus" in connected,
            location="settings",
            off_detail="Enable under Settings → Wishlist & downloads.",
        ),
        _download_row(
            "Usenet (Prowlarr → SABnzbd)",
            enabled=usenet,
            connected="usenet" in connected,
            location="plugins",
            off_detail="Enable Prowlarr and SABnzbd under System → Plugins.",
        ),
        _download_row(
            "Public torrents (Prowlarr → qBittorrent)",
            enabled=torrents,
            connected="prowlarr_public" in connected,
            location="plugins",
            off_detail="Enable Prowlarr and qBittorrent under System → Plugins.",
        ),
        _download_row(
            "Private torrents (Prowlarr → qBittorrent)",
            enabled=torrents,
            connected="prowlarr_private" in connected,
            location="plugins",
            off_detail="Enable Prowlarr and qBittorrent under System → Plugins.",
        ),
        _download_row(
            "Prowlarr indexers",
            enabled=acquisition.prowlarr.enabled,
            connected=prowlarr_connected,
            location="plugins",
            off_detail="Enable and configure Prowlarr under System → Plugins.",
        ),
        _download_row(
            "qBittorrent WebUI",
            enabled=acquisition.qbittorrent.enabled,
            connected=torrents_connected,
            location="plugins",
            off_detail="Enable and configure qBittorrent under System → Plugins.",
        ),
        _download_row(
            "SABnzbd",
            enabled=acquisition.sabnzbd.enabled,
            connected="usenet" in connected,
            location="plugins",
            off_detail="Enable and configure SABnzbd under System → Plugins.",
        ),
        ToolStatus(
            name="Chromaprint / AcoustID",
            state="configured" if acoustid and fingerprinting_enabled else "off",
            detail=(
                f"{len(metadata.acoustid_endpoints) or 1} key(s) saved; "
                f"{proxy_count} proxy route(s)."
                if acoustid
                else "Add an AcoustID application key under Settings → Application."
            ),
            location="settings",
        ),
        ToolStatus(
            name="Shazam audio recognition",
            state="configured" if shazam_enabled else "off",
            detail=(
                f"Enabled with direct route plus {proxy_count} configured proxy route(s)."
                if shazam_enabled
                else "Enable under Settings → Application to use audio-recognition fallback."
            ),
            location="settings",
        ),
        ToolStatus(
            name="MusicBrainz metadata",
            state=("configured" if "musicbrainz" in metadata.enabled_providers else "off"),
            detail=(
                "Public metadata lookup enabled."
                if "musicbrainz" in metadata.enabled_providers
                else "Disabled in identification providers."
            ),
            location="settings",
        ),
        ToolStatus(
            name="Discogs metadata",
            state="configured" if metadata.discogs_user_token else "off",
            detail=(
                "Personal token saved."
                if metadata.discogs_user_token
                else "Create a token at discogs.com/settings/developers."
            ),
            location="settings",
        ),
        ToolStatus(
            name="Media server",
            state="configured" if plugins else "off",
            detail=(
                ", ".join(plugins)
                if plugins
                else "Optional. Save Jellyfin or another server under Settings → Media servers."
            ),
            location="settings",
        ),
        ToolStatus(
            name="Last.fm recommendations",
            state=(
                "configured"
                if recommenders.lastfm.enabled and bool(recommenders.lastfm.api_key)
                else "off"
            ),
            detail=(
                "API key saved; similar-artist recommendations are enabled."
                if recommenders.lastfm.enabled and recommenders.lastfm.api_key
                else "Add an API key and enable under System → Plugins."
            ),
            location="plugins",
        ),
        ToolStatus(
            name="Spotify playlists",
            state=(
                "configured"
                if recommenders.spotify.enabled
                and bool(recommenders.spotify.client_id)
                and bool(recommenders.spotify.client_secret)
                else "off"
            ),
            detail=(
                "Credentials saved; "
                f"{len(recommenders.spotify.playlist_urls)} playlist(s) configured."
                if recommenders.spotify.enabled
                and recommenders.spotify.client_id
                and recommenders.spotify.client_secret
                else "Add app credentials and enable under System → Plugins."
            ),
            location="plugins",
        ),
    )


def format_tool_status_lines(rows: Sequence[ToolStatus]) -> str:
    """Plain-text checklist for Dashboard (no HTML)."""
    labels = {
        "connected": "Connected",
        "enabled": "Enabled, not connected",
        "configured": "Configured",
        "off": "Off",
    }
    return "\n".join(
        f"{labels.get(row.state, row.state)} — {row.name}. {row.detail}" for row in rows
    )


def _download_row(
    name: str,
    *,
    enabled: bool,
    connected: bool,
    location: str,
    off_detail: str,
) -> ToolStatus:
    if connected:
        return ToolStatus(name, "connected", "Ready for search.", location)
    if enabled:
        return ToolStatus(
            name,
            "enabled",
            "Enabled in VaultSeek but not connected. Start the client, then Test.",
            location,
        )
    return ToolStatus(name, "off", off_detail, location)

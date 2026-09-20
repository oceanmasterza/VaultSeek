"""Human-readable status of identification, download, and media-server tools."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from vaultseek.core.config import (
    AcquisitionConfig,
    MetadataConfig,
    RecommendationConfig,
    normalize_usenet_download_client,
)

_DOWNLOAD_IDS = frozenset({"nicotine_plus", "usenet", "prowlarr_public", "prowlarr_private"})
_TORRENT_IDS = frozenset({"prowlarr_public", "prowlarr_private"})
_PROWLARR_IDS = frozenset({"usenet", "prowlarr_public", "prowlarr_private"})

# Explicit caller-supplied probe results. Dashboard must not invent these.
PROBE_NICOTINE = "nicotine_plus"
PROBE_PROWLARR = "prowlarr"
PROBE_QBITTORRENT = "qbittorrent"
PROBE_SABNZBD = "sabnzbd"
PROBE_NZBGET = "nzbget"


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """One integration tile for Dashboard / setup checklists. Never includes secrets."""

    name: str
    state: str
    detail: str
    location: str
    short_name: str = ""


def has_connected_download_source(connected_ids: Iterable[str]) -> bool:
    """True when a real search provider (not the stub) is connected."""
    return bool(set(connected_ids) & _DOWNLOAD_IDS)


def nzbget_enabled(acquisition: AcquisitionConfig) -> bool:
    """True when the optional NZBGet downloader is switched on. Default is off."""
    enabled, _saved = _nzbget_flags(acquisition)
    return enabled


def usenet_download_client_id(acquisition: AcquisitionConfig) -> str:
    """Selected Usenet downloader. SABnzbd stays the default until config says otherwise."""
    return normalize_usenet_download_client(acquisition.usenet_download_client)


def dashboard_probe_fingerprint(acquisition: AcquisitionConfig) -> str:
    """Digest of settings a dashboard client probe depends on.

    Search source order and the selected Usenet client are not included.
    The digest is not a credential and must not be shown in the UI.
    """
    prowlarr = acquisition.prowlarr
    qbit = acquisition.qbittorrent
    sab = acquisition.sabnzbd
    nzb = acquisition.nzbget
    material = "\n".join(
        (
            str(prowlarr.enabled),
            prowlarr.base_url,
            prowlarr.api_key,
            str(qbit.enabled),
            qbit.base_url,
            qbit.username,
            qbit.password,
            str(sab.enabled),
            sab.base_url,
            sab.api_key,
            str(nzb.enabled),
            nzb.base_url,
            nzb.username,
            nzb.password,
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


def configured_dashboard_probe_ids(acquisition: AcquisitionConfig) -> tuple[str, ...]:
    """Clients with an enable flag or saved credential. Off clients are omitted."""
    ids: list[str] = []
    prowlarr = acquisition.prowlarr
    qbit = acquisition.qbittorrent
    sab = acquisition.sabnzbd
    nzb = acquisition.nzbget
    if prowlarr.enabled or bool(prowlarr.api_key.strip()):
        ids.append(PROBE_PROWLARR)
    if qbit.enabled or bool(qbit.password.strip()):
        ids.append(PROBE_QBITTORRENT)
    if sab.enabled or bool(sab.api_key.strip()):
        ids.append(PROBE_SABNZBD)
    if nzb.enabled or bool(nzb.password.strip()):
        ids.append(PROBE_NZBGET)
    return tuple(ids)


def state_label(state: str) -> str:
    """Short tile label. Configured means saved settings without a compatible live check."""
    labels = {
        "connected": "Connected",
        "configured": "Configured",
        "failed": "Failed",
        "off": "Off",
        "enabled": "Not connected",
    }
    return labels.get(state, state)


def summarize_music_tools(
    *,
    acquisition: AcquisitionConfig,
    metadata: MetadataConfig,
    recommendations: RecommendationConfig | None = None,
    connected_ids: Iterable[str],
    media_plugins: Sequence[str] = (),
    client_probes: Mapping[str, bool] | None = None,
) -> tuple[ToolStatus, ...]:
    """Describe each integration from saved config plus real provider links.

    ``client_probes`` is optional and only reflects checks the caller already
    performed. A connected ``usenet`` search source is Prowlarr, not proof that
    SABnzbd or NZBGet is up — those clients share that source.
    """
    connected = set(connected_ids)
    probes = client_probes or {}
    nic = acquisition.nicotine_plus
    prowlarr = acquisition.prowlarr
    qbit = acquisition.qbittorrent
    sab = acquisition.sabnzbd
    nzb_enabled, nzb_saved = _nzbget_flags(acquisition)
    selected = usenet_download_client_id(acquisition)
    prowlarr_connected = bool(connected & _PROWLARR_IDS)
    torrents_connected = bool(connected & _TORRENT_IDS)
    acoustid = bool(metadata.acoustid_api_key) or any(
        endpoint.api_key for endpoint in metadata.acoustid_endpoints
    )
    plugins = tuple(plugin for plugin in media_plugins if plugin)
    recommenders = recommendations or RecommendationConfig()
    proxy_count = sum(1 for endpoint in metadata.acoustid_endpoints if endpoint.proxy_url)
    fingerprinting_enabled = "acoustid" in metadata.enabled_providers
    shazam_enabled = "shazamio" in metadata.enabled_providers
    return (
        _client_row(
            "NZBGet",
            short_name="NZBGet",
            location="plugins",
            state=_link_state(
                enabled=nzb_enabled,
                saved=nzb_saved,
                linked=False,
                probe=_probe(probes, PROBE_NZBGET),
            ),
            selected=selected == "nzbget",
            off_detail=(
                "Optional Usenet downloader. SABnzbd stays the default. "
                "Enable under System → Plugins."
            ),
        ),
        _client_row(
            "SABnzbd",
            short_name="SABnzbd",
            location="plugins",
            state=_link_state(
                enabled=sab.enabled,
                saved=sab.enabled or bool(sab.api_key),
                linked=False,
                probe=_probe(probes, PROBE_SABNZBD),
            ),
            selected=selected == "sabnzbd",
            off_detail="Default Usenet downloader. Enable under System → Plugins.",
        ),
        _service_row(
            "Prowlarr",
            short_name="Prowlarr",
            location="plugins",
            state=_link_state(
                enabled=prowlarr.enabled,
                saved=prowlarr.enabled or bool(prowlarr.api_key),
                linked=prowlarr_connected,
                probe=_probe(probes, PROBE_PROWLARR),
            ),
            probe=_probe(probes, PROBE_PROWLARR),
            connected_detail=(
                "Indexer search is connected. That does not verify SABnzbd or NZBGet."
            ),
            idle_detail="Enabled, but indexer search is not connected.",
            off_detail="Enable and configure Prowlarr under System → Plugins.",
        ),
        _service_row(
            "qBittorrent",
            short_name="qBittorrent",
            location="plugins",
            state=_link_state(
                enabled=qbit.enabled,
                saved=qbit.enabled or bool(qbit.password),
                linked=torrents_connected,
                probe=_probe(probes, PROBE_QBITTORRENT),
            ),
            probe=_probe(probes, PROBE_QBITTORRENT),
            connected_detail="Public or private torrent search is connected (qBittorrent probed).",
            idle_detail="Enabled, but torrent search is not connected.",
            off_detail="Enable and configure qBittorrent under System → Plugins.",
        ),
        _service_row(
            "Nicotine+ (Soulseek)",
            short_name="Nicotine+",
            location="settings",
            state=_link_state(
                enabled=nic.enabled,
                saved=nic.enabled or bool(nic.password or nic.api_token or nic.username),
                linked="nicotine_plus" in connected,
                probe=_probe(probes, PROBE_NICOTINE),
            ),
            probe=_probe(probes, PROBE_NICOTINE),
            connected_detail="Soulseek search is connected.",
            idle_detail="Enabled, but Nicotine+ is not connected.",
            off_detail="Enable under Settings → Wishlist & downloads.",
        ),
        ToolStatus(
            name="Chromaprint / AcoustID",
            short_name="AcoustID",
            state="configured" if acoustid and fingerprinting_enabled else "off",
            detail=(
                f"{len(metadata.acoustid_endpoints) or 1} key(s) saved; "
                f"{proxy_count} proxy route(s). Not live-checked."
                if acoustid and fingerprinting_enabled
                else (
                    "Key saved; fingerprinting provider is off."
                    if acoustid
                    else "Add an AcoustID application key under Settings → Application."
                )
            ),
            location="settings",
        ),
        ToolStatus(
            name="Shazam audio recognition",
            short_name="Shazam",
            state="configured" if shazam_enabled else "off",
            detail=(
                f"Enabled with direct route plus {proxy_count} configured proxy route(s). "
                "Not live-checked."
                if shazam_enabled
                else "Enable under Settings → Application to use audio-recognition fallback."
            ),
            location="settings",
        ),
        ToolStatus(
            name="MusicBrainz metadata",
            short_name="MusicBrainz",
            state="configured" if "musicbrainz" in metadata.enabled_providers else "off",
            detail=(
                "Public metadata lookup enabled. Not live-checked."
                if "musicbrainz" in metadata.enabled_providers
                else "Disabled in identification providers."
            ),
            location="settings",
        ),
        ToolStatus(
            name="Discogs metadata",
            short_name="Discogs",
            state="configured" if metadata.discogs_user_token else "off",
            detail=(
                "Personal token saved. Not live-checked."
                if metadata.discogs_user_token
                else "Create a token at discogs.com/settings/developers."
            ),
            location="settings",
        ),
        ToolStatus(
            name="Proxy routes",
            short_name="Proxies",
            state="configured" if proxy_count else "off",
            detail=(
                f"{proxy_count} proxy route(s) saved for AcoustID and Shazam. Not live-checked."
                if proxy_count
                else "No proxy URLs saved. Add them under Settings → Application."
            ),
            location="settings",
        ),
        ToolStatus(
            name="Last.fm recommendations",
            short_name="Last.fm",
            state=(
                "configured"
                if recommenders.lastfm.enabled and bool(recommenders.lastfm.api_key)
                else "off"
            ),
            detail=(
                "API key saved; similar-artist recommendations are enabled. Not live-checked."
                if recommenders.lastfm.enabled and recommenders.lastfm.api_key
                else "Add an API key and enable under System → Plugins."
            ),
            location="plugins",
        ),
        ToolStatus(
            name="Spotify playlists",
            short_name="Spotify",
            state=(
                "configured"
                if recommenders.spotify.enabled
                and bool(recommenders.spotify.client_id)
                and bool(recommenders.spotify.client_secret)
                else "off"
            ),
            detail=(
                "Credentials saved; "
                f"{len(recommenders.spotify.playlist_urls)} playlist(s) configured. "
                "Not live-checked."
                if recommenders.spotify.enabled
                and recommenders.spotify.client_id
                and recommenders.spotify.client_secret
                else "Add app credentials and enable under System → Plugins."
            ),
            location="plugins",
        ),
        ToolStatus(
            name="Media server",
            short_name="Media servers",
            state="configured" if plugins else "off",
            detail=(
                f"{', '.join(plugins)}. Not live-checked."
                if plugins
                else "Optional. Save Jellyfin or another server under Settings → Media servers."
            ),
            location="settings",
        ),
    )


def format_tool_status_lines(rows: Sequence[ToolStatus]) -> str:
    """Plain-text checklist (no HTML, no secrets)."""
    return "\n".join(f"{state_label(row.state)} — {row.name}. {row.detail}" for row in rows)


def _probe(probes: Mapping[str, bool], key: str) -> bool | None:
    if key not in probes:
        return None
    return bool(probes[key])


def _link_state(*, enabled: bool, saved: bool, linked: bool, probe: bool | None) -> str:
    """Connected only for a real link or an explicit probe. Never invent a failure."""
    if probe is True or (probe is None and linked):
        return "connected"
    if probe is False:
        return "failed"
    if enabled or saved:
        return "configured"
    return "off"


def _nzbget_flags(acquisition: AcquisitionConfig) -> tuple[bool, bool]:
    """Return (enabled, credentials_or_enabled). Ignores URL defaults and secrets."""
    nzbget = acquisition.nzbget
    enabled = nzbget.enabled
    return enabled, enabled or bool(nzbget.password.strip())


def _client_row(
    name: str,
    *,
    short_name: str,
    location: str,
    state: str,
    selected: bool,
    off_detail: str,
) -> ToolStatus:
    role = "Selected Usenet downloader." if selected else "Not the selected Usenet downloader."
    if state == "connected":
        detail = f"Explicit connection check succeeded. {role}"
    elif state == "failed":
        detail = f"Explicit connection check failed. {role}"
    elif state == "configured":
        detail = (
            "Saved in VaultSeek and not live-checked here. "
            "A connected Usenet search source does not verify this downloader. "
            f"{role}"
        )
    else:
        detail = f"{off_detail} {role}"
    return ToolStatus(name, state, detail, location, short_name)


def _service_row(
    name: str,
    *,
    short_name: str,
    location: str,
    state: str,
    probe: bool | None,
    connected_detail: str,
    idle_detail: str,
    off_detail: str,
) -> ToolStatus:
    if state == "connected" and probe is True:
        detail = "Explicit connection check succeeded."
    elif state == "connected":
        detail = connected_detail
    elif state == "failed":
        detail = "Explicit connection check failed."
    elif state == "configured":
        detail = f"{idle_detail} Not live-checked beyond the acquisition providers."
    else:
        detail = off_detail
    return ToolStatus(name, state, detail, location, short_name)

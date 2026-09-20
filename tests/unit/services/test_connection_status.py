"""Dashboard integration tiles must not treat Usenet search as a downloader link."""

from dataclasses import replace

from vaultseek.core.config import (
    AcoustIdEndpointConfig,
    NzbgetConfig,
    RecommendationConfig,
    SpotifyConfig,
)
from vaultseek.services.connection_status import (
    PROBE_NZBGET,
    PROBE_PROWLARR,
    PROBE_QBITTORRENT,
    PROBE_SABNZBD,
    configured_dashboard_probe_ids,
    dashboard_probe_fingerprint,
    format_tool_status_lines,
    has_connected_download_source,
    nzbget_enabled,
    summarize_music_tools,
    usenet_download_client_id,
)


def _by_name(rows):
    return {row.short_name or row.name: row for row in rows}


def test_usenet_connection_does_not_mark_either_downloader(container) -> None:
    assert not has_connected_download_source(["stub", "prowlarr"])
    assert has_connected_download_source(["usenet"])
    assert has_connected_download_source(["prowlarr_public", "prowlarr_private"])
    assert has_connected_download_source(["nicotine_plus"])

    rows = summarize_music_tools(
        acquisition=replace(
            container.config.acquisition,
            prowlarr=replace(container.config.acquisition.prowlarr, enabled=True),
            sabnzbd=replace(container.config.acquisition.sabnzbd, enabled=True),
        ),
        metadata=container.config.metadata,
        connected_ids=("usenet",),
        media_plugins=("jellyfin",),
    )
    by_name = _by_name(rows)
    assert by_name["Prowlarr"].state == "connected"
    assert by_name["SABnzbd"].state == "configured"
    assert by_name["NZBGet"].state == "off"
    assert by_name["qBittorrent"].state == "off"
    assert "does not verify" in by_name["SABnzbd"].detail
    assert by_name["Media servers"].state == "configured"
    assert "jellyfin" in by_name["Media servers"].detail
    text = format_tool_status_lines(rows)
    assert "Connected — Prowlarr" in text
    assert "Connected — SABnzbd" not in text
    assert "Connected — NZBGet" not in text
    assert "Off — qBittorrent" in text


def test_explicit_probe_is_required_for_downloader_connectivity(container) -> None:
    acquisition = replace(
        container.config.acquisition,
        sabnzbd=replace(container.config.acquisition.sabnzbd, enabled=True, api_key="sab-secret"),
    )
    both_up = summarize_music_tools(
        acquisition=acquisition,
        metadata=container.config.metadata,
        connected_ids=("usenet",),
        client_probes={PROBE_SABNZBD: True, PROBE_NZBGET: False},
    )
    by_name = _by_name(both_up)
    assert by_name["SABnzbd"].state == "connected"
    assert by_name["NZBGet"].state == "failed"
    assert "sab-secret" not in format_tool_status_lines(both_up)
    only_search = summarize_music_tools(
        acquisition=acquisition,
        metadata=container.config.metadata,
        connected_ids=("usenet",),
    )
    quiet = _by_name(only_search)
    assert quiet["SABnzbd"].state == "configured"
    assert quiet["NZBGet"].state == "off"


def test_nzbget_selection_does_not_imply_a_live_link(container) -> None:
    acquisition = replace(
        container.config.acquisition,
        nzbget=NzbgetConfig(enabled=True, password="nzb-secret-value"),
        usenet_download_client="nzbget",
    )
    assert nzbget_enabled(acquisition) is True
    assert usenet_download_client_id(acquisition) == "nzbget"
    rows = summarize_music_tools(
        acquisition=acquisition,
        metadata=container.config.metadata,
        connected_ids=("usenet", "prowlarr_public"),
    )
    by_name = _by_name(rows)
    assert by_name["NZBGet"].state == "configured"
    assert by_name["SABnzbd"].state == "off"
    assert "Selected Usenet downloader." in by_name["NZBGet"].detail
    assert "Not the selected Usenet downloader." in by_name["SABnzbd"].detail
    assert by_name["qBittorrent"].state == "connected"
    text = format_tool_status_lines(rows)
    assert "nzb-secret-value" not in text
    assert "Connected — NZBGet" not in text


def test_default_usenet_client_remains_sabnzbd(container) -> None:
    assert usenet_download_client_id(container.config.acquisition) == "sabnzbd"
    assert nzbget_enabled(container.config.acquisition) is False


def test_identification_rows_from_saved_keys(container) -> None:
    metadata = replace(
        container.config.metadata,
        discogs_user_token="discogs-secret-xyz",
        acoustid_endpoints=(AcoustIdEndpointConfig(api_key="k", label="Main"),),
    )
    rows = summarize_music_tools(
        acquisition=container.config.acquisition,
        metadata=metadata,
        connected_ids=(),
    )
    by_name = _by_name(rows)
    assert by_name["AcoustID"].state == "configured"
    assert by_name["Discogs"].state == "configured"
    assert by_name["Discogs"].location == "settings"
    text = format_tool_status_lines(rows)
    assert "discogs-secret-xyz" not in text
    assert "Personal token saved" in text


def test_status_lists_proxy_and_recommender_configuration(container) -> None:
    metadata = replace(
        container.config.metadata,
        acoustid_endpoints=(
            AcoustIdEndpointConfig(api_key="one", proxy_url="http://proxy", label="A"),
            AcoustIdEndpointConfig(api_key="two", label="B"),
        ),
    )
    recommendations = RecommendationConfig(
        spotify=SpotifyConfig(
            enabled=True,
            client_id="client",
            client_secret="secret",
            playlist_urls=("spotify:playlist:example",),
        )
    )
    rows = summarize_music_tools(
        acquisition=container.config.acquisition,
        metadata=metadata,
        recommendations=recommendations,
        connected_ids=(),
    )
    by_name = _by_name(rows)
    assert "1 proxy route" in by_name["AcoustID"].detail
    assert by_name["Proxies"].state == "configured"
    assert by_name["Proxies"].location == "settings"
    assert "http://proxy" not in by_name["Proxies"].detail
    assert by_name["Shazam"].state == "configured"
    assert by_name["MusicBrainz"].state == "configured"
    assert by_name["Spotify"].state == "configured"
    assert by_name["Last.fm"].state == "off"
    assert by_name["Last.fm"].location == "plugins"
    assert "secret" not in format_tool_status_lines(rows)
    assert "client" not in by_name["Spotify"].detail


def test_probe_fingerprint_ignores_search_order_and_omits_secrets(container) -> None:
    acquisition = replace(
        container.config.acquisition,
        sabnzbd=replace(container.config.acquisition.sabnzbd, enabled=True, api_key="sab-secret"),
        provider_order=("nicotine_plus", "usenet"),
        usenet_download_client="sabnzbd",
    )
    reordered = replace(
        acquisition,
        provider_order=("usenet", "prowlarr_public", "nicotine_plus"),
        usenet_download_client="nzbget",
    )
    changed_key = replace(
        acquisition,
        sabnzbd=replace(acquisition.sabnzbd, api_key="other-secret"),
    )
    digest = dashboard_probe_fingerprint(acquisition)
    assert digest == dashboard_probe_fingerprint(reordered)
    assert digest != dashboard_probe_fingerprint(changed_key)
    assert "sab-secret" not in digest
    assert configured_dashboard_probe_ids(acquisition) == (PROBE_SABNZBD,)
    assert PROBE_NZBGET not in configured_dashboard_probe_ids(container.config.acquisition)


def test_explicit_client_probe_overrides_search_tier(container) -> None:
    rows = summarize_music_tools(
        acquisition=replace(
            container.config.acquisition,
            prowlarr=replace(container.config.acquisition.prowlarr, enabled=True),
            qbittorrent=replace(
                container.config.acquisition.qbittorrent, enabled=True, password="qbit-secret"
            ),
        ),
        metadata=container.config.metadata,
        connected_ids=("usenet", "prowlarr_public", "nicotine_plus"),
        client_probes={PROBE_PROWLARR: False, PROBE_QBITTORRENT: True},
    )
    by_name = _by_name(rows)
    assert by_name["Prowlarr"].state == "failed"
    assert by_name["qBittorrent"].state == "connected"
    assert "Explicit connection check failed." in by_name["Prowlarr"].detail
    assert "Explicit connection check succeeded." in by_name["qBittorrent"].detail
    assert by_name["Nicotine+"].state == "connected"
    assert "Soulseek search is connected." in by_name["Nicotine+"].detail
    assert by_name["Discogs"].state == "off"
    text = format_tool_status_lines(rows)
    assert "qbit-secret" not in text

"""Dashboard/status helpers must use waterfall provider ids, not legacy prowlarr."""

from dataclasses import replace

from vaultseek.core.config import AcoustIdEndpointConfig
from vaultseek.services.connection_status import (
    format_tool_status_lines,
    has_connected_download_source,
    summarize_music_tools,
)


def test_usenet_and_torrent_tiers_count_as_connected(container) -> None:
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
    by_name = {row.name: row for row in rows}
    assert by_name["Usenet (Prowlarr → SABnzbd)"].state == "connected"
    assert by_name["Public torrents (Prowlarr → qBittorrent)"].state == "off"
    assert by_name["Media server"].state == "configured"
    assert "jellyfin" in by_name["Media server"].detail
    text = format_tool_status_lines(rows)
    assert "Connected — Usenet" in text
    assert "Off — Public torrents" in text


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
    by_name = {row.name: row for row in rows}
    assert by_name["AcoustID fingerprinting"].state == "configured"
    assert by_name["Discogs metadata"].state == "configured"
    text = format_tool_status_lines(rows)
    assert "discogs-secret-xyz" not in text
    assert "Personal token saved" in text

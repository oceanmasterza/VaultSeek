"""Tests for schema v20: recommenders + Prowlarr/qBittorrent config."""

from __future__ import annotations

import json
from pathlib import Path

from vaultseek.core.config import (
    CURRENT_SCHEMA_VERSION,
    AppConfig,
    LastfmConfig,
    ProwlarrConfig,
    QbittorrentConfig,
    RecommendationConfig,
    SpotifyConfig,
    default_config,
    load_config,
    save_config,
)


def test_defaults_include_recommendations_and_torrent_provider() -> None:
    config = default_config()
    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.recommendations == RecommendationConfig()
    assert config.recommendations.enabled_recommenders == ()
    assert config.acquisition.prowlarr == ProwlarrConfig()
    assert config.acquisition.qbittorrent == QbittorrentConfig()
    assert "prowlarr_qbit" in config.acquisition.provider_order


def test_migrating_v19_adds_recommendations_and_torrent(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    document = default_config().to_dict()
    document["schema_version"] = 19
    document.pop("recommendations", None)
    document["acquisition"].pop("prowlarr", None)
    document["acquisition"].pop("qbittorrent", None)
    document["acquisition"]["provider_order"] = ["nicotine_plus", "stub"]
    config_path.write_text(json.dumps(document), encoding="utf-8")

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.recommendations == RecommendationConfig()
    assert config.acquisition.prowlarr == ProwlarrConfig()
    assert config.acquisition.qbittorrent == QbittorrentConfig()
    assert config.acquisition.provider_order[0] == "prowlarr_qbit"


def test_recommendation_and_torrent_config_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    original = AppConfig(
        recommendations=RecommendationConfig(
            enabled_recommenders=("lastfm_similar", "spotify_playlists"),
            max_new_per_run=10,
            lastfm=LastfmConfig(enabled=True, api_key="k", similar_artist_limit=8),
            spotify=SpotifyConfig(
                enabled=True,
                client_id="cid",
                client_secret="secret",
                playlist_urls=("https://open.spotify.com/playlist/abc",),
            ),
        ),
    )
    save_config(original, config_path)

    loaded = load_config(config_path)

    assert loaded.recommendations.enabled_recommenders == (
        "lastfm_similar",
        "spotify_playlists",
    )
    assert loaded.recommendations.max_new_per_run == 10
    assert loaded.recommendations.lastfm.api_key == "k"
    assert loaded.recommendations.spotify.playlist_urls == (
        "https://open.spotify.com/playlist/abc",
    )


def test_prowlarr_categories_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    from dataclasses import replace

    original = replace(
        default_config(),
        acquisition=replace(
            default_config().acquisition,
            prowlarr=ProwlarrConfig(enabled=True, categories=(3000, 3010), min_seeders=5),
            qbittorrent=QbittorrentConfig(enabled=True, base_url="http://x:8080"),
        ),
    )
    save_config(original, config_path)
    loaded = load_config(config_path)
    assert loaded.acquisition.prowlarr.categories == (3000, 3010)
    assert loaded.acquisition.prowlarr.min_seeders == 5
    assert loaded.acquisition.qbittorrent.base_url == "http://x:8080"

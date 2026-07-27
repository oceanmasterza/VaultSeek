"""Versioned JSON application configuration.

Configuration is stored as a single JSON document at
``AppPaths.config_file``. Every serialized document carries a
``schema_version`` field. On load, older documents are migrated forward
through a chain of pure functions registered in ``_MIGRATIONS`` until they
reach :data:`CURRENT_SCHEMA_VERSION`, so upgrading VaultSeek never
requires the user to manually edit or delete their configuration file.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from vaultseek.core.exceptions import ConfigError, ConfigMigrationError, ConfigVersionError

CURRENT_SCHEMA_VERSION = 21


@dataclass(frozen=True)
class AcoustIdEndpointConfig:
    """One AcoustID application key with optional HTTP proxy.

    Proxy URLs are also reused by the Shazamio fallback (direct route + each
    configured proxy) so fingerprint and audio-recognition share the same
    multi-IP throughput setup from Settings.
    """

    api_key: str = ""
    proxy_url: str = ""
    label: str = ""


@dataclass(frozen=True)
class NicotinePlusConfig:
    """Connection settings for the Nicotine+ acquisition provider."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 22024
    transport: str = "http"  # socket | http
    api_port: int = 12339
    api_token: str = ""
    username: str = ""
    password: str = ""
    # Soulseek flood protection — exact server limits are unpublished.
    search_min_interval_seconds: float = 5.0
    search_max_per_minute: int = 8


@dataclass(frozen=True)
class ProwlarrConfig:
    """Prowlarr indexer-aggregator settings for torrent/usenet search."""

    enabled: bool = False
    base_url: str = "http://127.0.0.1:9696"
    api_key: str = ""
    # Torznab category ids to search. 3000 = Audio (all sub-categories).
    categories: tuple[int, ...] = (3000,)
    min_seeders: int = 1


@dataclass(frozen=True)
class QbittorrentConfig:
    """qBittorrent WebUI settings — where Prowlarr torrent results are downloaded."""

    enabled: bool = False
    # Default 8081 avoids clashing with SABnzbd's common WebUI port 8080.
    base_url: str = "http://127.0.0.1:8081"
    username: str = "admin"
    password: str = ""
    # Torrents added by VaultSeek are tagged with this category for tracking.
    category: str = "vaultseek"
    # Optional explicit save path; blank uses qBittorrent's default.
    save_path: str = ""


@dataclass(frozen=True)
class SabnzbdConfig:
    """SABnzbd settings — where Prowlarr NZB / Usenet results are downloaded."""

    enabled: bool = False
    base_url: str = "http://127.0.0.1:8080"
    api_key: str = ""
    category: str = "vaultseek"


@dataclass(frozen=True)
class AcquisitionConfig:
    """Acquisition Engine provider enablement and dispatch tunables."""

    enabled_providers: tuple[str, ...] = ("stub",)
    provider_order: tuple[str, ...] = ("prowlarr", "nicotine_plus", "stub")
    search_timeout_seconds: float = 30.0
    auto_queue_jobs: bool = True
    auto_acquire_threshold: float = 0.45
    prefer_lossless: bool = True
    preferred_codec: str = ""
    min_bitrate_kbps: int = 192
    # Named UI preset: completist | collector | lossy_ok | custom
    quality_preset: str = "custom"
    download_whole_album_on_upgrade: bool = True
    # 0 = search wishlist as often as rate limits allow; >0 = at most one search pass per N hours.
    wishlist_search_interval_hours: float = 0.0
    nicotine_plus: NicotinePlusConfig = field(default_factory=NicotinePlusConfig)
    prowlarr: ProwlarrConfig = field(default_factory=ProwlarrConfig)
    qbittorrent: QbittorrentConfig = field(default_factory=QbittorrentConfig)
    sabnzbd: SabnzbdConfig = field(default_factory=SabnzbdConfig)


@dataclass(frozen=True)
class ArtworkConfig:
    """Artwork fetching tunables (Phase 11).

    No pixel threshold is documented anywhere in the architecture docs;
    500x500 is this implementation's fill-in — comfortably above
    thumbnail size, below the Cover Art Archive's typical 1200px
    originals, and user-adjustable here. ``fetch_enabled`` gates the
    *network* provider only; embedded art extraction always runs.
    """

    fetch_enabled: bool = True
    min_width: int = 500
    min_height: int = 500


@dataclass(frozen=True)
class WatchConfig:
    """Watch-folder polling tunables (Phase 10).

    Per-library enablement and the auto-approve threshold live on the
    `libraries` row (`watch_enabled`, `auto_approve_threshold`); this
    only holds the app-wide poll cadence. The poll interval doubles as
    the write-debounce window from the risk register — a file still
    being written changes size between polls and is picked up by a
    later scan.
    """

    poll_interval_seconds: float = 30.0


@dataclass(frozen=True)
class PipelineConfig:
    """Tunables for the job queue, dispatcher, and database writer thread."""

    db_writer_batch_size: int = 5_000
    db_writer_flush_interval_ms: int = 500
    job_claim_batch_size: int = 10
    scanner_worker_threads: int = 1
    hash_worker_processes: int | None = None
    metadata_worker_threads: int = 3
    retry_base_delay_seconds: float = 5.0
    retry_max_delay_seconds: float = 300.0


@dataclass(frozen=True)
class MetadataConfig:
    """Metadata provider enablement, priority order, and API keys.

    ``provider_order`` lists provider ids from highest to lowest priority
    for settings / display; the built-in providers still carry their own
    numeric ``priority`` fields used by the arbitrator.
    """

    confidence_threshold: float = 0.90
    provider_order: tuple[str, ...] = (
        "acoustid",
        "shazamio",
        "musicbrainz",
        "discogs",
        "local_tags",
        "filename_parser",
    )
    enabled_providers: tuple[str, ...] = (
        "acoustid",
        "shazamio",
        "musicbrainz",
        "discogs",
        "local_tags",
        "filename_parser",
    )
    acoustid_api_key: str = ""
    discogs_user_token: str = ""
    # Up to several keys, each with its own proxy — 3 req/s per AcoustID
    # endpoint. The same proxy URLs also feed the Shazamio route pool
    # (direct + proxies at ≤1 req/s each).
    acoustid_endpoints: tuple[AcoustIdEndpointConfig, ...] = ()
    # "all" = Chromaprint every file. "sample" = fingerprint until an album
    # folder is confirmed, then trust remaining siblings by tags/filenames.
    fingerprint_mode: str = "all"
    fingerprint_sample_min: int = 3


@dataclass(frozen=True)
class LastfmConfig:
    """Last.fm API settings for the similar-music recommender."""

    enabled: bool = False
    api_key: str = ""
    # How many similar artists to pull per seed artist in your library.
    similar_artist_limit: int = 5
    # Top albums to suggest per discovered similar artist.
    top_albums_per_artist: int = 2


@dataclass(frozen=True)
class SpotifyConfig:
    """Spotify Web API settings for the playlist-sync recommender.

    Uses the Client Credentials flow (no user login) which can read public
    playlists. Create an app at https://developer.spotify.com/dashboard.
    """

    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    # Playlist share links or spotify:playlist: URIs to mirror into Wanted.
    playlist_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecommendationConfig:
    """Discovery recommenders that feed the Wanted shelf (all opt-in)."""

    enabled_recommenders: tuple[str, ...] = ()
    # Safety cap on how many new Wanted entries a single run may create.
    max_new_per_run: int = 25
    lastfm: LastfmConfig = field(default_factory=LastfmConfig)
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)


@dataclass(frozen=True)
class AppConfig:
    """Root application configuration."""

    schema_version: int = CURRENT_SCHEMA_VERSION
    log_level: str = "INFO"
    theme: str = "dark"
    # First-run wizard: False for new installs; migration sets True for upgrades.
    setup_completed: bool = False
    # Dashboard “Getting started” checklist — hide after user dismisses.
    onboarding_tips_dismissed: bool = False
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    metadata: MetadataConfig = field(default_factory=MetadataConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)
    artwork: ArtworkConfig = field(default_factory=ArtworkConfig)
    acquisition: AcquisitionConfig = field(default_factory=AcquisitionConfig)
    recommendations: RecommendationConfig = field(default_factory=RecommendationConfig)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict representation suitable for JSON serialization."""
        data = asdict(self)
        metadata = data.get("metadata")
        if isinstance(metadata, dict):
            for key in ("provider_order", "enabled_providers"):
                value = metadata.get(key)
                if isinstance(value, tuple):
                    metadata[key] = list(value)
            endpoints = metadata.get("acoustid_endpoints")
            if isinstance(endpoints, tuple):
                metadata["acoustid_endpoints"] = list(endpoints)
        acquisition = data.get("acquisition")
        if isinstance(acquisition, dict):
            for key in ("enabled_providers", "provider_order"):
                value = acquisition.get(key)
                if isinstance(value, tuple):
                    acquisition[key] = list(value)
            prowlarr = acquisition.get("prowlarr")
            if isinstance(prowlarr, dict) and isinstance(prowlarr.get("categories"), tuple):
                prowlarr["categories"] = list(prowlarr["categories"])
        recommendations = data.get("recommendations")
        if isinstance(recommendations, dict):
            value = recommendations.get("enabled_recommenders")
            if isinstance(value, tuple):
                recommendations["enabled_recommenders"] = list(value)
            spotify = recommendations.get("spotify")
            if isinstance(spotify, dict) and isinstance(spotify.get("playlist_urls"), tuple):
                spotify["playlist_urls"] = list(spotify["playlist_urls"])
        return data


def default_config() -> AppConfig:
    """Return the built-in default configuration."""
    return AppConfig()


def _migrate_v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(raw)
    migrated["schema_version"] = 2
    migrated["pipeline"] = asdict(PipelineConfig())
    return migrated


def _migrate_v2_to_v3(raw: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(raw)
    migrated["schema_version"] = 3
    pipeline = dict(migrated.get("pipeline") or asdict(PipelineConfig()))
    pipeline.setdefault("metadata_worker_threads", 1)
    migrated["pipeline"] = pipeline
    migrated["metadata"] = asdict(MetadataConfig())
    return migrated


def _migrate_v3_to_v4(raw: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(raw)
    migrated["schema_version"] = 4
    migrated["watch"] = asdict(WatchConfig())
    return migrated


def _migrate_v4_to_v5(raw: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(raw)
    migrated["schema_version"] = 5
    migrated["artwork"] = asdict(ArtworkConfig())
    return migrated


def _migrate_v5_to_v6(raw: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(raw)
    migrated["schema_version"] = 6
    metadata = dict(migrated.get("metadata") or asdict(MetadataConfig()))
    metadata.setdefault("fingerprint_mode", "all")
    metadata.setdefault("fingerprint_sample_min", 3)
    migrated["metadata"] = metadata
    return migrated


def _migrate_v6_to_v7(raw: dict[str, Any]) -> dict[str, Any]:
    """Raise I/O worker concurrency so artwork/identify aren't single-threaded."""
    migrated = dict(raw)
    migrated["schema_version"] = 7
    pipeline = dict(migrated.get("pipeline") or asdict(PipelineConfig()))
    # Only bump the old default of 1; leave deliberate higher values alone.
    if int(pipeline.get("metadata_worker_threads") or 1) <= 1:
        pipeline["metadata_worker_threads"] = 3
    migrated["pipeline"] = pipeline
    return migrated


def _migrate_v7_to_v8(raw: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(raw)
    migrated["schema_version"] = 8
    migrated["acquisition"] = asdict(AcquisitionConfig())
    return migrated


def _migrate_v8_to_v9(raw: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(raw)
    migrated["schema_version"] = 9
    acq = dict(migrated.get("acquisition") or asdict(AcquisitionConfig()))
    acq.setdefault("auto_acquire_threshold", 0.90)
    acq.setdefault("auto_queue_jobs", True)
    nicotine = dict(acq.get("nicotine_plus") or asdict(NicotinePlusConfig()))
    nicotine.setdefault("transport", "http")
    nicotine.setdefault("api_port", 12339)
    nicotine.setdefault("api_token", "")
    acq["nicotine_plus"] = nicotine
    migrated["acquisition"] = acq
    return migrated


def _migrate_v9_to_v10(raw: dict[str, Any]) -> dict[str, Any]:
    """Turn on auto_queue_jobs — Settings now exposes the toggle; docs default is on."""
    migrated = dict(raw)
    migrated["schema_version"] = 10
    acq = dict(migrated.get("acquisition") or asdict(AcquisitionConfig()))
    acq["auto_queue_jobs"] = True
    migrated["acquisition"] = acq
    return migrated


def _migrate_v10_to_v11(raw: dict[str, Any]) -> dict[str, Any]:
    """Preserve legacy single AcoustID key as the first pooled endpoint."""
    migrated = dict(raw)
    migrated["schema_version"] = 11
    metadata = dict(migrated.get("metadata") or asdict(MetadataConfig()))
    endpoints = list(metadata.get("acoustid_endpoints") or [])
    legacy_key = str(metadata.get("acoustid_api_key") or "").strip()
    if legacy_key and not endpoints:
        endpoints = [{"api_key": legacy_key, "proxy_url": "", "label": "Primary"}]
    metadata["acoustid_endpoints"] = endpoints
    migrated["metadata"] = metadata
    return migrated


def _migrate_v11_to_v12(raw: dict[str, Any]) -> dict[str, Any]:
    """Fix common Nicotine+ misconfiguration (HTTP port used as NDJSON socket)."""
    migrated = dict(raw)
    migrated["schema_version"] = 12
    acq = dict(migrated.get("acquisition") or asdict(AcquisitionConfig()))
    nicotine = dict(acq.get("nicotine_plus") or asdict(NicotinePlusConfig()))
    transport = str(nicotine.get("transport") or "socket").casefold()
    port = int(nicotine.get("port") or 22024)
    api_port = int(nicotine.get("api_port") or 12339)
    if transport == "socket" and port == api_port:
        nicotine["transport"] = "http"
        nicotine["port"] = 22024
    acq["nicotine_plus"] = nicotine
    enabled = list(acq.get("enabled_providers") or ["stub"])
    if nicotine.get("enabled"):
        if "nicotine_plus" not in enabled:
            enabled.append("nicotine_plus")
        enabled = [provider_id for provider_id in enabled if provider_id != "stub"]
    acq["enabled_providers"] = enabled or ["stub"]
    migrated["acquisition"] = acq
    return migrated


def _migrate_v12_to_v13(raw: dict[str, Any]) -> dict[str, Any]:
    """Add Soulseek search flood-protection defaults for Nicotine+."""
    migrated = dict(raw)
    migrated["schema_version"] = 13
    acq = dict(migrated.get("acquisition") or asdict(AcquisitionConfig()))
    nicotine = dict(acq.get("nicotine_plus") or asdict(NicotinePlusConfig()))
    nicotine.setdefault("search_min_interval_seconds", 5.0)
    nicotine.setdefault("search_max_per_minute", 8)
    acq["nicotine_plus"] = nicotine
    migrated["acquisition"] = acq
    return migrated


def _migrate_v13_to_v14(raw: dict[str, Any]) -> dict[str, Any]:
    """Lower unusable auto-acquire thresholds for Soulseek path-only hits."""
    migrated = dict(raw)
    migrated["schema_version"] = 14
    acq = dict(migrated.get("acquisition") or asdict(AcquisitionConfig()))
    try:
        threshold = float(acq.get("auto_acquire_threshold", 0.45))
    except (TypeError, ValueError):
        threshold = 0.45
    # Old defaults (0.85–0.90) never auto-downloaded Nicotine hits under the
    # previous scorer. Cap down once; users can raise the setting again.
    if threshold >= 0.70:
        acq["auto_acquire_threshold"] = 0.45
    migrated["acquisition"] = acq
    return migrated


def _migrate_v14_to_v15(raw: dict[str, Any]) -> dict[str, Any]:
    """Restore Discogs + add library quality preference defaults."""
    migrated = dict(raw)
    migrated["schema_version"] = 15
    metadata = dict(migrated.get("metadata") or asdict(MetadataConfig()))
    metadata.setdefault("discogs_user_token", "")
    for key in ("provider_order", "enabled_providers"):
        providers = list(metadata.get(key) or [])
        if "discogs" not in providers:
            if "musicbrainz" in providers:
                providers.insert(providers.index("musicbrainz") + 1, "discogs")
            else:
                providers.insert(0, "discogs")
        metadata[key] = providers
    migrated["metadata"] = metadata
    acq = dict(migrated.get("acquisition") or asdict(AcquisitionConfig()))
    acq.setdefault("prefer_lossless", True)
    acq.setdefault("preferred_codec", "")
    acq.setdefault("min_bitrate_kbps", 192)
    acq.setdefault("download_whole_album_on_upgrade", True)
    migrated["acquisition"] = acq
    return migrated


def _migrate_v15_to_v16(raw: dict[str, Any]) -> dict[str, Any]:
    """Wishlist search interval (hours) for dashboard/automation."""
    migrated = dict(raw)
    migrated["schema_version"] = 16
    acq = dict(migrated.get("acquisition") or asdict(AcquisitionConfig()))
    acq.setdefault("wishlist_search_interval_hours", 0.0)
    migrated["acquisition"] = acq
    return migrated


def _migrate_v16_to_v17(raw: dict[str, Any]) -> dict[str, Any]:
    """Onboarding flags — existing installs skip forced first-run wizard."""
    migrated = dict(raw)
    migrated["schema_version"] = 17
    # Upgrades already have folders/config; don't force the wizard on them.
    migrated.setdefault("setup_completed", True)
    migrated.setdefault("onboarding_tips_dismissed", False)
    return migrated


def _migrate_v17_to_v18(raw: dict[str, Any]) -> dict[str, Any]:
    """Named quality presets for Settings / Setup wizard UI."""
    migrated = dict(raw)
    migrated["schema_version"] = 18
    acq = dict(migrated.get("acquisition") or asdict(AcquisitionConfig()))
    if "quality_preset" not in acq:
        from vaultseek.services.quality_presets import infer_preset

        acq["quality_preset"] = infer_preset(
            prefer_lossless=bool(acq.get("prefer_lossless", True)),
            preferred_codec=str(acq.get("preferred_codec") or ""),
            min_bitrate_kbps=int(acq.get("min_bitrate_kbps") or 0),
        )
    migrated["acquisition"] = acq
    return migrated


def _migrate_v18_to_v19(raw: dict[str, Any]) -> dict[str, Any]:
    """Enable Shazamio as AcoustID audio-recognition fallback."""
    migrated = dict(raw)
    migrated["schema_version"] = 19
    metadata = dict(migrated.get("metadata") or asdict(MetadataConfig()))
    for key in ("provider_order", "enabled_providers"):
        values = list(metadata.get(key) or [])
        if "shazamio" not in values:
            if "acoustid" in values:
                values.insert(values.index("acoustid") + 1, "shazamio")
            else:
                values.insert(0, "shazamio")
        metadata[key] = values
    migrated["metadata"] = metadata
    return migrated


def _migrate_v19_to_v20(raw: dict[str, Any]) -> dict[str, Any]:
    """Add opt-in recommenders (Last.fm/Spotify) and Prowlarr+qBittorrent provider."""
    migrated = dict(raw)
    migrated["schema_version"] = 20
    migrated.setdefault("recommendations", asdict(RecommendationConfig()))
    acq = dict(migrated.get("acquisition") or asdict(AcquisitionConfig()))
    acq.setdefault("prowlarr", asdict(ProwlarrConfig()))
    acq.setdefault("qbittorrent", asdict(QbittorrentConfig()))
    order = list(acq.get("provider_order") or [])
    if "prowlarr_qbit" not in order and "prowlarr" not in order:
        order.insert(0, "prowlarr_qbit")
    acq["provider_order"] = order
    migrated["acquisition"] = acq
    return migrated


def _migrate_v20_to_v21(raw: dict[str, Any]) -> dict[str, Any]:
    """Add SABnzbd and rename provider id prowlarr_qbit → prowlarr."""
    migrated = dict(raw)
    migrated["schema_version"] = 21
    acq = dict(migrated.get("acquisition") or asdict(AcquisitionConfig()))
    acq.setdefault("sabnzbd", asdict(SabnzbdConfig()))
    order = ["prowlarr" if p == "prowlarr_qbit" else p for p in (acq.get("provider_order") or [])]
    order = list(dict.fromkeys(order))
    if "prowlarr" not in order:
        order.insert(0, "prowlarr")
    acq["provider_order"] = order
    enabled = ["prowlarr" if p == "prowlarr_qbit" else p for p in (acq.get("enabled_providers") or [])]
    acq["enabled_providers"] = enabled or ["stub"]
    # Prefer 8081 for qBit when still on the SAB-clashing default 8080.
    qbit = dict(acq.get("qbittorrent") or asdict(QbittorrentConfig()))
    if str(qbit.get("base_url") or "").rstrip("/") in {
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    }:
        qbit["base_url"] = "http://127.0.0.1:8081"
    acq["qbittorrent"] = qbit
    migrated["acquisition"] = acq
    return migrated


_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
    4: _migrate_v4_to_v5,
    5: _migrate_v5_to_v6,
    6: _migrate_v6_to_v7,
    7: _migrate_v7_to_v8,
    8: _migrate_v8_to_v9,
    9: _migrate_v9_to_v10,
    10: _migrate_v10_to_v11,
    11: _migrate_v11_to_v12,
    12: _migrate_v12_to_v13,
    13: _migrate_v13_to_v14,
    14: _migrate_v14_to_v15,
    15: _migrate_v15_to_v16,
    16: _migrate_v16_to_v17,
    17: _migrate_v17_to_v18,
    18: _migrate_v18_to_v19,
    19: _migrate_v19_to_v20,
    20: _migrate_v20_to_v21,
}


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    version = raw.get("schema_version")
    if not isinstance(version, int):
        raise ConfigVersionError(
            f"Configuration is missing a valid integer 'schema_version' field: {version!r}"
        )
    if version > CURRENT_SCHEMA_VERSION:
        raise ConfigVersionError(
            f"Configuration schema version {version} is newer than this build of VaultSeek "
            f"supports (current: {CURRENT_SCHEMA_VERSION}). Update the application."
        )

    while version < CURRENT_SCHEMA_VERSION:
        migration = _MIGRATIONS.get(version)
        if migration is None:
            raise ConfigMigrationError(
                f"No migration registered to upgrade configuration from version {version}."
            )
        raw = migration(raw)
        version = raw["schema_version"]

    return raw


def _from_dict(raw: dict[str, Any]) -> AppConfig:
    known_fields = set(AppConfig.__dataclass_fields__)
    filtered = {key: value for key, value in raw.items() if key in known_fields}

    pipeline_raw = filtered.get("pipeline")
    if isinstance(pipeline_raw, dict):
        pipeline_fields = set(PipelineConfig.__dataclass_fields__)
        filtered["pipeline"] = PipelineConfig(
            **{key: value for key, value in pipeline_raw.items() if key in pipeline_fields}
        )

    metadata_raw = filtered.get("metadata")
    if isinstance(metadata_raw, dict):
        metadata_fields = set(MetadataConfig.__dataclass_fields__)
        coerced = {key: value for key, value in metadata_raw.items() if key in metadata_fields}
        if "provider_order" in coerced and isinstance(coerced["provider_order"], list):
            coerced["provider_order"] = tuple(coerced["provider_order"])
        if "enabled_providers" in coerced and isinstance(coerced["enabled_providers"], list):
            coerced["enabled_providers"] = tuple(coerced["enabled_providers"])
        if "acoustid_endpoints" in coerced and isinstance(coerced["acoustid_endpoints"], list):
            endpoint_fields = set(AcoustIdEndpointConfig.__dataclass_fields__)
            coerced["acoustid_endpoints"] = tuple(
                AcoustIdEndpointConfig(**{k: v for k, v in item.items() if k in endpoint_fields})
                for item in coerced["acoustid_endpoints"]
                if isinstance(item, dict)
            )
        filtered["metadata"] = MetadataConfig(**coerced)

    watch_raw = filtered.get("watch")
    if isinstance(watch_raw, dict):
        watch_fields = set(WatchConfig.__dataclass_fields__)
        filtered["watch"] = WatchConfig(
            **{key: value for key, value in watch_raw.items() if key in watch_fields}
        )

    artwork_raw = filtered.get("artwork")
    if isinstance(artwork_raw, dict):
        artwork_fields = set(ArtworkConfig.__dataclass_fields__)
        filtered["artwork"] = ArtworkConfig(
            **{key: value for key, value in artwork_raw.items() if key in artwork_fields}
        )

    acquisition_raw = filtered.get("acquisition")
    if isinstance(acquisition_raw, dict):
        acquisition_fields = set(AcquisitionConfig.__dataclass_fields__)
        coerced = {
            key: value for key, value in acquisition_raw.items() if key in acquisition_fields
        }
        if "enabled_providers" in coerced and isinstance(coerced["enabled_providers"], list):
            coerced["enabled_providers"] = tuple(coerced["enabled_providers"])
        if "provider_order" in coerced and isinstance(coerced["provider_order"], list):
            coerced["provider_order"] = tuple(coerced["provider_order"])
        nicotine_raw = coerced.get("nicotine_plus")
        if isinstance(nicotine_raw, dict):
            nicotine_fields = set(NicotinePlusConfig.__dataclass_fields__)
            coerced["nicotine_plus"] = NicotinePlusConfig(
                **{key: value for key, value in nicotine_raw.items() if key in nicotine_fields}
            )
        prowlarr_raw = coerced.get("prowlarr")
        if isinstance(prowlarr_raw, dict):
            prowlarr_fields = set(ProwlarrConfig.__dataclass_fields__)
            prowlarr_coerced = {
                key: value for key, value in prowlarr_raw.items() if key in prowlarr_fields
            }
            if isinstance(prowlarr_coerced.get("categories"), list):
                prowlarr_coerced["categories"] = tuple(
                    int(c) for c in prowlarr_coerced["categories"]
                )
            coerced["prowlarr"] = ProwlarrConfig(**prowlarr_coerced)
        qbittorrent_raw = coerced.get("qbittorrent")
        if isinstance(qbittorrent_raw, dict):
            qbittorrent_fields = set(QbittorrentConfig.__dataclass_fields__)
            coerced["qbittorrent"] = QbittorrentConfig(
                **{
                    key: value
                    for key, value in qbittorrent_raw.items()
                    if key in qbittorrent_fields
                }
            )
        sabnzbd_raw = coerced.get("sabnzbd")
        if isinstance(sabnzbd_raw, dict):
            sabnzbd_fields = set(SabnzbdConfig.__dataclass_fields__)
            coerced["sabnzbd"] = SabnzbdConfig(
                **{key: value for key, value in sabnzbd_raw.items() if key in sabnzbd_fields}
            )
        filtered["acquisition"] = AcquisitionConfig(**coerced)

    recommendations_raw = filtered.get("recommendations")
    if isinstance(recommendations_raw, dict):
        rec_fields = set(RecommendationConfig.__dataclass_fields__)
        rec_coerced = {
            key: value for key, value in recommendations_raw.items() if key in rec_fields
        }
        if isinstance(rec_coerced.get("enabled_recommenders"), list):
            rec_coerced["enabled_recommenders"] = tuple(rec_coerced["enabled_recommenders"])
        lastfm_raw = rec_coerced.get("lastfm")
        if isinstance(lastfm_raw, dict):
            lastfm_fields = set(LastfmConfig.__dataclass_fields__)
            rec_coerced["lastfm"] = LastfmConfig(
                **{key: value for key, value in lastfm_raw.items() if key in lastfm_fields}
            )
        spotify_raw = rec_coerced.get("spotify")
        if isinstance(spotify_raw, dict):
            spotify_fields = set(SpotifyConfig.__dataclass_fields__)
            spotify_coerced = {
                key: value for key, value in spotify_raw.items() if key in spotify_fields
            }
            if isinstance(spotify_coerced.get("playlist_urls"), list):
                spotify_coerced["playlist_urls"] = tuple(spotify_coerced["playlist_urls"])
            rec_coerced["spotify"] = SpotifyConfig(**spotify_coerced)
        filtered["recommendations"] = RecommendationConfig(**rec_coerced)

    return AppConfig(**filtered)


def load_config(path: Path) -> AppConfig:
    """Load configuration from ``path``, creating it with defaults if missing."""
    if not path.exists():
        config = default_config()
        save_config(config, path)
        return config

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Configuration file at {path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Configuration file at {path} must contain a JSON object.")

    migrated = _migrate(raw)
    config = _from_dict(migrated)

    if migrated is not raw:
        save_config(config, path)

    return config


def save_config(config: AppConfig, path: Path) -> None:
    """Serialize ``config`` to ``path`` as pretty-printed JSON (UTF-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    document = json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n"
    path.write_text(document, encoding="utf-8")

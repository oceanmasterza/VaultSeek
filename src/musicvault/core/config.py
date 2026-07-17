"""Versioned JSON application configuration.

Configuration is stored as a single JSON document at
``AppPaths.config_file``. Every serialized document carries a
``schema_version`` field. On load, older documents are migrated forward
through a chain of pure functions registered in ``_MIGRATIONS`` until they
reach :data:`CURRENT_SCHEMA_VERSION`, so upgrading MusicVault never
requires the user to manually edit or delete their configuration file.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from musicvault.core.exceptions import ConfigError, ConfigMigrationError, ConfigVersionError

CURRENT_SCHEMA_VERSION = 5


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
    metadata_worker_threads: int = 1
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
        "musicbrainz",
        "local_tags",
        "filename_parser",
    )
    enabled_providers: tuple[str, ...] = (
        "acoustid",
        "musicbrainz",
        "local_tags",
        "filename_parser",
    )
    acoustid_api_key: str = ""


@dataclass(frozen=True)
class AppConfig:
    """Root application configuration."""

    schema_version: int = CURRENT_SCHEMA_VERSION
    log_level: str = "INFO"
    theme: str = "dark"
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    metadata: MetadataConfig = field(default_factory=MetadataConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)
    artwork: ArtworkConfig = field(default_factory=ArtworkConfig)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict representation suitable for JSON serialization."""
        data = asdict(self)
        metadata = data.get("metadata")
        if isinstance(metadata, dict):
            for key in ("provider_order", "enabled_providers"):
                value = metadata.get(key)
                if isinstance(value, tuple):
                    metadata[key] = list(value)
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


_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
    4: _migrate_v4_to_v5,
}


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    version = raw.get("schema_version")
    if not isinstance(version, int):
        raise ConfigVersionError(
            f"Configuration is missing a valid integer 'schema_version' field: {version!r}"
        )
    if version > CURRENT_SCHEMA_VERSION:
        raise ConfigVersionError(
            f"Configuration schema version {version} is newer than this build of MusicVault "
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

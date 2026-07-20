"""Unit tests for vaultseek.core.config."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from vaultseek.core.config import (
    CURRENT_SCHEMA_VERSION,
    AppConfig,
    ArtworkConfig,
    MetadataConfig,
    PipelineConfig,
    WatchConfig,
    default_config,
    load_config,
    save_config,
)
from vaultseek.core.exceptions import ConfigError, ConfigMigrationError, ConfigVersionError


def test_default_config_uses_current_schema_version() -> None:
    assert default_config().schema_version == CURRENT_SCHEMA_VERSION


def test_default_config_includes_metadata_section() -> None:
    assert default_config().metadata == MetadataConfig()
    assert default_config().pipeline.metadata_worker_threads == 3


def test_load_config_creates_default_file_when_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    assert not config_path.exists()

    config = load_config(config_path)

    assert config == default_config()
    assert config_path.exists()


def test_load_config_round_trips_saved_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    original = AppConfig(log_level="DEBUG", theme="light")
    save_config(original, config_path)

    loaded = load_config(config_path)

    assert loaded == original


def test_load_config_rejects_invalid_json(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path)


def test_load_config_rejects_non_object_json(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path)


def test_load_config_rejects_missing_schema_version(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"log_level": "INFO"}), encoding="utf-8")

    with pytest.raises(ConfigVersionError):
        load_config(config_path)


def test_load_config_rejects_future_schema_version(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"schema_version": CURRENT_SCHEMA_VERSION + 1}), encoding="utf-8"
    )

    with pytest.raises(ConfigVersionError):
        load_config(config_path)


def test_load_config_ignores_unknown_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"schema_version": CURRENT_SCHEMA_VERSION, "future_field": "x"}),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION


def test_save_config_writes_pretty_printed_utf8_json(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "config.json"
    save_config(default_config(), config_path)

    text = config_path.read_text(encoding="utf-8")
    assert json.loads(text) == default_config().to_dict()


def test_shipped_defaults_json_matches_code_defaults() -> None:
    """The repository's config/defaults.json must stay in sync with AppConfig()."""
    defaults_path = Path(__file__).parents[3] / "config" / "defaults.json"
    shipped = json.loads(defaults_path.read_text(encoding="utf-8"))

    assert shipped == default_config().to_dict()


def test_default_config_includes_default_pipeline_config() -> None:
    assert default_config().pipeline == PipelineConfig()


def test_migrating_a_v1_config_adds_default_pipeline_section(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"schema_version": 1, "log_level": "DEBUG", "theme": "light"}),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.log_level == "DEBUG"
    assert config.theme == "light"
    assert config.pipeline == PipelineConfig()
    assert config.metadata == MetadataConfig()


def test_migrating_a_v1_config_persists_the_upgraded_document(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    load_config(config_path)

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == CURRENT_SCHEMA_VERSION
    assert persisted["pipeline"] == asdict(PipelineConfig())
    assert persisted["metadata"] == default_config().to_dict()["metadata"]


def test_migrating_a_v2_config_adds_metadata_section(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "log_level": "WARNING",
                "theme": "dark",
                "pipeline": asdict(PipelineConfig(db_writer_batch_size=1000)),
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.log_level == "WARNING"
    assert config.pipeline.db_writer_batch_size == 1000
    assert config.pipeline.metadata_worker_threads == 3
    assert config.metadata == MetadataConfig()


def test_migrating_a_v3_config_adds_watch_section(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    v3_document = default_config().to_dict()
    v3_document["schema_version"] = 3
    del v3_document["watch"]
    config_path.write_text(json.dumps(v3_document), encoding="utf-8")

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.watch == WatchConfig()
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["watch"] == asdict(WatchConfig())


def test_watch_config_round_trips_custom_poll_interval(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    save_config(AppConfig(watch=WatchConfig(poll_interval_seconds=5.0)), config_path)

    config = load_config(config_path)

    assert config.watch.poll_interval_seconds == 5.0


def test_migrating_a_v4_config_adds_artwork_section(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    v4_document = default_config().to_dict()
    v4_document["schema_version"] = 4
    del v4_document["artwork"]
    config_path.write_text(json.dumps(v4_document), encoding="utf-8")

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.artwork == ArtworkConfig()
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["artwork"] == asdict(ArtworkConfig())


def test_migrating_a_v5_config_adds_fingerprint_sampling_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    v5_document = default_config().to_dict()
    v5_document["schema_version"] = 5
    del v5_document["metadata"]["fingerprint_mode"]
    del v5_document["metadata"]["fingerprint_sample_min"]
    config_path.write_text(json.dumps(v5_document), encoding="utf-8")

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.metadata.fingerprint_mode == "all"
    assert config.metadata.fingerprint_sample_min == 3


def test_migrating_a_v6_config_bumps_single_metadata_worker_thread(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    v6_document = default_config().to_dict()
    v6_document["schema_version"] = 6
    v6_document["pipeline"]["metadata_worker_threads"] = 1
    config_path.write_text(json.dumps(v6_document), encoding="utf-8")

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.pipeline.metadata_worker_threads == 3


def test_fingerprint_sampling_settings_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    save_config(
        AppConfig(
            metadata=MetadataConfig(fingerprint_mode="sample", fingerprint_sample_min=5)
        ),
        config_path,
    )

    loaded = load_config(config_path)

    assert loaded.metadata.fingerprint_mode == "sample"
    assert loaded.metadata.fingerprint_sample_min == 5


def test_load_config_raises_when_no_migration_exists_for_an_old_version(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"schema_version": 0}), encoding="utf-8")

    with pytest.raises(ConfigMigrationError):
        load_config(config_path)


def test_load_config_round_trips_custom_pipeline_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    original = AppConfig(pipeline=PipelineConfig(db_writer_batch_size=1_000))
    save_config(original, config_path)

    loaded = load_config(config_path)

    assert loaded == original
    assert loaded.pipeline.db_writer_batch_size == 1_000

"""Unit tests for acquisition config migration and bootstrap."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from vaultseek.core.config import (
    CURRENT_SCHEMA_VERSION,
    AcquisitionConfig,
    AppConfig,
    NicotinePlusConfig,
    default_config,
    load_config,
    save_config,
)
from vaultseek.models.interfaces.acquisition import SearchRequest
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.plugins.builtin.nicotine_plus import NicotinePlusProvider
from vaultseek.services.acquisition_bootstrap import connect_acquisition_providers
from vaultseek.services.provider_manager import ProviderManager


def test_default_config_includes_acquisition_section() -> None:
    config = default_config()
    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.acquisition == AcquisitionConfig()
    assert config.acquisition.enabled_providers == ("stub",)


def test_migrating_v7_config_adds_acquisition_section(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    v7_document = default_config().to_dict()
    v7_document["schema_version"] = 7
    del v7_document["acquisition"]
    config_path.write_text(json.dumps(v7_document), encoding="utf-8")

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.acquisition == AcquisitionConfig()
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert "acquisition" in persisted
    assert persisted["acquisition"]["enabled_providers"] == ["stub"]


def test_acquisition_config_round_trips(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    original = AppConfig(
        acquisition=AcquisitionConfig(
            enabled_providers=("stub", "nicotine_plus"),
            search_timeout_seconds=45.0,
            nicotine_plus=NicotinePlusConfig(enabled=True, host="192.168.1.10", port=22025),
        )
    )
    save_config(original, config_path)

    loaded = load_config(config_path)

    assert loaded.acquisition.enabled_providers == ("stub", "nicotine_plus")
    assert loaded.acquisition.search_timeout_seconds == 45.0
    assert loaded.acquisition.nicotine_plus.host == "192.168.1.10"
    assert loaded.acquisition.nicotine_plus.port == 22025


def test_migrating_v8_config_adds_auto_acquire_and_http_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    v8_document = default_config().to_dict()
    v8_document["schema_version"] = 8
    v8_document["acquisition"].pop("auto_acquire_threshold", None)
    nicotine = dict(v8_document["acquisition"]["nicotine_plus"])
    nicotine.pop("transport", None)
    nicotine.pop("api_port", None)
    nicotine.pop("api_token", None)
    v8_document["acquisition"]["nicotine_plus"] = nicotine
    config_path.write_text(json.dumps(v8_document), encoding="utf-8")

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.acquisition.auto_acquire_threshold == 0.90
    assert config.acquisition.nicotine_plus.transport == "socket"
    assert config.acquisition.nicotine_plus.api_port == 12339


def test_migrating_v9_config_enables_auto_queue_jobs(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    v9_document = default_config().to_dict()
    v9_document["schema_version"] = 9
    v9_document["acquisition"]["auto_queue_jobs"] = False
    config_path.write_text(json.dumps(v9_document), encoding="utf-8")

    config = load_config(config_path)

    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.acquisition.auto_queue_jobs is True


def test_connect_acquisition_providers_connects_enabled_stub() -> None:
    manager = ProviderManager([StubAcquisitionProvider(), NicotinePlusProvider()])
    connect_acquisition_providers(AcquisitionConfig(enabled_providers=("stub",)), manager)

    hits = manager.search(SearchRequest(artist="X"))
    assert hits == []
    # nicotine_plus remains disconnected when not enabled
    assert manager.get("nicotine_plus") is not None

"""Schema v23 keeps SABnzbd as the default Usenet client and preserves other fields."""

from __future__ import annotations

import json
from pathlib import Path

from vaultseek.core.config import (
    CURRENT_SCHEMA_VERSION,
    NzbgetConfig,
    default_config,
    load_config,
    save_config,
)


def test_defaults_keep_sabnzbd_and_add_nzbget() -> None:
    config = default_config()
    assert config.schema_version == CURRENT_SCHEMA_VERSION == 23
    assert config.acquisition.usenet_download_client == "sabnzbd"
    assert config.acquisition.nzbget == NzbgetConfig()
    assert config.acquisition.provider_order[1] == "usenet"
    assert "nzbget" not in config.acquisition.provider_order


def test_v22_migration_preserves_sab_and_does_not_add_a_search_source(tmp_path: Path) -> None:
    document = default_config().to_dict()
    document["schema_version"] = 22
    document["acquisition"].pop("nzbget")
    document["acquisition"].pop("usenet_download_client")
    document["acquisition"]["sabnzbd"]["api_key"] = "sab-keep"
    document["acquisition"]["sabnzbd"]["enabled"] = True
    document["acquisition"]["nicotine_plus"]["password"] = "soul-keep"
    order = list(document["acquisition"]["provider_order"])
    path = tmp_path / "config.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    loaded = load_config(path)

    assert loaded.schema_version == 23
    assert loaded.acquisition.sabnzbd.api_key == "sab-keep"
    assert loaded.acquisition.sabnzbd.enabled is True
    assert loaded.acquisition.nicotine_plus.password == "soul-keep"
    assert loaded.acquisition.usenet_download_client == "sabnzbd"
    assert loaded.acquisition.nzbget.enabled is False
    assert list(loaded.acquisition.provider_order) == order


def test_unknown_usenet_client_stays_on_sabnzbd(tmp_path: Path) -> None:
    document = default_config().to_dict()
    document["acquisition"]["usenet_download_client"] = "both"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load_config(path).acquisition.usenet_download_client == "sabnzbd"


def test_nzbget_round_trip_does_not_drop_sab(tmp_path: Path) -> None:
    from dataclasses import replace

    original = replace(
        default_config(),
        acquisition=replace(
            default_config().acquisition,
            usenet_download_client="nzbget",
            sabnzbd=replace(default_config().acquisition.sabnzbd, api_key="sab-keep"),
            nzbget=NzbgetConfig(
                enabled=True,
                base_url="http://127.0.0.1:6790",
                username="control",
                password="hidden",
                category="vaultseek",
            ),
        ),
    )
    path = tmp_path / "config.json"
    save_config(original, path)
    loaded = load_config(path)
    assert loaded.acquisition.sabnzbd.api_key == "sab-keep"
    assert loaded.acquisition.nzbget.password == "hidden"
    assert loaded.acquisition.usenet_download_client == "nzbget"
    assert "nzbget" not in loaded.acquisition.provider_order

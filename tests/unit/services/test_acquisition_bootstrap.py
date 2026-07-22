"""Tests for acquisition bootstrap helpers."""

from __future__ import annotations

from vaultseek.core.config import AcquisitionConfig, NicotinePlusConfig
from vaultseek.plugins.builtin.nicotine_plus.rpc import FakeRpcClient
from vaultseek.services.acquisition_bootstrap import (
    connect_acquisition_providers,
    normalize_nicotine_settings,
    probe_nicotine_plus_connection,
    resolve_enabled_acquisition_providers,
)
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.plugins.builtin.nicotine_plus import NicotinePlusProvider
from vaultseek.services.provider_manager import ProviderManager


def test_normalize_nicotine_settings_switches_http_when_ports_match() -> None:
    fixed = normalize_nicotine_settings(
        {"transport": "socket", "port": 12339, "api_port": 12339}
    )
    assert fixed["transport"] == "http"
    assert fixed["port"] == 22024


def test_resolve_enabled_providers_drops_stub_when_nicotine_on() -> None:
    config = AcquisitionConfig(
        enabled_providers=("stub",),
        nicotine_plus=NicotinePlusConfig(enabled=True),
    )
    assert resolve_enabled_acquisition_providers(config) == {"nicotine_plus"}


def test_connect_skips_stub_when_nicotine_enabled() -> None:
    manager = ProviderManager([StubAcquisitionProvider(), NicotinePlusProvider(rpc_client=FakeRpcClient())])
    config = AcquisitionConfig(
        enabled_providers=("stub", "nicotine_plus"),
        nicotine_plus=NicotinePlusConfig(enabled=True),
    )
    connect_acquisition_providers(config, manager)
    assert manager.connected_provider_ids() == ("nicotine_plus",)


def test_probe_nicotine_socket_unreachable() -> None:
    result = probe_nicotine_plus_connection(
        host="127.0.0.1",
        port=1,
        transport="socket",
        api_port=12339,
        timeout_seconds=0.05,
    )
    assert result.ok is False
    assert "NDJSON" in result.message


def test_probe_nicotine_http_unreachable() -> None:
    result = probe_nicotine_plus_connection(
        host="127.0.0.1",
        port=22024,
        transport="http",
        api_port=1,
        timeout_seconds=0.05,
    )
    assert result.ok is False
    assert "api-nicotine-plus" in result.message


def test_probe_nicotine_fake_rpc_success() -> None:
    provider_settings = {
        "host": "127.0.0.1",
        "port": 22024,
        "transport": "socket",
        "api_port": 12339,
    }
    # Exercise provider path via direct connect (probe uses fresh provider).
    from vaultseek.models.interfaces.acquisition import AcquisitionProviderConfig
    from vaultseek.plugins.builtin.nicotine_plus import NicotinePlusProvider

    provider = NicotinePlusProvider(rpc_client=FakeRpcClient())
    assert provider.connect(
        AcquisitionProviderConfig(
            provider_id="nicotine_plus",
            enabled=True,
            settings=provider_settings,
        )
    )

"""Tests for acquisition bootstrap helpers."""

from __future__ import annotations

from vaultseek.plugins.builtin.nicotine_plus.rpc import FakeRpcClient
from vaultseek.services.acquisition_bootstrap import probe_nicotine_plus_connection


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

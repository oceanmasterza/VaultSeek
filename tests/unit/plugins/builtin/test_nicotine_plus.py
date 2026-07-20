"""Unit tests for NicotinePlusProvider skeleton."""

from __future__ import annotations

from unittest.mock import patch

from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    SearchRequest,
    SearchResult,
)
from vaultseek.plugins.builtin.nicotine_plus import NicotinePlusProvider


def test_connect_fails_gracefully_when_host_unreachable() -> None:
    provider = NicotinePlusProvider(connect_timeout_seconds=0.05)
    with patch.object(provider, "_probe_host", return_value=False):
        ok = provider.connect(
            AcquisitionProviderConfig(
                provider_id="nicotine_plus",
                enabled=True,
                settings={"host": "127.0.0.1", "port": 1},
            )
        )
    assert ok is False
    assert provider.search(SearchRequest(artist="Pink Floyd")) == []


def test_connect_succeeds_when_probe_ok() -> None:
    provider = NicotinePlusProvider()
    with patch.object(provider, "_probe_host", return_value=True):
        ok = provider.connect(
            AcquisitionProviderConfig(
                provider_id="nicotine_plus",
                enabled=True,
                settings={"host": "127.0.0.1", "port": 22024},
            )
        )
    assert ok is True
    assert provider.search(SearchRequest(album="The Wall")) == []


def test_download_status_reports_not_implemented_when_connected() -> None:
    provider = NicotinePlusProvider()
    with patch.object(provider, "_probe_host", return_value=True):
        provider.connect(
            AcquisitionProviderConfig(provider_id="nicotine_plus", enabled=True)
        )
    handle = provider.download(
        SearchResult(
            provider_id="nicotine_plus",
            result_id="r1",
            display_name="Pink Floyd - The Wall",
        )
    )
    status = provider.get_status(handle)
    assert status.state == "failed"
    assert "not implemented" in status.message.lower()


def test_disabled_config_does_not_connect() -> None:
    provider = NicotinePlusProvider()
    ok = provider.connect(
        AcquisitionProviderConfig(provider_id="nicotine_plus", enabled=False)
    )
    assert ok is False

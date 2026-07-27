"""Unit tests for ProviderManager and the acquisition stub."""

from __future__ import annotations

from vaultseek.models.interfaces.acquisition import AcquisitionProviderConfig, SearchRequest
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.services.provider_manager import ProviderManager


def test_stub_connect_and_empty_search() -> None:
    stub = StubAcquisitionProvider()
    manager = ProviderManager([stub])
    assert manager.connect(AcquisitionProviderConfig(provider_id="stub")) is True
    assert manager.search(SearchRequest(artist="A", album="B")) == []
    manager.disconnect()
    assert manager.search(SearchRequest(artist="A", album="B")) == []


def test_unknown_provider_connect_fails() -> None:
    manager = ProviderManager([StubAcquisitionProvider()])
    assert manager.connect(AcquisitionProviderConfig(provider_id="missing")) is False


def test_search_continues_when_one_provider_throttled() -> None:
    from vaultseek.models.interfaces.acquisition import (
        ProviderCapabilities,
        SearchResult,
    )
    from vaultseek.plugins.builtin.nicotine_plus.search_rate_gate import SearchThrottled

    class _Throttle:
        provider_id = "nicotine_plus"
        display_name = "N"
        capabilities = ProviderCapabilities(search=True, download=False)

        def connect(self, config):  # noqa: ANN001
            return True

        def disconnect(self) -> None:
            return None

        def search(self, request):  # noqa: ANN001
            raise SearchThrottled(12.0)

    class _Ok:
        provider_id = "prowlarr"
        display_name = "P"
        capabilities = ProviderCapabilities(search=True, download=False)

        def connect(self, config):  # noqa: ANN001
            return True

        def disconnect(self) -> None:
            return None

        def search(self, request):  # noqa: ANN001
            return [
                SearchResult(
                    provider_id="prowlarr",
                    result_id="1",
                    display_name="hit",
                    album=request.album,
                )
            ]

    manager = ProviderManager([_Throttle(), _Ok()], provider_order=("nicotine_plus", "prowlarr"))
    manager.connect(AcquisitionProviderConfig(provider_id="nicotine_plus", enabled=True))
    manager.connect(AcquisitionProviderConfig(provider_id="prowlarr", enabled=True))
    hits = manager.search(SearchRequest(artist="A", album="B", title="T"))
    assert len(hits) == 1
    assert hits[0].provider_id == "prowlarr"

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

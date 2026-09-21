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
    from vaultseek.plugins.builtin.nicotine_plus.search_rate_gate import SearchThrottleError

    class _Throttle:
        provider_id = "nicotine_plus"
        display_name = "N"
        capabilities = ProviderCapabilities(search=True, download=False)

        def connect(self, config):  # noqa: ANN001
            return True

        def disconnect(self) -> None:
            return None

        def search(self, request):  # noqa: ANN001
            raise SearchThrottleError(12.0)

    class _Ok:
        provider_id = "prowlarr_public"
        display_name = "P"
        capabilities = ProviderCapabilities(search=True, download=False)

        def connect(self, config):  # noqa: ANN001
            return True

        def disconnect(self) -> None:
            return None

        def search(self, request):  # noqa: ANN001
            return [
                SearchResult(
                    provider_id="prowlarr_public",
                    result_id="1",
                    display_name="hit",
                    album=request.album,
                )
            ]

    manager = ProviderManager(
        [_Throttle(), _Ok()],
        provider_order=("nicotine_plus", "prowlarr_public"),
        search_waterfall=True,
        provider_search_delay_seconds=0.0,
    )
    manager.connect(AcquisitionProviderConfig(provider_id="nicotine_plus", enabled=True))
    manager.connect(AcquisitionProviderConfig(provider_id="prowlarr_public", enabled=True))
    hits = manager.search(SearchRequest(artist="A", album="B", title="T"))
    assert len(hits) == 1
    assert hits[0].provider_id == "prowlarr_public"


def test_search_waterfall_stops_after_first_hits() -> None:
    from vaultseek.models.interfaces.acquisition import ProviderCapabilities, SearchResult

    calls: list[str] = []

    class _Empty:
        provider_id = "nicotine_plus"
        display_name = "N"
        capabilities = ProviderCapabilities(search=True, download=False)

        def connect(self, config):  # noqa: ANN001
            return True

        def disconnect(self) -> None:
            return None

        def search(self, request):  # noqa: ANN001
            calls.append(self.provider_id)
            return []

    class _Hit:
        provider_id = "usenet"
        display_name = "U"
        capabilities = ProviderCapabilities(search=True, download=False)

        def connect(self, config):  # noqa: ANN001
            return True

        def disconnect(self) -> None:
            return None

        def search(self, request):  # noqa: ANN001
            calls.append(self.provider_id)
            return [
                SearchResult(
                    provider_id="usenet",
                    result_id="1",
                    display_name="nzb",
                    album=request.album,
                )
            ]

    class _Never:
        provider_id = "prowlarr_public"
        display_name = "P"
        capabilities = ProviderCapabilities(search=True, download=False)

        def connect(self, config):  # noqa: ANN001
            return True

        def disconnect(self) -> None:
            return None

        def search(self, request):  # noqa: ANN001
            calls.append(self.provider_id)
            return [
                SearchResult(
                    provider_id="prowlarr_public",
                    result_id="2",
                    display_name="torrent",
                )
            ]

    manager = ProviderManager(
        [_Empty(), _Hit(), _Never()],
        provider_order=("nicotine_plus", "usenet", "prowlarr_public"),
        search_waterfall=True,
        provider_search_delay_seconds=0.0,
    )
    for pid in ("nicotine_plus", "usenet", "prowlarr_public"):
        manager.connect(AcquisitionProviderConfig(provider_id=pid, enabled=True))
    hits = manager.search(SearchRequest(artist="A", album="B"))
    assert [h.provider_id for h in hits] == ["usenet"]
    assert calls == ["nicotine_plus", "usenet"]


def test_lifecycle_serializes_reconnect_against_search() -> None:
    """Settings/Plugins reconnect and search must not interleave provider mutation."""
    from threading import Event, Thread

    from vaultseek.models.interfaces.acquisition import ProviderCapabilities, SearchResult

    search_entered = Event()
    allow_search_finish = Event()
    order: list[str] = []

    class _Slow:
        provider_id = "stub"
        display_name = "S"
        capabilities = ProviderCapabilities(search=True, download=False)

        def connect(self, config):  # noqa: ANN001
            order.append("connect")
            return True

        def disconnect(self) -> None:
            order.append("disconnect")

        def search(self, request):  # noqa: ANN001
            order.append("search-start")
            search_entered.set()
            allow_search_finish.wait(2)
            order.append("search-end")
            return [
                SearchResult(
                    provider_id="stub",
                    result_id="1",
                    display_name="hit",
                    album=request.album,
                )
            ]

    manager = ProviderManager([_Slow()], provider_order=("stub",), search_waterfall=True)
    manager.connect(AcquisitionProviderConfig(provider_id="stub", enabled=True))

    def run_search() -> None:
        manager.search(SearchRequest(artist="A", album="B"))

    searcher = Thread(target=run_search)
    searcher.start()
    assert search_entered.wait(2)

    def run_reconnect() -> None:
        with manager.lifecycle():
            order.append("reconnect-start")
            manager.disconnect("stub")
            manager.connect(AcquisitionProviderConfig(provider_id="stub", enabled=True))
            order.append("reconnect-end")

    reconnect = Thread(target=run_reconnect)
    reconnect.start()
    # Reconnect must not progress until search releases the lifecycle lock.
    assert "reconnect-start" not in order
    allow_search_finish.set()
    searcher.join(timeout=2)
    reconnect.join(timeout=2)
    assert order.index("search-end") < order.index("reconnect-start")
    assert "reconnect-end" in order


def test_status_returns_promptly_during_blocked_search() -> None:
    """Dashboard status must not wait on the lifecycle lock held by search."""
    from threading import Event, Thread
    from time import monotonic

    from vaultseek.models.interfaces.acquisition import ProviderCapabilities, SearchResult

    search_entered = Event()
    allow_search_finish = Event()

    class _Slow:
        provider_id = "usenet"
        display_name = "U"
        capabilities = ProviderCapabilities(search=True, download=False)

        def connect(self, config):  # noqa: ANN001
            return True

        def disconnect(self) -> None:
            return None

        def search(self, request):  # noqa: ANN001
            search_entered.set()
            allow_search_finish.wait(3)
            return [
                SearchResult(
                    provider_id="usenet",
                    result_id="1",
                    display_name="hit",
                    album=request.album,
                )
            ]

    manager = ProviderManager([_Slow()], provider_order=("usenet",), search_waterfall=True)
    manager.connect(AcquisitionProviderConfig(provider_id="usenet", enabled=True))

    def run_search() -> None:
        manager.search(SearchRequest(artist="A", album="B"))

    searcher = Thread(target=run_search)
    searcher.start()
    assert search_entered.wait(2)

    started = monotonic()
    assert manager.connected_provider_ids() == ("usenet",)
    assert manager.has_connected_search_providers() is True
    elapsed = monotonic() - started
    assert elapsed < 0.25, f"status blocked for {elapsed:.3f}s during search"

    allow_search_finish.set()
    searcher.join(timeout=2)
    assert not searcher.is_alive()


def test_status_returns_promptly_during_blocked_reconnect() -> None:
    """Dashboard status must not wait on lifecycle held by a slow reconnect."""
    from threading import Event, Thread
    from time import monotonic

    from vaultseek.models.interfaces.acquisition import ProviderCapabilities

    connect_entered = Event()
    allow_connect_finish = Event()

    class _SlowConnect:
        provider_id = "usenet"
        display_name = "U"
        capabilities = ProviderCapabilities(search=True, download=False)

        def connect(self, config):  # noqa: ANN001
            connect_entered.set()
            allow_connect_finish.wait(3)
            return True

        def disconnect(self) -> None:
            return None

        def search(self, request):  # noqa: ANN001
            return []

    manager = ProviderManager([_SlowConnect()], provider_order=("usenet",))
    # Seed connected so the GUI has a prior snapshot while reconnect blocks.
    allow_connect_finish.set()
    assert manager.connect(AcquisitionProviderConfig(provider_id="usenet", enabled=True))
    allow_connect_finish.clear()
    connect_entered.clear()

    def run_reconnect() -> None:
        with manager.lifecycle():
            manager.disconnect("usenet")
            manager.connect(AcquisitionProviderConfig(provider_id="usenet", enabled=True))

    worker = Thread(target=run_reconnect)
    worker.start()
    assert connect_entered.wait(2)

    started = monotonic()
    # Snapshot may be empty after disconnect published; must still return fast.
    _ = manager.connected_provider_ids()
    _ = manager.has_connected_search_providers()
    elapsed = monotonic() - started
    assert elapsed < 0.25, f"status blocked for {elapsed:.3f}s during reconnect"

    allow_connect_finish.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert manager.connected_provider_ids() == ("usenet",)

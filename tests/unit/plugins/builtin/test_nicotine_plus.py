"""Unit tests for NicotinePlusProvider and RPC transports."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from unittest.mock import patch

from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    SearchRequest,
    SearchResult,
)
from vaultseek.plugins.builtin.nicotine_plus import (
    FakeRpcClient,
    LocalSocketRpcClient,
    NicotinePlusProvider,
    RpcSearchHit,
)


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
    assert isinstance(provider.rpc_client, LocalSocketRpcClient)


def test_download_status_fails_gracefully_when_rpc_offline() -> None:
    client = LocalSocketRpcClient(host="127.0.0.1", port=1, timeout_seconds=0.05)
    provider = NicotinePlusProvider(rpc_client=client)
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
    assert "unreachable" in status.message.lower()


def test_disabled_config_does_not_connect() -> None:
    provider = NicotinePlusProvider()
    ok = provider.connect(
        AcquisitionProviderConfig(provider_id="nicotine_plus", enabled=False)
    )
    assert ok is False


def test_fake_rpc_client_returns_search_hits() -> None:
    fake = FakeRpcClient(
        [
            RpcSearchHit(
                result_id="hit1",
                display_name="Pink Floyd - Hey You",
                artist="Pink Floyd",
                title="Hey You",
                format="FLAC",
            )
        ]
    )
    provider = NicotinePlusProvider(rpc_client=fake)
    provider.connect(AcquisitionProviderConfig(provider_id="nicotine_plus", enabled=True))

    results = provider.search(SearchRequest(artist="Pink Floyd", title="Hey You"))

    assert len(results) == 1
    assert results[0].result_id == "hit1"
    assert results[0].format == "FLAC"
    assert len(fake.search_calls) == 1


def test_fake_rpc_client_completes_download(tmp_path: Path) -> None:
    audio = tmp_path / "track.flac"
    audio.write_bytes(b"flac")
    fake = FakeRpcClient(complete_paths=[audio])
    provider = NicotinePlusProvider(rpc_client=fake)
    provider.connect(AcquisitionProviderConfig(provider_id="nicotine_plus", enabled=True))

    handle = provider.download(
        SearchResult(
            provider_id="nicotine_plus",
            result_id="hit1",
            display_name="track",
        )
    )
    status = provider.get_status(handle)

    assert status.state == "completed"
    assert status.local_paths == (audio,)


def test_local_socket_rpc_round_trip() -> None:
    """LocalSocketRpcClient speaks NDJSON against a tiny echo peer."""

    def handle(conn: socket.socket) -> None:
        with conn:
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            req = json.loads(data.decode("utf-8").split("\n", 1)[0])
            if req["method"] == "search":
                body = {
                    "id": req["id"],
                    "ok": True,
                    "result": {
                        "hits": [
                            {
                                "result_id": "h1",
                                "display_name": "Artist - Title",
                                "artist": "Artist",
                                "title": "Title",
                                "format": "flac",
                                "username": "peer",
                            }
                        ]
                    },
                }
            elif req["method"] == "enqueue_download":
                body = {
                    "id": req["id"],
                    "ok": True,
                    "result": {"download_id": "dl-1"},
                }
            elif req["method"] == "download_status":
                body = {
                    "id": req["id"],
                    "ok": True,
                    "result": {
                        "state": "completed",
                        "progress": 1.0,
                        "message": "",
                        "local_paths": ["C:/tmp/a.flac"],
                    },
                }
            else:
                body = {"id": req["id"], "ok": True, "result": {"cancelled": True}}
            conn.sendall((json.dumps(body) + "\n").encode("utf-8"))

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()

    def accept_loop() -> None:
        for _ in range(4):
            conn, _ = server.accept()
            handle(conn)

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    try:
        client = LocalSocketRpcClient(host=host, port=port, timeout_seconds=2.0)
        hits = client.search(SearchRequest(artist="Artist", title="Title"))
        assert len(hits) == 1
        assert hits[0].result_id == "h1"
        assert hits[0].source_user == "peer"

        download_id = client.enqueue_download("h1", raw={"username": "peer"})
        assert download_id == "dl-1"
        status = client.download_status(download_id)
        assert status.state == "completed"
        assert status.local_paths == (Path("C:/tmp/a.flac"),)
        assert client.cancel(download_id) is True
    finally:
        server.close()
        thread.join(timeout=2.0)


def test_local_socket_rpc_search_empty_when_offline() -> None:
    client = LocalSocketRpcClient(host="127.0.0.1", port=1, timeout_seconds=0.05)
    assert client.search(SearchRequest(artist="x")) == []
    assert client.cancel("any") is False

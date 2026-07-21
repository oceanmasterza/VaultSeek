"""Unit tests for HttpApiRpcClient."""

from __future__ import annotations

from unittest.mock import patch

from vaultseek.models.interfaces.acquisition import SearchRequest
from vaultseek.plugins.builtin.nicotine_plus.http_api_rpc import HttpApiRpcClient


def test_probe_returns_true_on_health_ok() -> None:
    client = HttpApiRpcClient()
    with patch.object(client, "_get", return_value={"status": "ok"}):
        assert client.probe() is True


def test_probe_returns_false_on_error() -> None:
    client = HttpApiRpcClient()
    with patch.object(client, "_get", side_effect=OSError("offline")):
        assert client.probe() is False


def test_search_maps_http_results() -> None:
    client = HttpApiRpcClient()
    with patch.object(client, "_post", return_value={"token": 42}):
        with patch.object(
            client,
            "_get",
            return_value={
                "items": [
                    {
                        "username": "peer",
                        "file_path": "Music/Artist/Track.flac",
                        "size": 1234,
                        "extension": "flac",
                    }
                ]
            },
        ):
            hits = client.search(SearchRequest(artist="Artist", title="Track"))

    assert len(hits) == 1
    assert hits[0].result_id == "42:0"
    assert hits[0].source_user == "peer"
    assert hits[0].format == "flac"


def test_enqueue_download_uses_search_download() -> None:
    client = HttpApiRpcClient()
    with patch.object(client, "_post") as post:
        download_id = client.enqueue_download("99:3", raw={})
    assert download_id == "99:3"
    post.assert_called_once_with("/search/download", {"token": 99, "index": 3})


def test_download_status_maps_finished_transfer() -> None:
    client = HttpApiRpcClient()
    with patch.object(
        client,
        "_get",
        return_value={
            "items": [
                {
                    "token": 7,
                    "status": "Finished",
                    "progress_pct": 100.0,
                    "folder_path": "C:/downloads",
                    "virtual_path": "Music\\\\Artist\\\\Track.flac",
                }
            ]
        },
    ):
        state = client.download_status("7:0")

    assert state.state == "completed"
    assert state.progress == 1.0
    assert state.local_paths[0].name == "Track.flac"


def test_cancel_is_not_supported() -> None:
    assert HttpApiRpcClient().cancel("any") is False

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


def test_search_polls_until_results_arrive() -> None:
    client = HttpApiRpcClient()
    empty = {"items": []}
    populated = {
        "items": [
            {
                "username": "peer",
                "file_path": "Music/Artist/Track.flac",
                "size": 1234,
                "extension": "flac",
            }
        ]
    }
    responses = [empty, empty, populated, populated]

    def _get(*_a: object, **_k: object) -> dict:
        if responses:
            return responses.pop(0)
        return populated

    with patch.object(client, "_post", return_value={"token": 42}):
        with patch.object(client, "_get", side_effect=_get):
            with patch(
                "vaultseek.plugins.builtin.nicotine_plus.http_api_rpc.time.sleep"
            ):
                hits = client.search(
                    SearchRequest(artist="Artist", title="Track"),
                    wait_seconds=10.0,
                    poll_interval=0.5,
                )

    assert len(hits) == 1
    assert hits[0].result_id == "42:0"
    assert hits[0].source_user == "peer"
    assert hits[0].format == "flac"


def test_search_returns_empty_after_timeout_with_no_hits() -> None:
    client = HttpApiRpcClient()
    with patch.object(client, "_post", return_value={"token": 7}):
        with patch.object(client, "_get", return_value={"items": []}) as get:
            with patch(
                "vaultseek.plugins.builtin.nicotine_plus.http_api_rpc.time.sleep"
            ) as sleep:
                hits = client.search(
                    SearchRequest(artist="Nobody"),
                    wait_seconds=0.0,
                    poll_interval=0.5,
                )
    assert hits == []
    assert get.call_count == 1
    sleep.assert_not_called()


def test_enqueue_download_returns_username_path() -> None:
    client = HttpApiRpcClient()
    with patch.object(
        client,
        "_post",
        return_value={
            "ok": True,
            "username": "peer",
            "virtual_path": "Music\\Artist\\Track.flac",
            "queued": True,
        },
    ) as post:
        download_id = client.enqueue_download("99:3", raw={})
    assert download_id == "peer:Music\\Artist\\Track.flac"
    assert post.call_args_list[0].args == ("/search/download", {"token": 99, "index": 3})
    assert post.call_args_list[1].args == ("/search/close", {"token": 99})


def test_download_status_maps_finished_transfer() -> None:
    client = HttpApiRpcClient()
    with patch.object(
        client,
        "_get",
        return_value={
            "items": [
                {
                    "username": "peer",
                    "status": "Finished",
                    "progress_pct": 100.0,
                    "folder_path": "C:/downloads",
                    "virtual_path": "Music\\\\Artist\\\\Track.flac",
                }
            ]
        },
    ):
        state = client.download_status("peer:Music\\\\Artist\\\\Track.flac")

    assert state.state == "completed"
    assert state.progress == 1.0
    assert state.local_paths[0].name == "Track.flac"


def test_download_status_queued_when_transfer_not_listed_yet() -> None:
    client = HttpApiRpcClient()
    with patch.object(client, "_get", return_value={"items": []}):
        state = client.download_status("peer:Music/Track.flac")
    assert state.state == "queued"


def test_cancel_is_not_supported() -> None:
    assert HttpApiRpcClient().cancel("any") is False

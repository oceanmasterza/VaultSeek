"""NZBGet JSON-RPC client: permissions, queue, history, cancel, and completion."""

from __future__ import annotations

import json
from pathlib import Path

import responses

from vaultseek.plugins.builtin.nzbget import NzbgetClient

_URL = "http://nzbget:6789/jsonrpc"


def _post(payload: dict[str, object] | str, *, status: int = 200) -> None:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    responses.add(responses.POST, _URL, body=body, status=status, content_type="application/json")


@responses.activate
def test_version_without_queue_is_add_only() -> None:
    _post({"result": "26.3"})
    _post({"error": {"code": 1, "message": "Access denied"}})
    access = NzbgetClient(_URL.removesuffix("/jsonrpc"), "add-user", "secret").probe_access()
    assert access.ok is False
    assert access.level == "add_only"
    assert "control" in access.message.casefold()
    assert "secret" not in access.message


@responses.activate
def test_control_login_can_list_the_queue() -> None:
    _post({"result": "26.3"})
    _post({"result": []})
    access = NzbgetClient("http://nzbget:6789", "control", "secret").probe_access()
    assert access.ok is True
    assert access.level == "ready"
    assert "secret" not in responses.calls[0].request.url


@responses.activate
def test_rejected_password_is_not_ready() -> None:
    _post({"error": {"message": "Unauthorized"}}, status=401)
    access = NzbgetClient("http://nzbget:6789", "control", "nope").probe_access()
    assert access.level == "denied"
    assert access.ok is False


@responses.activate
def test_malformed_json_is_reported() -> None:
    _post("not-json")
    access = NzbgetClient("http://nzbget:6789", "control", "secret").probe_access()
    assert access.level == "malformed"
    assert access.ok is False


@responses.activate
def test_append_is_positional_and_zero_is_not_a_handle() -> None:
    seen: dict[str, object] = {}

    def capture(request: responses.Response) -> tuple[int, dict[str, str], str]:
        body = json.loads(request.body or "")
        seen["keys"] = list(body)
        seen["params"] = body["params"]
        return (200, {}, json.dumps({"result": 0}))

    responses.add_callback(responses.POST, _URL, callback=capture)
    client = NzbgetClient("http://nzbget:6789", "control", "secret")
    try:
        client.append_url("http://example/album.nzb", category="vaultseek")
    except ConnectionError as exc:
        assert "rejected" in str(exc).casefold()
    else:
        raise AssertionError("zero NZBID must not become a download handle")
    assert seen["keys"] == ["jsonrpc", "id", "method", "params"]
    params = seen["params"]
    assert isinstance(params, list)
    assert params[1] == "http://example/album.nzb"
    assert params[2] == "vaultseek"
    assert params[9] is False
    assert params[10] == []
    assert len(responses.calls) == 1


@responses.activate
def test_queue_post_processing_is_not_complete() -> None:
    _post(
        {
            "result": [
                {
                    "NZBID": 7,
                    "Status": "PP_QUEUED",
                    "FileSizeLo": 1000,
                    "FileSizeHi": 0,
                    "RemainingSizeLo": 0,
                    "RemainingSizeHi": 0,
                    "PostStageProgress": 200,
                    "DestDir": "C:/incomplete",
                }
            ]
        }
    )
    _post({"result": []})
    item = NzbgetClient("http://nzbget:6789", "u", "p").find(7)
    assert item is not None
    mapped = NzbgetClient("http://nzbget:6789", "u", "p").map_status(item)
    assert mapped.state == "downloading"
    assert mapped.state != "completed"


@responses.activate
def test_history_success_deleted_and_missing(tmp_path: Path) -> None:
    album = tmp_path / "Album"
    album.mkdir()
    (album / "01.flac").write_bytes(b"flac")
    history = {
        "result": [
            {"NZBID": 7, "Status": "SUCCESS/ALL", "FinalDir": str(album), "Name": "Album"},
            {"NZBID": 8, "Status": "DELETED/MANUAL", "DestDir": str(album)},
            {"NZBID": 9, "Status": "FAILURE/UNPACK", "DestDir": str(album)},
        ]
    }
    calls = {"n": 0}

    def respond(_request: object) -> tuple[int, dict[str, str], str]:
        calls["n"] += 1
        payload = {"result": []} if calls["n"] % 2 == 1 else history
        return (200, {}, json.dumps(payload))

    responses.add_callback(responses.POST, _URL, callback=respond)
    client = NzbgetClient("http://nzbget:6789", "u", "p")
    success = client.find(7)
    deleted = client.find(8)
    failed = client.find(9)
    missing = client.find(10)
    assert success is not None and deleted is not None and failed is not None
    assert missing is None
    done = client.map_status(success)
    assert done.state == "completed"
    assert done.local_paths == (album / "01.flac",)
    assert client.map_status(deleted).state == "failed"
    assert client.map_status(failed).state == "failed"


@responses.activate
def test_cancel_uses_group_delete() -> None:
    seen: list[object] = []

    def capture(request: responses.Response) -> tuple[int, dict[str, str], str]:
        body = json.loads(request.body or "")
        seen.append(body["params"])
        return (200, {}, json.dumps({"result": True}))

    responses.add_callback(responses.POST, _URL, callback=capture)
    assert NzbgetClient("http://nzbget:6789", "u", "p").delete(7) is True
    assert seen == [["GroupDelete", "", [7]]]

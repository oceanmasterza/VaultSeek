"""VaultSeek NDJSON proxy for Nicotine+ socket transport.

VaultSeek's `LocalSocketRpcClient` expects a tiny line-delimited JSON
protocol (NDJSON) on a TCP port.

Nicotine+ itself does not provide a stable socket/RPC interface; instead,
this proxy forwards to the community `api-nicotine-plus` HTTP plugin
(default `127.0.0.1:12339`) and exposes the NDJSON interface expected by
VaultSeek on another port (default `127.0.0.1:22024`).

Run the proxy:

  python scripts/nicotine_plus_ndjson_proxy.py \
    --listen-host 127.0.0.1 --listen-port 22024 \
    --http-host 127.0.0.1 --http-port 12339 \
    --api-token YOUR_TOKEN_OR_EMPTY

Then in VaultSeek Settings → Acquisition → Nicotine+ transport:
  * choose "VaultSeek NDJSON socket"
  * set NDJSON port to the listen-port above
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
from pathlib import Path
from typing import Any

from vaultseek.models.interfaces.acquisition import SearchRequest
from vaultseek.plugins.builtin.nicotine_plus.http_api_rpc import HttpApiRpcClient
from vaultseek.plugins.builtin.nicotine_plus.rpc import DEFAULT_RPC_PORT
from vaultseek.plugins.builtin.nicotine_plus.rpc import RpcDownloadState, RpcSearchHit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=DEFAULT_RPC_PORT)
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=12339)
    parser.add_argument("--api-token", default="")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--backlog", type=int, default=10)
    args = parser.parse_args()

    client = HttpApiRpcClient(
        host=args.http_host,
        port=args.http_port,
        api_token=args.api_token,
        timeout_seconds=args.timeout_seconds,
    )

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((args.listen_host, args.listen_port))
    server.listen(args.backlog)
    print(f"VaultSeek NDJSON proxy listening on {args.listen_host}:{args.listen_port}")

    def accept_loop() -> None:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(
                target=_handle_client,
                args=(conn, addr, client),
                daemon=True,
            )
            t.start()

    accept_loop()


def _handle_client(
    conn: socket.socket,
    _addr: Any,
    client: HttpApiRpcClient,
) -> None:
    # Make sure one misbehaving client does not hang the server forever.
    conn.settimeout(30.0)
    try:
        f = conn.makefile("rwb")
        while True:
            line = f.readline()
            if not line:
                return
            payload = json.loads(line.decode("utf-8").strip())
            request_id = str(payload.get("id") or "")
            method = str(payload.get("method") or "")
            params = payload.get("params") or {}
            try:
                result = _dispatch(method, params, client)
                response = {"id": request_id, "ok": True, "result": result}
            except Exception as exc:
                response = {"id": request_id, "ok": False, "error": str(exc)}
            f.write((json.dumps(response) + "\n").encode("utf-8"))
            f.flush()
    except Exception:
        # Ignore client errors and close.
        return
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _dispatch(method: str, params: dict[str, Any], client: HttpApiRpcClient) -> dict[str, Any]:
    method = method.lower().strip()
    if method == "search":
        artist = params.get("artist")
        album = params.get("album")
        title = params.get("title")
        request = SearchRequest(artist=artist, album=album, title=title)
        hits: list[RpcSearchHit] = client.search(request)
        return {"hits": [_hit_to_dict(h) for h in hits]}

    if method == "enqueue_download":
        result_id = str(params.get("result_id") or "")
        raw = params.get("raw") or {}
        download_id = client.enqueue_download(result_id, raw=raw)
        return {"download_id": download_id}

    if method == "download_status":
        download_id = str(params.get("download_id") or "")
        state: RpcDownloadState = client.download_status(download_id)
        return {
            "state": state.state,
            "progress": state.progress,
            "message": state.message,
            "local_paths": [str(p) for p in state.local_paths],
            "download_id": state.download_id,
        }

    if method == "cancel":
        download_id = str(params.get("download_id") or "")
        cancelled = client.cancel(download_id)
        return {"cancelled": bool(cancelled)}

    raise ValueError(f"Unknown method: {method}")


def _hit_to_dict(hit: RpcSearchHit) -> dict[str, Any]:
    return {
        "result_id": hit.result_id,
        "display_name": hit.display_name,
        "artist": hit.artist,
        "album": hit.album,
        "title": hit.title,
        "format": hit.format,
        "bit_depth": hit.bit_depth,
        "size_bytes": hit.size_bytes,
        "track_count": hit.track_count,
        "source_user": hit.source_user,
        "raw": hit.raw,
    }


if __name__ == "__main__":
    main()


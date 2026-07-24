"""In-process Shazamio recognizer (sync wrapper around async API).

Runs inside the main VaultSeek interpreter. Target Python is 3.12 so
``shazamio-core`` Windows wheels install cleanly — no second venv or
per-track subprocess helper.

A shared background event loop serves all routes; each route reuses one
``Shazam`` client and serializes recognizes so the ≤1 req/s community
rate limit holds under multi-threaded metadata workers.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from loguru import logger

_WARNED_UNAVAILABLE = False
_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_THREAD: threading.Thread | None = None
_LOOP_LOCK = threading.Lock()
# One Shazam client per proxy URL (None = direct). Created lazily.
_CLIENTS: dict[str | None, Any] = {}
_CLIENTS_LOCK = threading.Lock()


def recognize_with_shazamio(file_path: str, *, proxy_url: str | None = None) -> dict[str, Any] | None:
    """Run one Shazam recognition. Returns the raw Shazam JSON dict or None."""
    global _WARNED_UNAVAILABLE
    path = Path(file_path).expanduser()
    try:
        path = path.resolve(strict=False)
    except OSError:
        path = Path(file_path)
    if not path.is_file():
        logger.debug("Shazamio skipped — audio file not found: {}", path)
        return None

    try:
        import shazamio  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        if not _WARNED_UNAVAILABLE:
            _WARNED_UNAVAILABLE = True
            logger.warning(
                "Shazamio is enabled but not importable ({}). "
                "Install project deps on Python 3.12+ with shazamio.",
                exc,
            )
        return None

    try:
        return _run_on_loop(_recognize_async(str(path), proxy_url=proxy_url))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Shazamio recognize failed for {}: {}", path.name, exc)
        return None


async def _recognize_async(file_path: str, *, proxy_url: str | None) -> dict[str, Any]:
    shazam = _client_for(proxy_url)
    kwargs: dict[str, Any] = {}
    if proxy_url:
        kwargs["proxy"] = proxy_url
    return await shazam.recognize(file_path, **kwargs)


def _client_for(proxy_url: str | None) -> Any:
    """Reuse one Shazam instance per route (avoids reconnect churn)."""
    key = proxy_url or None
    with _CLIENTS_LOCK:
        existing = _CLIENTS.get(key)
        if existing is not None:
            return existing

        from aiohttp_retry import ExponentialRetry
        from shazamio import HTTPClient, Shazam

        # Modest retries: parent route lock already spaces requests; long
        # exponential backoffs would stall the metadata pipeline.
        client = Shazam(
            http_client=HTTPClient(
                retry_options=ExponentialRetry(
                    attempts=4,
                    max_timeout=30.0,
                    statuses={429, 500, 502, 503, 504},
                ),
            ),
        )
        _CLIENTS[key] = client
        return client


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Start a dedicated asyncio loop thread once (metadata workers are sync)."""
    global _LOOP, _LOOP_THREAD
    with _LOOP_LOCK:
        if _LOOP is not None and _LOOP.is_running():
            return _LOOP

        loop = asyncio.new_event_loop()

        def _runner() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(
            target=_runner,
            name="vaultseek-shazamio-loop",
            daemon=True,
        )
        thread.start()
        _LOOP = loop
        _LOOP_THREAD = thread
        return loop


def _run_on_loop(coro: Any) -> Any:
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=120)

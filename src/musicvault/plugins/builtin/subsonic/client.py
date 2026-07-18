"""Shared Subsonic REST client (Navidrome / generic Subsonic)."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any
from urllib.parse import urljoin

import requests


class SubsonicClient:
    """Minimal Subsonic API client used by Navidrome and generic Subsonic plugins.

    Auth uses the token+salt scheme (API version 1.13.0+). Only the methods
    Phase 15 needs are implemented: ``ping`` and ``startScan``.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout_seconds: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self._base = base_url.rstrip("/") + "/"
        self._username = username
        self._password = password
        self._timeout = timeout_seconds
        self._session = session or requests.Session()

    def ping(self) -> bool:
        data = self._get("ping.view")
        return bool(data.get("status") == "ok")

    def start_scan(self) -> bool:
        data = self._get("startScan.view")
        return bool(data.get("status") == "ok")

    def _get(self, endpoint: str, **params: str) -> dict[str, Any]:
        salt = secrets.token_hex(8)
        token = hashlib.md5(f"{self._password}{salt}".encode(), usedforsecurity=False).hexdigest()
        query = {
            "u": self._username,
            "t": token,
            "s": salt,
            "v": "1.16.1",
            "c": "MusicVault",
            "f": "json",
            **params,
        }
        url = urljoin(self._base, f"rest/{endpoint}")
        response = self._session.get(url, params=query, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {}
        subsonic = payload.get("subsonic-response")
        return subsonic if isinstance(subsonic, dict) else {}

"""SABnzbd API client (mode= JSON endpoints)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass(frozen=True, slots=True)
class SabnzbdSlot:
    nzo_id: str
    status: str
    percentage: float
    name: str = ""
    storage: str = ""
    path: str = ""


@dataclass(frozen=True, slots=True)
class SabnzbdMappedStatus:
    state: str  # queued | downloading | completed | failed
    progress: float
    message: str
    local_paths: tuple[Path, ...] = ()


class SabnzbdClient:
    """Minimal SABnzbd HTTP API client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._session = session or requests.Session()
        self._timeout = timeout_seconds

    def configure(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def _get(self, mode: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "mode": mode,
            "apikey": self._api_key,
            "output": "json",
        }
        if extra:
            params.update(extra)
        url = f"{self._base_url}/api"
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ConnectionError(f"SABnzbd request failed: {exc}") from exc
        if response.status_code != 200:
            raise ConnectionError(f"SABnzbd returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectionError("SABnzbd returned invalid JSON") from exc
        return payload if isinstance(payload, dict) else {}

    def probe(self) -> bool:
        try:
            payload = self._get("version")
        except ConnectionError:
            return False
        return bool(payload.get("version"))

    def add_url(self, url: str, *, category: str = "") -> str:
        """Enqueue an NZB/URL; return the new nzo_id when SABnzbd reports one."""
        extra: dict[str, Any] = {"name": url}
        if category:
            extra["cat"] = category
        payload = self._get("addurl", extra)
        if not payload.get("status", True) and payload.get("error"):
            raise ConnectionError(f"SABnzbd rejected URL: {payload.get('error')}")
        nzo_ids = payload.get("nzo_ids") or []
        if isinstance(nzo_ids, list) and nzo_ids:
            return str(nzo_ids[0])
        # Some builds only return status; fall back to newest queue slot name match.
        return self._newest_queue_id() or url

    def _newest_queue_id(self) -> str:
        slots = self.queue_slots()
        return slots[0].nzo_id if slots else ""

    def queue_slots(self) -> list[SabnzbdSlot]:
        payload = self._get("queue")
        queue = payload.get("queue") or {}
        rows = queue.get("slots") or []
        return [_slot_from_queue(row) for row in rows if isinstance(row, dict)]

    def history_slots(self, *, limit: int = 50) -> list[SabnzbdSlot]:
        payload = self._get("history", {"limit": limit})
        history = payload.get("history") or {}
        rows = history.get("slots") or []
        return [_slot_from_history(row) for row in rows if isinstance(row, dict)]

    def find_slot(self, nzo_id: str) -> SabnzbdSlot | None:
        for slot in self.queue_slots():
            if slot.nzo_id == nzo_id:
                return slot
        for slot in self.history_slots():
            if slot.nzo_id == nzo_id:
                return slot
        return None

    def delete(self, nzo_id: str) -> bool:
        try:
            payload = self._get("queue", {"name": "delete", "value": nzo_id})
        except ConnectionError:
            return False
        return bool(payload.get("status", True))

    def map_status(self, slot: SabnzbdSlot) -> SabnzbdMappedStatus:
        status = (slot.status or "").casefold()
        if status in {"failed", "deleted"}:
            return SabnzbdMappedStatus(
                state="failed",
                progress=slot.percentage / 100.0,
                message=f"SABnzbd status: {slot.status}",
            )
        if status in {"completed", "complete"}:
            paths = _audio_paths_under(slot.storage or slot.path)
            return SabnzbdMappedStatus(
                state="completed",
                progress=1.0,
                message="download complete",
                local_paths=paths,
            )
        if status in {"queued", "paused", "propagating"}:
            return SabnzbdMappedStatus(
                state="queued",
                progress=slot.percentage / 100.0,
                message=f"SABnzbd status: {slot.status}",
            )
        return SabnzbdMappedStatus(
            state="downloading",
            progress=min(1.0, max(0.0, slot.percentage / 100.0)),
            message=f"SABnzbd status: {slot.status}",
        )


_AUDIO_EXTENSIONS = frozenset(
    {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".alac", ".wv", ".ape"}
)


def _slot_from_queue(row: dict[str, Any]) -> SabnzbdSlot:
    try:
        percentage = float(row.get("percentage") or 0.0)
    except (TypeError, ValueError):
        percentage = 0.0
    return SabnzbdSlot(
        nzo_id=str(row.get("nzo_id") or ""),
        status=str(row.get("status") or ""),
        percentage=percentage,
        name=str(row.get("filename") or row.get("name") or ""),
        path=str(row.get("path") or ""),
    )


def _slot_from_history(row: dict[str, Any]) -> SabnzbdSlot:
    return SabnzbdSlot(
        nzo_id=str(row.get("nzo_id") or ""),
        status=str(row.get("status") or "Completed"),
        percentage=100.0,
        name=str(row.get("name") or ""),
        storage=str(row.get("storage") or row.get("path") or ""),
        path=str(row.get("path") or ""),
    )


def _audio_paths_under(root: str) -> tuple[Path, ...]:
    if not root:
        return ()
    base = Path(root)
    if base.is_file():
        return (base,) if base.suffix.casefold() in _AUDIO_EXTENSIONS else ()
    if not base.is_dir():
        return ()
    paths = [
        path
        for path in base.rglob("*")
        if path.is_file() and path.suffix.casefold() in _AUDIO_EXTENSIONS
    ]
    return tuple(sorted(paths))

"""qBittorrent WebUI API (v2) client.

Handles cookie-based login, adding a torrent by magnet or URL, resolving
the resulting info hash, polling status, listing files, and deletion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import requests

# qBittorrent states that mean "done downloading" (seeding/complete/paused-up).
_COMPLETE_STATES = frozenset(
    {"uploading", "stalledUP", "pausedUP", "forcedUP", "queuedUP", "checkingUP"}
)
_ERROR_STATES = frozenset({"error", "missingFiles"})

_MAGNET_BTIH = re.compile(r"xt=urn:btih:([0-9a-zA-Z]+)", re.IGNORECASE)


def infohash_from_magnet(magnet: str) -> str:
    """Return the lowercase hex btih from a magnet link, if 40-char hex."""
    match = _MAGNET_BTIH.search(magnet or "")
    if not match:
        return ""
    value = match.group(1)
    if len(value) == 40 and all(c in "0123456789abcdefABCDEF" for c in value):
        return value.lower()
    # Base32 (32-char) hashes need conversion; leave to diff-based resolution.
    return ""


@dataclass(frozen=True, slots=True)
class QbittorrentTorrent:
    hash: str
    name: str
    state: str
    progress: float
    save_path: str
    content_path: str
    amount_left: int = 0


@dataclass(frozen=True, slots=True)
class QbittorrentFile:
    name: str
    size: int = 0


@dataclass(frozen=True, slots=True)
class MappedStatus:
    """Provider-neutral status derived from a qBittorrent torrent."""

    state: str  # queued | downloading | completed | failed
    progress: float
    message: str
    relative_files: tuple[str, ...] = field(default_factory=tuple)
    save_path: str = ""


class QbittorrentClient:
    """Cookie-authenticated qBittorrent WebUI client."""

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._session = session or requests.Session()
        self._timeout = timeout_seconds
        self._logged_in = False

    def configure(self, base_url: str, username: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._logged_in = False

    def login(self) -> bool:
        url = f"{self._base_url}/api/v2/auth/login"
        try:
            response = self._session.post(
                url,
                data={"username": self._username, "password": self._password},
                headers={"Referer": self._base_url},
                timeout=self._timeout,
            )
        except requests.RequestException:
            self._logged_in = False
            return False
        body = response.text.strip()
        # Classic WebUI: 200 + "Ok.". qBittorrent 5.x with localhost / subnet
        # bypass often returns 204 (or empty body) while the session is already usable.
        if response.status_code == 200 and body == "Ok.":
            self._logged_in = True
            return True
        if response.status_code in (200, 204) and self._version_reachable():
            self._logged_in = True
            return True
        self._logged_in = False
        return False

    def _version_reachable(self) -> bool:
        try:
            response = self._session.get(
                f"{self._base_url}/api/v2/app/version",
                headers={"Referer": self._base_url},
                timeout=self._timeout,
            )
        except requests.RequestException:
            return False
        return response.status_code == 200 and bool(response.text.strip())

    def probe(self) -> bool:
        return self.login()

    def _ensure_login(self) -> None:
        if not self._logged_in and not self.login():
            raise ConnectionError("qBittorrent login failed — check WebUI credentials")

    def list_hashes(self, *, category: str | None = None) -> set[str]:
        return {t.hash for t in self.torrents_info(category=category)}

    def add_torrent(
        self,
        link: str,
        *,
        category: str = "",
        save_path: str = "",
    ) -> None:
        self._ensure_login()
        data: dict[str, str] = {"urls": link}
        if category:
            data["category"] = category
        if save_path:
            data["savepath"] = save_path
        url = f"{self._base_url}/api/v2/torrents/add"
        try:
            response = self._session.post(url, data=data, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ConnectionError(f"qBittorrent add failed: {exc}") from exc
        if response.status_code != 200 or response.text.strip() not in ("Ok.", ""):
            raise ConnectionError(f"qBittorrent rejected torrent (HTTP {response.status_code})")

    def torrents_info(
        self,
        *,
        hashes: str | None = None,
        category: str | None = None,
    ) -> list[QbittorrentTorrent]:
        self._ensure_login()
        params: dict[str, str] = {}
        if hashes:
            params["hashes"] = hashes
        if category is not None:
            params["category"] = category
        url = f"{self._base_url}/api/v2/torrents/info"
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ConnectionError(f"qBittorrent info failed: {exc}") from exc
        if response.status_code != 200:
            raise ConnectionError(f"qBittorrent info returned HTTP {response.status_code}")
        rows = response.json()
        result: list[QbittorrentTorrent] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            result.append(
                QbittorrentTorrent(
                    hash=str(row.get("hash") or "").lower(),
                    name=str(row.get("name") or ""),
                    state=str(row.get("state") or ""),
                    progress=float(row.get("progress") or 0.0),
                    save_path=str(row.get("save_path") or ""),
                    content_path=str(row.get("content_path") or ""),
                    amount_left=int(row.get("amount_left") or 0),
                )
            )
        return result

    def torrent_files(self, torrent_hash: str) -> list[QbittorrentFile]:
        self._ensure_login()
        url = f"{self._base_url}/api/v2/torrents/files"
        try:
            response = self._session.get(url, params={"hash": torrent_hash}, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ConnectionError(f"qBittorrent files failed: {exc}") from exc
        if response.status_code != 200:
            raise ConnectionError(f"qBittorrent files returned HTTP {response.status_code}")
        rows = response.json()
        files: list[QbittorrentFile] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "")
            if not name:
                continue
            files.append(QbittorrentFile(name=name, size=int(row.get("size") or 0)))
        return files

    def delete(self, torrent_hash: str, *, delete_files: bool = False) -> bool:
        self._ensure_login()
        url = f"{self._base_url}/api/v2/torrents/delete"
        try:
            response = self._session.post(
                url,
                data={
                    "hashes": torrent_hash,
                    "deleteFiles": "true" if delete_files else "false",
                },
                timeout=self._timeout,
            )
        except requests.RequestException:
            return False
        return response.status_code == 200

    def map_status(self, torrent: QbittorrentTorrent) -> MappedStatus:
        """Translate a qBittorrent torrent into provider-neutral status."""
        if torrent.state in _ERROR_STATES:
            return MappedStatus(
                state="failed",
                progress=torrent.progress,
                message=f"qBittorrent state: {torrent.state}",
                save_path=torrent.save_path,
            )
        completed = torrent.progress >= 1.0 or torrent.state in _COMPLETE_STATES
        if completed:
            files = tuple(f.name for f in self.torrent_files(torrent.hash))
            return MappedStatus(
                state="completed",
                progress=1.0,
                message="download complete",
                relative_files=files,
                save_path=torrent.save_path,
            )
        if torrent.state in ("queuedDL", "checkingDL", "allocating", "metaDL"):
            return MappedStatus(
                state="queued",
                progress=torrent.progress,
                message=f"qBittorrent state: {torrent.state}",
                save_path=torrent.save_path,
            )
        return MappedStatus(
            state="downloading",
            progress=torrent.progress,
            message=f"qBittorrent state: {torrent.state}",
            save_path=torrent.save_path,
        )

    def find_torrent(self, torrent_hash: str) -> QbittorrentTorrent | None:
        for torrent in self.torrents_info(hashes=torrent_hash):
            if torrent.hash == torrent_hash.lower():
                return torrent
        return None

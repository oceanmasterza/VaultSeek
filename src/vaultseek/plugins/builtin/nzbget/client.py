"""NZBGet JSON-RPC client (positional parameters, HTTP Basic auth).

Per-download state comes from ``listgroups`` and ``history``, not the global
``status`` method. Add-only accounts may call ``version`` and ``append`` but
cannot poll; :meth:`NzbgetClient.probe_access` reports that honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

_QUEUE_PENDING = frozenset({"queued", "paused", "fetching"})
_QUEUE_POST = frozenset(
    {
        "pp_queued",
        "loading_pars",
        "verifying_sources",
        "repairing",
        "verifying_repaired",
        "renaming",
        "unpacking",
        "moving",
        "post_unpack_renaming",
        "post_download_renaming",
        "executing_script",
        "pp_finished",
    }
)
_AUDIO_EXTENSIONS = frozenset(
    {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".alac", ".wv", ".ape"}
)
_PERMISSION_MARKERS = (
    "denied",
    "author",
    "permission",
    "not allowed",
    "restricted",
)


class NzbgetRpcError(ConnectionError):
    """JSON-RPC or transport failure. Messages never include credentials."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        malformed: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.malformed = malformed


@dataclass(frozen=True, slots=True)
class NzbgetAccess:
    """Result of a control-credential check. ``ok`` requires queue listing."""

    ok: bool
    level: str  # ready | add_only | denied | unreachable | malformed
    message: str


@dataclass(frozen=True, slots=True)
class NzbgetItem:
    nzb_id: str
    status: str
    where: str  # queue | history
    progress: float
    dest_dir: str = ""
    name: str = ""


@dataclass(frozen=True, slots=True)
class NzbgetMappedStatus:
    state: str  # queued | downloading | completed | failed
    progress: float
    message: str
    local_paths: tuple[Path, ...] = ()


class NzbgetClient:
    """Minimal NZBGet JSON-RPC client. Does not change NZBGet's configuration."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._session = session or requests.Session()
        self._timeout = timeout_seconds
        self._rpc_id = 0

    def configure(self, base_url: str, username: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password

    def probe(self) -> bool:
        """True only when control credentials can list the queue."""
        return self.probe_access().ok

    def probe_authenticated(self) -> bool:
        """Same as :meth:`probe`. Version-only or add-only logins return False."""
        return self.probe()

    def probe_access(self) -> NzbgetAccess:
        """Distinguish a live control login from an add-only or dead endpoint."""
        try:
            version = self.version()
        except NzbgetRpcError as exc:
            return _access_from_failure(exc)
        if not version:
            return NzbgetAccess(
                ok=False,
                level="unreachable",
                message="NZBGet did not report a version. Check the URL.",
            )
        try:
            self.list_groups()
        except NzbgetRpcError as exc:
            if exc.malformed:
                return _access_from_failure(exc)
            if exc.status_code in {401, 403} or _looks_like_permission(str(exc)):
                return NzbgetAccess(
                    ok=False,
                    level="add_only",
                    message=(
                        "These credentials can reach NZBGet but cannot list the queue. "
                        "An add-only account may append NZBs and read the version, but "
                        "VaultSeek needs the control username and password to poll, "
                        "cancel, and recover downloads."
                    ),
                )
            return NzbgetAccess(
                ok=False,
                level="denied",
                message=str(exc) or "NZBGet refused queue access.",
            )
        return NzbgetAccess(
            ok=True,
            level="ready",
            message=f"NZBGet {version} accepted the control credentials.",
        )

    def version(self) -> str:
        result = self._rpc("version", [])
        return str(result).strip() if result is not None else ""

    def append_url(self, url: str, *, category: str = "") -> str:
        """Queue one URL. A non-positive NZBID is an error; do not guess another id."""
        # Official append order (v25+ / 26.x): Filename, Content, Category,
        # Priority, AddToTop, AddPaused, DupeKey, DupeScore, DupeMode,
        # AutoCategory, PPParameters. A URL is passed as Content, not Base64.
        result = self._rpc(
            "append",
            [
                "",
                url,
                category,
                0,
                False,
                False,
                "",
                0,
                "SCORE",
                False,
                [],
            ],
        )
        if isinstance(result, bool) or not isinstance(result, int | str):
            raise NzbgetRpcError("NZBGet append did not return an NZB id.")
        try:
            nzb_id = int(result)
        except ValueError as exc:
            raise NzbgetRpcError("NZBGet append did not return an NZB id.") from exc
        if nzb_id <= 0:
            raise NzbgetRpcError("NZBGet rejected the NZB and did not queue it.")
        return str(nzb_id)

    def list_groups(self) -> list[dict[str, Any]]:
        return _as_rows(self._rpc("listgroups", [0]))

    def history(self) -> list[dict[str, Any]]:
        return _as_rows(self._rpc("history", [False]))

    def find(self, nzb_id: int) -> NzbgetItem | None:
        return self.find_item(str(nzb_id))

    def delete(self, nzb_id: int) -> bool:
        """Cancel via ``editqueue`` GroupDelete. False when NZBGet refuses."""
        return self.cancel(str(nzb_id))

    def find_item(self, nzb_id: str) -> NzbgetItem | None:
        wanted = str(nzb_id)
        for row in self.list_groups():
            if str(row.get("NZBID") or "") == wanted:
                return _item_from_queue(row)
        for row in self.history():
            if str(row.get("NZBID") or "") == wanted:
                return _item_from_history(row)
        return None

    def cancel(self, nzb_id: str) -> bool:
        """Move the group to history (GroupDelete). Does not use GroupFinalDelete."""
        try:
            result = self._rpc("editqueue", ["GroupDelete", "", [int(nzb_id)]])
        except (NzbgetRpcError, ValueError):
            return False
        return result is True

    def map_status(self, item: NzbgetItem) -> NzbgetMappedStatus:
        if item.where == "history":
            return _map_history(item)
        return _map_queue(item)

    def _rpc(self, method: str, params: list[Any]) -> Any:
        self._rpc_id += 1
        # Keep id before params. Older JSON-RPC readers reject append when id follows params.
        body = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": method,
            "params": params,
        }
        url = self._endpoint()
        try:
            response = self._session.post(
                url,
                json=body,
                auth=(self._username, self._password),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise NzbgetRpcError(
                "NZBGet request failed. Check its address and availability."
            ) from exc
        if response.status_code in {401, 403}:
            raise NzbgetRpcError(
                "NZBGet rejected the username or password.",
                status_code=response.status_code,
            )
        if response.status_code != 200:
            raise NzbgetRpcError(
                f"NZBGet returned HTTP {response.status_code}.",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise NzbgetRpcError("NZBGet returned invalid JSON.", malformed=True) from exc
        if not isinstance(payload, dict):
            raise NzbgetRpcError("NZBGet returned invalid JSON.", malformed=True)
        error = payload.get("error")
        if error:
            if isinstance(error, dict):
                message = str(error.get("message") or "NZBGet request failed.")
            else:
                message = str(error)
            raise NzbgetRpcError(message)
        return payload.get("result")

    def _endpoint(self) -> str:
        if self._base_url.endswith("/jsonrpc"):
            return self._base_url
        return f"{self._base_url}/jsonrpc"


def _access_from_failure(exc: NzbgetRpcError) -> NzbgetAccess:
    if exc.malformed:
        return NzbgetAccess(
            ok=False,
            level="malformed",
            message="NZBGet returned invalid JSON.",
        )
    if exc.status_code in {401, 403}:
        return NzbgetAccess(
            ok=False,
            level="denied",
            message="NZBGet rejected the username or password.",
        )
    return NzbgetAccess(
        ok=False,
        level="unreachable",
        message="NZBGet did not respond. Check the URL and that it is running.",
    )


def _looks_like_permission(message: str) -> bool:
    folded = message.casefold()
    return any(marker in folded for marker in _PERMISSION_MARKERS)


def _as_rows(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    if not isinstance(result, list):
        raise NzbgetRpcError("NZBGet returned invalid JSON.", malformed=True)
    return [row for row in result if isinstance(row, dict)]


def _item_from_queue(row: dict[str, Any]) -> NzbgetItem:
    status = str(row.get("Status") or "")
    total = _u64(row.get("FileSizeLo"), row.get("FileSizeHi"))
    remaining = _u64(row.get("RemainingSizeLo"), row.get("RemainingSizeHi"))
    if status.casefold() in _QUEUE_POST:
        try:
            progress = float(row.get("PostStageProgress") or 0) / 1000.0
        except (TypeError, ValueError):
            progress = 0.0
    elif total > 0:
        progress = min(1.0, max(0.0, (total - remaining) / total))
    else:
        progress = 0.0
    dest = str(row.get("FinalDir") or row.get("DestDir") or "")
    return NzbgetItem(
        nzb_id=str(row.get("NZBID") or ""),
        status=status,
        where="queue",
        progress=progress,
        dest_dir=dest,
        name=str(row.get("NZBName") or ""),
    )


def _item_from_history(row: dict[str, Any]) -> NzbgetItem:
    return NzbgetItem(
        nzb_id=str(row.get("NZBID") or ""),
        status=str(row.get("Status") or ""),
        where="history",
        progress=1.0,
        dest_dir=str(row.get("FinalDir") or row.get("DestDir") or ""),
        name=str(row.get("Name") or row.get("NZBName") or ""),
    )


def _map_queue(item: NzbgetItem) -> NzbgetMappedStatus:
    status = item.status.casefold()
    # Downloading and every post-processing stage stay in progress.
    # PP_FINISHED is still in the queue and is not history success.
    state = "queued" if status in _QUEUE_PENDING else "downloading"
    label = "post-processing" if status in _QUEUE_POST else "queue"
    return NzbgetMappedStatus(
        state=state,
        progress=min(1.0, max(0.0, item.progress)),
        message=f"NZBGet {label} status: {item.status or 'unknown'}",
    )


def _map_history(item: NzbgetItem) -> NzbgetMappedStatus:
    head = item.status.split("/", 1)[0].casefold()
    if head == "success" and item.dest_dir:
        return NzbgetMappedStatus(
            state="completed",
            progress=1.0,
            message=f"NZBGet history status: {item.status}",
            local_paths=_audio_paths_under(item.dest_dir),
        )
    if head == "success":
        return NzbgetMappedStatus(
            state="failed",
            progress=1.0,
            message="NZBGet reported success without a destination directory.",
        )
    return NzbgetMappedStatus(
        state="failed",
        progress=item.progress,
        message=f"NZBGet history status: {item.status or 'unknown'}",
    )


def _u32(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        return 0
    try:
        number = int(value)
    except ValueError:
        return 0
    return number & 0xFFFFFFFF


def _u64(lo: object, hi: object) -> int:
    return (_u32(hi) << 32) | _u32(lo)


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

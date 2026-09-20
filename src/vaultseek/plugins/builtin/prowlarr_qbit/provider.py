"""Prowlarr acquisition provider with qBittorrent and a Usenet download client.

Search is always Prowlarr. Downloads route by result protocol:
torrent / magnet → qBittorrent; usenet / NZB → the selected client
(SABnzbd by default, or NZBGet). NZBGet is not a separate search source.
Existing ``sab:`` and ``nzb:`` handles stay on the client that accepted them.
"""

from __future__ import annotations

import time
from pathlib import Path, PurePosixPath, PureWindowsPath

from loguru import logger

from vaultseek.core.config import normalize_usenet_download_client
from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    DownloadHandle,
    DownloadStatus,
    ProviderCapabilities,
    SearchRequest,
    SearchResult,
)
from vaultseek.plugins.builtin.nzbget import NzbgetClient
from vaultseek.plugins.builtin.prowlarr_qbit.prowlarr_client import (
    ProwlarrClient,
    ProwlarrResult,
)
from vaultseek.plugins.builtin.prowlarr_qbit.qbittorrent_client import (
    QbittorrentClient,
    infohash_from_magnet,
)
from vaultseek.plugins.builtin.sabnzbd import SabnzbdClient

_AUDIO_EXTENSIONS = frozenset(
    {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".alac", ".wv", ".ape"}
)
_HASH_RESOLVE_ATTEMPTS = 8
_HASH_RESOLVE_DELAY_SECONDS = 0.5
_SAB_PREFIX = "sab:"
_NZB_PREFIX = "nzb:"


class ProwlarrProvider:
    """Search via Prowlarr; download via qBittorrent and/or SABnzbd.

    Optional ``protocol_filter`` / ``privacy_filter`` create waterfall tiers
    (usenet vs public torrents vs private torrents) from the same Prowlarr API.
    """

    def __init__(
        self,
        *,
        provider_id: str = "prowlarr",
        display_name: str = "Prowlarr (qBittorrent / SABnzbd)",
        protocol_filter: str | None = None,
        privacy_filter: str | None = None,
        prowlarr: ProwlarrClient | None = None,
        qbittorrent: QbittorrentClient | None = None,
        sabnzbd: SabnzbdClient | None = None,
        nzbget: NzbgetClient | None = None,
        hash_resolve_attempts: int = _HASH_RESOLVE_ATTEMPTS,
        hash_resolve_delay_seconds: float = _HASH_RESOLVE_DELAY_SECONDS,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        self._protocol_filter = (protocol_filter or "").casefold() or None
        self._privacy_filter = (privacy_filter or "").casefold() or None
        self._prowlarr = prowlarr
        self._qbit = qbittorrent
        self._sab = sabnzbd
        self._nzb = nzbget
        self._injected = any(x is not None for x in (prowlarr, qbittorrent, sabnzbd, nzbget))
        self._connected = False
        self._qbit_enabled = False
        self._sab_enabled = False
        self._nzb_enabled = False
        self._usenet_client = "sabnzbd"
        self._categories: tuple[int, ...] = (3000,)
        self._min_seeders = 0
        self._qbit_category = "vaultseek"
        self._qbit_save_path = ""
        self._sab_category = "vaultseek"
        self._nzb_category = "vaultseek"
        self._hash_attempts = max(1, hash_resolve_attempts)
        self._hash_delay = max(0.0, hash_resolve_delay_seconds)

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            search=True, browse=False, download=True, cancel=True, progress=True
        )

    def connect(self, config: AcquisitionProviderConfig) -> bool:
        if not config.enabled:
            self._connected = False
            return False
        settings = dict(config.settings)
        self._categories = tuple(int(c) for c in settings.get("categories") or (3000,))
        self._min_seeders = int(settings.get("min_seeders") or 0)
        self._qbit_category = str(settings.get("qbit_category") or "vaultseek")
        self._qbit_save_path = str(settings.get("qbit_save_path") or "")
        self._sab_category = str(settings.get("sab_category") or "vaultseek")
        self._nzb_category = str(settings.get("nzb_category") or "vaultseek")
        self._qbit_enabled = bool(settings.get("qbit_enabled"))
        self._sab_enabled = bool(settings.get("sab_enabled"))
        self._nzb_enabled = bool(settings.get("nzb_enabled"))
        self._usenet_client = normalize_usenet_download_client(
            settings.get("usenet_download_client")
        )
        # Tier constraints: usenet uses one NZB client; torrent tiers need qBit only.
        if self._protocol_filter == "usenet":
            self._qbit_enabled = False
        elif self._protocol_filter == "torrent":
            self._sab_enabled = False
            self._nzb_enabled = False

        if not self._injected:
            self._prowlarr = ProwlarrClient(
                base_url=str(settings.get("prowlarr_base_url") or ""),
                api_key=str(settings.get("prowlarr_api_key") or ""),
            )
            self._qbit = (
                QbittorrentClient(
                    base_url=str(settings.get("qbit_base_url") or ""),
                    username=str(settings.get("qbit_username") or ""),
                    password=str(settings.get("qbit_password") or ""),
                )
                if self._qbit_enabled
                else None
            )
            self._sab = (
                SabnzbdClient(
                    base_url=str(settings.get("sab_base_url") or ""),
                    api_key=str(settings.get("sab_api_key") or ""),
                )
                if self._sab_enabled
                else None
            )
            self._nzb = (
                NzbgetClient(
                    base_url=str(settings.get("nzb_base_url") or ""),
                    username=str(settings.get("nzb_username") or ""),
                    password=str(settings.get("nzb_password") or ""),
                )
                if self._nzb_enabled
                else None
            )
        else:
            # Tests may inject only some clients — fill gaps from settings.
            if self._prowlarr is None:
                self._prowlarr = ProwlarrClient(
                    base_url=str(settings.get("prowlarr_base_url") or ""),
                    api_key=str(settings.get("prowlarr_api_key") or ""),
                )
            if self._qbit_enabled and self._qbit is None:
                self._qbit = QbittorrentClient(
                    base_url=str(settings.get("qbit_base_url") or ""),
                    username=str(settings.get("qbit_username") or ""),
                    password=str(settings.get("qbit_password") or ""),
                )
            if not self._qbit_enabled:
                self._qbit = None
            if self._sab_enabled and self._sab is None:
                self._sab = SabnzbdClient(
                    base_url=str(settings.get("sab_base_url") or ""),
                    api_key=str(settings.get("sab_api_key") or ""),
                )
            if not self._sab_enabled:
                self._sab = None
            if self._nzb_enabled and self._nzb is None:
                self._nzb = NzbgetClient(
                    base_url=str(settings.get("nzb_base_url") or ""),
                    username=str(settings.get("nzb_username") or ""),
                    password=str(settings.get("nzb_password") or ""),
                )
            if not self._nzb_enabled:
                self._nzb = None

        if self._prowlarr is None:
            self._connected = False
            return False
        sab_required = self._sab_enabled and not self._nzb_is_selected()
        nzb_required = self._nzb_enabled and self._nzb_is_selected()
        if not self._qbit_enabled and not sab_required and not nzb_required:
            logger.warning("Prowlarr enabled but no download client is on")
            self._connected = False
            return False

        prowlarr_ok = self._prowlarr.probe()
        qbit_ok = True
        sab_ok = True
        nzb_ok = True
        if self._qbit_enabled:
            qbit_ok = self._qbit is not None and self._qbit.probe()
            if not qbit_ok:
                logger.warning("qBittorrent login failed — check WebUI URL and credentials")
        if sab_required:
            sab_ok = self._sab is not None and self._sab.probe()
            if not sab_ok:
                logger.warning("SABnzbd did not respond — check URL and API key")
        elif self._sab_enabled and (self._sab is None or not self._sab.probe()):
            logger.warning("SABnzbd is enabled but did not respond; sab: downloads stay pending")
        if nzb_required:
            nzb_ok = self._nzb is not None and self._nzb.probe()
            if not nzb_ok:
                logger.warning(
                    "NZBGet cannot be polled — check the URL and control username/password. "
                    "An add-only login is not enough."
                )
        elif self._nzb_enabled and (self._nzb is None or not self._nzb.probe()):
            logger.warning("NZBGet is enabled but did not respond; nzb: downloads stay pending")
        if not prowlarr_ok:
            logger.warning("Prowlarr did not respond — check base URL and API key")
        elif self._prowlarr is not None:
            self._prowlarr.refresh_indexer_privacy()

        clients_ok = qbit_ok and sab_ok and nzb_ok
        any_client = (
            (self._qbit_enabled and qbit_ok)
            or (sab_required and sab_ok)
            or (nzb_required and nzb_ok)
        )
        self._connected = prowlarr_ok and clients_ok and any_client
        return self._connected

    def _nzb_is_selected(self) -> bool:
        return self._usenet_client == "nzbget" and self._protocol_filter != "torrent"

    def disconnect(self) -> None:
        self._connected = False

    def search(self, request: SearchRequest) -> list[SearchResult]:
        if not self._connected or self._prowlarr is None:
            logger.warning("Prowlarr search skipped — not connected")
            return []
        query = " ".join(
            part for part in (request.artist, request.album, request.title) if part
        ).strip()
        if not query:
            return []
        try:
            hits = self._prowlarr.search(
                query,
                categories=self._categories,
                protocol=self._protocol_filter,
                privacy=self._privacy_filter,
            )
        except ConnectionError as exc:
            logger.warning("Prowlarr search failed: {}", exc)
            return []
        results: list[SearchResult] = []
        for hit in hits:
            if not hit.link:
                continue
            if hit.is_torrent and not self._qbit_enabled:
                continue
            if hit.is_nzb and not self._usenet_ready():
                continue
            if not hit.is_torrent and not hit.is_nzb:
                continue
            if hit.is_torrent and hit.seeders is not None and hit.seeders < self._min_seeders:
                continue
            results.append(self._to_search_result(hit))
        logger.info(
            "{} returned {} usable result(s) for {}",
            self.provider_id,
            len(results),
            query or "(empty)",
        )
        return results

    def _to_search_result(self, hit: ProwlarrResult) -> SearchResult:
        result_id = hit.info_hash or hit.guid or hit.link
        if hit.is_nzb:
            download_client = "nzbget" if self._usenet_client == "nzbget" else "sabnzbd"
        else:
            download_client = "qbittorrent"
        return SearchResult(
            provider_id=self.provider_id,
            result_id=result_id,
            display_name=hit.title,
            format=_guess_format(hit.title),
            size_bytes=hit.size_bytes,
            source_user=hit.indexer,
            raw={
                "link": hit.link,
                "magnet_url": hit.magnet_url,
                "download_url": hit.download_url,
                "info_hash": hit.info_hash,
                "seeders": hit.seeders,
                "title": hit.title,
                "protocol": hit.protocol,
                "download_client": download_client,
            },
        )

    def download(self, result: SearchResult) -> DownloadHandle:
        raw = dict(result.raw)
        client = str(raw.get("download_client") or "")
        link = str(raw.get("link") or "")
        if not link:
            raise ValueError("Prowlarr result has no download link")

        # New NZBs follow the current Usenet client only. Never submit to the other
        # client when this one rejects or returns an ambiguous id.
        if client in {"sabnzbd", "nzbget"} or self._looks_nzb(raw):
            if self._usenet_client == "nzbget":
                return self._download_nzb(result, link)
            return self._download_sab(result, link)
        return self._download_qbit(result, raw, link)

    @staticmethod
    def _looks_nzb(raw: dict[str, object]) -> bool:
        protocol = str(raw.get("protocol") or "").casefold()
        url = str(raw.get("download_url") or raw.get("link") or "").casefold()
        return protocol == "usenet" or ".nzb" in url

    def _download_sab(self, result: SearchResult, link: str) -> DownloadHandle:
        if self._sab is None:
            raise ConnectionError("SABnzbd is not connected")
        nzo_id = self._sab.add_url(link, category=self._sab_category)
        return DownloadHandle(
            provider_id=self.provider_id,
            download_id=f"{_SAB_PREFIX}{nzo_id}",
            result_id=result.result_id,
        )

    def _download_nzb(self, result: SearchResult, link: str) -> DownloadHandle:
        if self._nzb is None:
            raise ConnectionError("NZBGet is not connected")
        # Do not fall back to SABnzbd if this call is ambiguous or rejected.
        nzb_id = self._nzb.append_url(link, category=self._nzb_category)
        return DownloadHandle(
            provider_id=self.provider_id,
            download_id=f"{_NZB_PREFIX}{nzb_id}",
            result_id=result.result_id,
        )

    def _download_qbit(
        self, result: SearchResult, raw: dict[str, object], link: str
    ) -> DownloadHandle:
        if self._qbit is None:
            raise ConnectionError("qBittorrent is not connected")
        known_hash = str(raw.get("info_hash") or "").lower() or infohash_from_magnet(
            str(raw.get("magnet_url") or link)
        )
        before = self._qbit.list_hashes(category=self._qbit_category)
        self._qbit.add_torrent(link, category=self._qbit_category, save_path=self._qbit_save_path)
        resolved = self._resolve_hash(known_hash, before)
        download_id = resolved or known_hash or result.result_id
        return DownloadHandle(
            provider_id=self.provider_id,
            download_id=download_id,
            result_id=result.result_id,
        )

    def _resolve_hash(self, known_hash: str, before: set[str]) -> str:
        if self._qbit is None:
            return known_hash
        for _ in range(self._hash_attempts):
            current = self._qbit.list_hashes(category=self._qbit_category)
            if known_hash and known_hash in current:
                return known_hash
            new_hashes = current - before
            if len(new_hashes) == 1:
                return next(iter(new_hashes))
            if new_hashes and known_hash in new_hashes:
                return known_hash
            if self._hash_delay:
                time.sleep(self._hash_delay)
        current = self._qbit.list_hashes(category=self._qbit_category)
        new_hashes = current - before
        if new_hashes:
            return sorted(new_hashes)[0]
        return known_hash

    def cancel(self, handle: DownloadHandle) -> bool:
        if handle.download_id.startswith(_NZB_PREFIX):
            if self._nzb is None:
                return False
            nzb_id = _parse_nzb_id(handle.download_id)
            if nzb_id is None:
                return False
            return self._nzb.delete(nzb_id)
        if handle.download_id.startswith(_SAB_PREFIX):
            if self._sab is None:
                return False
            return self._sab.delete(handle.download_id[len(_SAB_PREFIX) :])
        if self._qbit is None:
            return False
        return self._qbit.delete(handle.download_id, delete_files=False)

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        if handle.download_id.startswith(_SAB_PREFIX):
            return self._status_sab(handle)
        if handle.download_id.startswith(_NZB_PREFIX):
            return self._status_nzb(handle)
        if not self._connected:
            return DownloadStatus(
                download_id=handle.download_id,
                state="failed",
                message="Prowlarr download clients are not connected.",
            )
        return self._status_qbit(handle)

    def _status_sab(self, handle: DownloadHandle) -> DownloadStatus:
        if self._sab is None:
            return DownloadStatus(
                download_id=handle.download_id,
                state="failed",
                message="SABnzbd is not connected.",
            )
        nzo_id = handle.download_id[len(_SAB_PREFIX) :]
        slot = self._sab.find_slot(nzo_id)
        if slot is None:
            return DownloadStatus(
                download_id=handle.download_id,
                state="queued",
                progress=0.0,
                message="Waiting for SABnzbd to register the NZB.",
            )
        mapped = self._sab.map_status(slot)
        return DownloadStatus(
            download_id=handle.download_id,
            state=mapped.state,
            progress=mapped.progress,
            message=mapped.message,
            local_paths=mapped.local_paths,
        )

    def _status_nzb(self, handle: DownloadHandle) -> DownloadStatus:
        if self._nzb is None:
            return DownloadStatus(
                download_id=handle.download_id,
                state="failed",
                message="NZBGet is not connected.",
            )
        nzb_id = _parse_nzb_id(handle.download_id)
        if nzb_id is None:
            return DownloadStatus(
                download_id=handle.download_id,
                state="queued",
                progress=0.0,
                message="NZBGet id is not valid.",
            )
        try:
            item = self._nzb.find(nzb_id)
        except (ConnectionError, PermissionError):
            return DownloadStatus(
                download_id=handle.download_id,
                state="queued",
                progress=0.0,
                message="Waiting for NZBGet to answer.",
            )
        if item is None:
            return DownloadStatus(
                download_id=handle.download_id,
                state="queued",
                progress=0.0,
                message="NZBGet has not registered this NZB.",
            )
        mapped = self._nzb.map_status(item)
        return DownloadStatus(
            download_id=handle.download_id,
            state=mapped.state,
            progress=mapped.progress,
            message=mapped.message,
            local_paths=mapped.local_paths,
        )

    def _usenet_ready(self) -> bool:
        if self._usenet_client == "nzbget":
            return self._nzb_enabled
        return self._sab_enabled

    def _status_qbit(self, handle: DownloadHandle) -> DownloadStatus:
        if self._qbit is None:
            return DownloadStatus(
                download_id=handle.download_id,
                state="failed",
                message="qBittorrent is not connected.",
            )
        torrent = self._qbit.find_torrent(handle.download_id)
        if torrent is None:
            return DownloadStatus(
                download_id=handle.download_id,
                state="queued",
                progress=0.0,
                message="Waiting for qBittorrent to register the torrent.",
            )
        mapped = self._qbit.map_status(torrent)
        local_paths: tuple[Path, ...] = ()
        if mapped.state == "completed":
            local_paths = _build_local_paths(mapped.save_path, mapped.relative_files)
        return DownloadStatus(
            download_id=handle.download_id,
            state=mapped.state,
            progress=mapped.progress,
            message=mapped.message,
            local_paths=local_paths,
        )


# Backward-compatible alias used by older imports/tests.
ProwlarrQbittorrentProvider = ProwlarrProvider


def _parse_nzb_id(download_id: str) -> int | None:
    raw = download_id[len(_NZB_PREFIX) :]
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _guess_format(title: str) -> str | None:
    lowered = title.casefold()
    for token in ("flac", "alac", "aac", "mp3", "ogg", "opus", "wav", "aiff"):
        if token in lowered:
            return token.upper()
    return None


def _build_local_paths(save_path: str, relative_files: tuple[str, ...]) -> tuple[Path, ...]:
    if not save_path:
        return ()
    base = Path(save_path)
    paths: list[Path] = []
    for name in relative_files:
        parts = PureWindowsPath(name).parts if "\\" in name else PurePosixPath(name).parts
        if not parts:
            continue
        candidate = base.joinpath(*parts)
        if candidate.suffix.casefold() in _AUDIO_EXTENSIONS:
            paths.append(candidate)
    return tuple(paths)

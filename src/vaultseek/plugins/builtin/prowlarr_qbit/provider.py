"""Prowlarr + qBittorrent acquisition provider.

Search is delegated to Prowlarr (indexer aggregator); downloading is handed
to qBittorrent's WebUI. The two are paired because Prowlarr finds torrents
and qBittorrent grabs them — together they form one acquisition backend that
slots into the same search → score → download → verify → import pipeline as
Nicotine+.
"""

from __future__ import annotations

import time
from pathlib import Path, PurePosixPath, PureWindowsPath

from loguru import logger

from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    DownloadHandle,
    DownloadStatus,
    ProviderCapabilities,
    SearchRequest,
    SearchResult,
)
from vaultseek.plugins.builtin.prowlarr_qbit.prowlarr_client import (
    ProwlarrClient,
    ProwlarrResult,
)
from vaultseek.plugins.builtin.prowlarr_qbit.qbittorrent_client import (
    QbittorrentClient,
    infohash_from_magnet,
)

_AUDIO_EXTENSIONS = frozenset(
    {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".alac", ".wv", ".ape"}
)
# How long to wait for qBittorrent to register an added torrent's hash.
_HASH_RESOLVE_ATTEMPTS = 8
_HASH_RESOLVE_DELAY_SECONDS = 0.5


class ProwlarrQbittorrentProvider:
    """Search via Prowlarr, download via qBittorrent."""

    provider_id = "prowlarr_qbit"
    display_name = "Prowlarr + qBittorrent"

    def __init__(
        self,
        *,
        prowlarr: ProwlarrClient | None = None,
        qbittorrent: QbittorrentClient | None = None,
        hash_resolve_attempts: int = _HASH_RESOLVE_ATTEMPTS,
        hash_resolve_delay_seconds: float = _HASH_RESOLVE_DELAY_SECONDS,
    ) -> None:
        self._prowlarr = prowlarr
        self._qbit = qbittorrent
        self._injected = prowlarr is not None or qbittorrent is not None
        self._connected = False
        self._categories: tuple[int, ...] = (3000,)
        self._min_seeders = 0
        self._category = "vaultseek"
        self._save_path = ""
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
        self._category = str(settings.get("qbit_category") or "vaultseek")
        self._save_path = str(settings.get("qbit_save_path") or "")

        if not self._injected:
            self._prowlarr = ProwlarrClient(
                base_url=str(settings.get("prowlarr_base_url") or ""),
                api_key=str(settings.get("prowlarr_api_key") or ""),
            )
            self._qbit = QbittorrentClient(
                base_url=str(settings.get("qbit_base_url") or ""),
                username=str(settings.get("qbit_username") or ""),
                password=str(settings.get("qbit_password") or ""),
            )
        if self._prowlarr is None or self._qbit is None:
            self._connected = False
            return False

        prowlarr_ok = self._prowlarr.probe()
        qbit_ok = self._qbit.probe()
        if not prowlarr_ok:
            logger.warning("Prowlarr did not respond — check base URL and API key")
        if not qbit_ok:
            logger.warning("qBittorrent login failed — check WebUI URL and credentials")
        self._connected = prowlarr_ok and qbit_ok
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def search(self, request: SearchRequest) -> list[SearchResult]:
        if not self._connected or self._prowlarr is None:
            logger.warning("Prowlarr+qBittorrent search skipped — not connected")
            return []
        query = " ".join(
            part for part in (request.artist, request.album, request.title) if part
        ).strip()
        if not query:
            return []
        hits = self._prowlarr.search(query, categories=self._categories)
        results: list[SearchResult] = []
        for hit in hits:
            if not hit.link:
                continue
            if hit.seeders is not None and hit.seeders < self._min_seeders:
                continue
            results.append(self._to_search_result(hit))
        logger.info(
            "Prowlarr returned {} usable result(s) for {}", len(results), query or "(empty)"
        )
        return results

    def _to_search_result(self, hit: ProwlarrResult) -> SearchResult:
        result_id = hit.info_hash or hit.guid or hit.link
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
            },
        )

    def download(self, result: SearchResult) -> DownloadHandle:
        if self._qbit is None:
            raise ConnectionError("qBittorrent is not connected")
        raw = dict(result.raw)
        link = str(raw.get("link") or "")
        if not link:
            raise ValueError("Prowlarr result has no magnet/torrent link to download")

        known_hash = str(raw.get("info_hash") or "").lower() or infohash_from_magnet(
            str(raw.get("magnet_url") or link)
        )
        before = self._qbit.list_hashes(category=self._category)
        self._qbit.add_torrent(link, category=self._category, save_path=self._save_path)
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
            current = self._qbit.list_hashes(category=self._category)
            if known_hash and known_hash in current:
                return known_hash
            new_hashes = current - before
            if len(new_hashes) == 1:
                return next(iter(new_hashes))
            if new_hashes and known_hash in new_hashes:
                return known_hash
            if self._hash_delay:
                time.sleep(self._hash_delay)
        # Last resort: any newly appeared hash.
        current = self._qbit.list_hashes(category=self._category)
        new_hashes = current - before
        if new_hashes:
            return sorted(new_hashes)[0]
        return known_hash

    def cancel(self, handle: DownloadHandle) -> bool:
        if self._qbit is None:
            return False
        return self._qbit.delete(handle.download_id, delete_files=False)

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        if not self._connected or self._qbit is None:
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


def _guess_format(title: str) -> str | None:
    lowered = title.casefold()
    for token in ("flac", "alac", "aac", "mp3", "ogg", "opus", "wav", "aiff"):
        if token in lowered:
            return token.upper()
    return None


def _build_local_paths(save_path: str, relative_files: tuple[str, ...]) -> tuple[Path, ...]:
    """Join qBittorrent's save path with each audio file's relative name.

    qBittorrent reports file names with forward slashes even on Windows;
    normalize per-platform and keep only audio files.
    """
    if not save_path:
        return ()
    base = Path(save_path)
    paths: list[Path] = []
    for name in relative_files:
        # Torrent file names use POSIX separators; split on both to be safe.
        parts = PureWindowsPath(name).parts if "\\" in name else PurePosixPath(name).parts
        if not parts:
            continue
        candidate = base.joinpath(*parts)
        if candidate.suffix.casefold() in _AUDIO_EXTENSIONS:
            paths.append(candidate)
    return tuple(paths)

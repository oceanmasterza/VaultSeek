"""Tests for the Prowlarr + qBittorrent acquisition provider."""

from __future__ import annotations

from pathlib import Path

import responses

from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    DownloadHandle,
    SearchRequest,
    SearchResult,
)
from vaultseek.plugins.builtin.prowlarr_qbit import (
    ProwlarrClient,
    ProwlarrQbittorrentProvider,
    ProwlarrResult,
    QbittorrentClient,
    infohash_from_magnet,
)
from vaultseek.plugins.builtin.prowlarr_qbit.qbittorrent_client import (
    MappedStatus,
    QbittorrentTorrent,
)

_HASH = "0123456789abcdef0123456789abcdef01234567"


# --------------------------------------------------------------- magnet util --
def test_infohash_from_magnet_hex() -> None:
    magnet = f"magnet:?xt=urn:btih:{_HASH}&dn=Album"
    assert infohash_from_magnet(magnet) == _HASH


def test_infohash_from_magnet_base32_returns_empty() -> None:
    # 32-char base32 form is not directly usable; leave to diff resolution.
    magnet = "magnet:?xt=urn:btih:ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    assert infohash_from_magnet(magnet) == ""


# --------------------------------------------------------------- Prowlarr ----
@responses.activate
def test_prowlarr_search_maps_results() -> None:
    responses.add(
        responses.GET,
        "http://pr:9696/api/v1/search",
        json=[
            {
                "title": "Artist - Album [FLAC]",
                "guid": "guid-1",
                "indexer": "Indexer",
                "downloadUrl": "http://pr/dl/1",
                "magnetUrl": f"magnet:?xt=urn:btih:{_HASH}",
                "size": 12345,
                "seeders": 20,
                "categories": [{"id": 3040, "name": "Audio/Lossless"}],
            }
        ],
    )
    client = ProwlarrClient("http://pr:9696", "key")
    results = client.search("Artist Album")
    assert len(results) == 1
    assert results[0].seeders == 20
    assert results[0].link.startswith("magnet:")
    assert results[0].categories == (3040,)


@responses.activate
def test_prowlarr_probe() -> None:
    responses.add(responses.GET, "http://pr:9696/api/v1/system/status", json={"version": "1"})
    assert ProwlarrClient("http://pr:9696", "key").probe() is True


# ------------------------------------------------------------- qBittorrent ---
@responses.activate
def test_qbittorrent_login_bypass_204() -> None:
    """qBittorrent 5.x localhost bypass often returns 204 on /auth/login."""
    base = "http://qb:8081"
    responses.add(responses.POST, f"{base}/api/v2/auth/login", status=204, body="")
    responses.add(responses.GET, f"{base}/api/v2/app/version", body="v5.2.3")
    assert QbittorrentClient(base, "admin", "").probe() is True


@responses.activate
def test_qbittorrent_login_add_and_files() -> None:
    base = "http://qb:8080"
    responses.add(responses.POST, f"{base}/api/v2/auth/login", body="Ok.")
    responses.add(responses.POST, f"{base}/api/v2/torrents/add", body="Ok.")
    responses.add(
        responses.GET,
        f"{base}/api/v2/torrents/info",
        json=[
            {
                "hash": _HASH,
                "name": "Album",
                "state": "uploading",
                "progress": 1.0,
                "save_path": "D:/dl",
                "content_path": "D:/dl/Album",
            }
        ],
    )
    responses.add(
        responses.GET,
        f"{base}/api/v2/torrents/files",
        json=[{"name": "Album/01.flac", "size": 100}],
    )
    client = QbittorrentClient(base, "admin", "pw")
    assert client.probe() is True
    client.add_torrent("magnet:?xt=urn:btih:x", category="vaultseek")
    torrents = client.torrents_info(hashes=_HASH)
    assert torrents[0].state == "uploading"
    mapped = client.map_status(torrents[0])
    assert mapped.state == "completed"
    assert mapped.relative_files == ("Album/01.flac",)


def test_qbittorrent_map_status_states() -> None:
    client = QbittorrentClient("http://qb:8080")

    def torrent(state: str, progress: float) -> QbittorrentTorrent:
        return QbittorrentTorrent(
            hash=_HASH,
            name="n",
            state=state,
            progress=progress,
            save_path="D:/dl",
            content_path="D:/dl/n",
        )

    assert client.map_status(torrent("downloading", 0.5)).state == "downloading"
    assert client.map_status(torrent("queuedDL", 0.0)).state == "queued"
    assert client.map_status(torrent("error", 0.3)).state == "failed"


# ---------------------------------------------------------------- provider ---
class _FakeProwlarr:
    def __init__(self, results: list[ProwlarrResult]) -> None:
        self._results = results
        self.searched: list[str] = []

    def probe(self) -> bool:
        return True

    def search(self, query, *, categories=(3000,), limit=50):
        self.searched.append(query)
        return self._results


class _FakeQbit:
    def __init__(self) -> None:
        self.added: list[str] = []
        self._hashes: set[str] = set()
        self.torrent: QbittorrentTorrent | None = None
        self.mapped: MappedStatus | None = None
        self.deleted: list[str] = []

    def probe(self) -> bool:
        return True

    def list_hashes(self, *, category=None):
        return set(self._hashes)

    def add_torrent(self, link, *, category="", save_path=""):
        self.added.append(link)
        self._hashes.add(_HASH)

    def find_torrent(self, torrent_hash):
        return self.torrent

    def map_status(self, torrent):
        return self.mapped

    def delete(self, torrent_hash, *, delete_files=False):
        self.deleted.append(torrent_hash)
        return True


def _connect(provider: ProwlarrQbittorrentProvider) -> None:
    provider.connect(
        AcquisitionProviderConfig(
            provider_id="prowlarr",
            enabled=True,
            settings={
                "min_seeders": 5,
                "qbit_category": "vaultseek",
                "qbit_enabled": True,
            },
        )
    )


def test_provider_search_filters_low_seeders() -> None:
    results = [
        ProwlarrResult(
            title="Good",
            guid="g1",
            magnet_url=f"magnet:?xt=urn:btih:{_HASH}",
            seeders=10,
            protocol="torrent",
        ),
        ProwlarrResult(
            title="Starved",
            guid="g2",
            magnet_url="magnet:?xt=urn:btih:z",
            seeders=1,
            protocol="torrent",
        ),
        ProwlarrResult(title="NoLink", guid="g3", seeders=100, protocol="torrent"),
    ]
    provider = ProwlarrQbittorrentProvider(prowlarr=_FakeProwlarr(results), qbittorrent=_FakeQbit())
    _connect(provider)

    hits = provider.search(SearchRequest(artist="A", album="B"))

    assert [h.display_name for h in hits] == ["Good"]
    assert hits[0].provider_id == "prowlarr"


def test_provider_download_resolves_infohash() -> None:
    qbit = _FakeQbit()
    result = SearchResult(
        provider_id="prowlarr",
        result_id="g1",
        display_name="Good",
        raw={
            "link": f"magnet:?xt=urn:btih:{_HASH}",
            "magnet_url": f"magnet:?xt=urn:btih:{_HASH}",
            "info_hash": _HASH,
        },
    )
    provider = ProwlarrQbittorrentProvider(
        prowlarr=_FakeProwlarr([]), qbittorrent=qbit, hash_resolve_delay_seconds=0.0
    )
    _connect(provider)

    handle = provider.download(result)

    assert qbit.added == [f"magnet:?xt=urn:btih:{_HASH}"]
    assert handle.download_id == _HASH


def test_provider_status_builds_audio_local_paths() -> None:
    qbit = _FakeQbit()
    qbit.torrent = QbittorrentTorrent(
        hash=_HASH,
        name="Album",
        state="uploading",
        progress=1.0,
        save_path="D:/dl",
        content_path="D:/dl/Album",
    )
    qbit.mapped = MappedStatus(
        state="completed",
        progress=1.0,
        message="done",
        relative_files=("Album/01.flac", "Album/cover.jpg"),
        save_path="D:/dl",
    )
    provider = ProwlarrQbittorrentProvider(prowlarr=_FakeProwlarr([]), qbittorrent=qbit)
    _connect(provider)

    status = provider.get_status(DownloadHandle("prowlarr", _HASH, "g1"))

    assert status.state == "completed"
    assert status.local_paths == (Path("D:/dl") / "Album" / "01.flac",)


def test_provider_cancel_deletes_without_files() -> None:
    qbit = _FakeQbit()
    provider = ProwlarrQbittorrentProvider(prowlarr=_FakeProwlarr([]), qbittorrent=qbit)
    _connect(provider)
    assert provider.cancel(DownloadHandle("prowlarr", _HASH, "g1")) is True
    assert qbit.deleted == [_HASH]

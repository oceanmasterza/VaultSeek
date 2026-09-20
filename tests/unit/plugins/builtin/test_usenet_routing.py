"""Usenet downloads follow the selected client and keep old handles."""

from __future__ import annotations

from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    DownloadHandle,
    SearchResult,
)
from vaultseek.plugins.builtin.nzbget import NzbgetItem, NzbgetMappedStatus
from vaultseek.plugins.builtin.prowlarr_qbit import ProwlarrProvider
from vaultseek.plugins.builtin.prowlarr_qbit.prowlarr_client import ProwlarrResult
from vaultseek.plugins.builtin.sabnzbd import SabnzbdMappedStatus, SabnzbdSlot


class _Prowlarr:
    def probe(self) -> bool:
        return True

    def refresh_indexer_privacy(self) -> None:
        return None

    def search(self, query: str, **_kwargs: object) -> list[ProwlarrResult]:
        return []


class _Sab:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.deleted: list[str] = []
        self.slot: SabnzbdSlot | None = None

    def probe(self) -> bool:
        return True

    def add_url(self, url: str, *, category: str = "") -> str:
        self.urls.append(url)
        return "nzo-1"

    def delete(self, nzo_id: str) -> bool:
        self.deleted.append(nzo_id)
        return True

    def find_slot(self, nzo_id: str) -> SabnzbdSlot | None:
        return self.slot

    def map_status(self, slot: SabnzbdSlot) -> SabnzbdMappedStatus:
        return SabnzbdMappedStatus(state="downloading", progress=0.2, message=slot.status)


class _Nzb:
    def __init__(self, *, fail: bool = False) -> None:
        self.urls: list[str] = []
        self.deleted: list[int] = []
        self.fail = fail
        self.item: NzbgetItem | None = None
        self.mapped = NzbgetMappedStatus(state="queued", progress=0.0, message="pending")

    def probe(self) -> bool:
        return True

    def append_url(self, url: str, *, category: str = "") -> str:
        if self.fail:
            raise ConnectionError("NZBGet rejected the NZB and did not queue it.")
        self.urls.append(url)
        return "15"

    def delete(self, nzb_id: int) -> bool:
        self.deleted.append(nzb_id)
        return True

    def find(self, nzb_id: int) -> NzbgetItem | None:
        return self.item

    def map_status(self, item: NzbgetItem) -> NzbgetMappedStatus:
        return self.mapped


def _connect(provider: ProwlarrProvider, *, client: str) -> None:
    provider.connect(
        AcquisitionProviderConfig(
            provider_id="usenet",
            enabled=True,
            settings={
                "sab_enabled": True,
                "nzb_enabled": True,
                "usenet_download_client": client,
            },
        )
    )


def _nzb_result(client: str) -> SearchResult:
    return SearchResult(
        provider_id="usenet",
        result_id="hit",
        display_name="Album",
        raw={"link": "http://index/album.nzb", "download_client": client, "protocol": "usenet"},
    )


def test_new_nzb_uses_only_the_selected_client() -> None:
    sab = _Sab()
    nzb = _Nzb()
    provider = ProwlarrProvider(
        provider_id="usenet",
        protocol_filter="usenet",
        prowlarr=_Prowlarr(),
        sabnzbd=sab,
        nzbget=nzb,
    )
    _connect(provider, client="nzbget")
    handle = provider.download(_nzb_result("sabnzbd"))
    assert handle.download_id == "nzb:15"
    assert nzb.urls == ["http://index/album.nzb"]
    assert sab.urls == []


def test_rejected_nzbget_submit_does_not_fall_back_to_sab() -> None:
    sab = _Sab()
    nzb = _Nzb(fail=True)
    provider = ProwlarrProvider(
        provider_id="usenet",
        protocol_filter="usenet",
        prowlarr=_Prowlarr(),
        sabnzbd=sab,
        nzbget=nzb,
    )
    _connect(provider, client="nzbget")
    try:
        provider.download(_nzb_result("nzbget"))
    except ConnectionError:
        pass
    else:
        raise AssertionError("ambiguous NZBGet submit must not look successful")
    assert sab.urls == []


def test_existing_sab_handle_survives_preference_change() -> None:
    sab = _Sab()
    sab.slot = SabnzbdSlot(nzo_id="nzo-1", status="Downloading", percentage=20.0)
    nzb = _Nzb()
    provider = ProwlarrProvider(
        provider_id="usenet",
        protocol_filter="usenet",
        prowlarr=_Prowlarr(),
        sabnzbd=sab,
        nzbget=nzb,
    )
    _connect(provider, client="nzbget")
    status = provider.get_status(
        DownloadHandle(provider_id="usenet", download_id="sab:nzo-1", result_id="hit")
    )
    assert status.state == "downloading"
    assert status.state != "completed"
    assert provider.cancel(
        DownloadHandle(provider_id="usenet", download_id="sab:nzo-1", result_id="hit")
    )
    assert sab.deleted == ["nzo-1"]
    assert nzb.deleted == []


def test_missing_nzbget_job_is_not_complete() -> None:
    provider = ProwlarrProvider(
        provider_id="usenet",
        protocol_filter="usenet",
        prowlarr=_Prowlarr(),
        sabnzbd=_Sab(),
        nzbget=_Nzb(),
    )
    _connect(provider, client="nzbget")
    status = provider.get_status(
        DownloadHandle(provider_id="usenet", download_id="nzb:15", result_id="hit")
    )
    assert status.state != "completed"
    assert status.state == "queued"

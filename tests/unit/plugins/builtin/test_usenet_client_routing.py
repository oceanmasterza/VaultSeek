"""Usenet downloads stay on the client named by the handle."""

from __future__ import annotations

import pytest

from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    DownloadHandle,
    SearchResult,
)
from vaultseek.plugins.builtin.prowlarr_qbit.provider import ProwlarrProvider


class _Prowlarr:
    def probe(self) -> bool:
        return True

    def refresh_indexer_privacy(self) -> None:
        return None


class _Sab:
    def __init__(self) -> None:
        self.added: list[str] = []
        self.found: list[str] = []

    def probe(self) -> bool:
        return True

    def add_url(self, url: str, *, category: str = "") -> str:
        self.added.append(url)
        return "SABnzbd_nzo_old"

    def find_slot(self, nzo_id: str):  # noqa: ANN201
        self.found.append(nzo_id)
        return None

    def delete(self, nzo_id: str) -> bool:
        return True


class _Nzb:
    def __init__(self, *, fail: bool = False) -> None:
        self.added: list[str] = []
        self.fail = fail
        self.deleted: list[int] = []

    def probe(self) -> bool:
        return True

    def probe_authenticated(self) -> bool:
        return True

    def append_url(self, url: str, *, category: str = "") -> int:
        if self.fail:
            raise ConnectionError("NZBGet request failed")
        self.added.append(url)
        return 42

    def find(self, nzb_id: int):  # noqa: ANN201
        return None

    def delete(self, nzb_id: int) -> bool:
        self.deleted.append(nzb_id)
        return True

    def map_status(self, item: object):  # noqa: ANN201
        raise AssertionError(item)


def _connect(provider: ProwlarrProvider, *, client: str) -> None:
    assert provider.connect(
        AcquisitionProviderConfig(
            provider_id="usenet",
            enabled=True,
            settings={
                "usenet_download_client": client,
                "sab_enabled": True,
                "nzb_enabled": True,
            },
        )
    )


def test_nzbget_failure_does_not_submit_to_sab() -> None:
    sab = _Sab()
    nzb = _Nzb(fail=True)
    provider = ProwlarrProvider(
        provider_id="usenet",
        protocol_filter="usenet",
        prowlarr=_Prowlarr(),  # type: ignore[arg-type]
        sabnzbd=sab,  # type: ignore[arg-type]
        nzbget=nzb,  # type: ignore[arg-type]
    )
    _connect(provider, client="nzbget")
    result = SearchResult(
        provider_id="usenet",
        result_id="nzb-1",
        display_name="Album",
        raw={"link": "http://indexer/album.nzb", "download_client": "nzbget", "protocol": "usenet"},
    )
    with pytest.raises(ConnectionError):
        provider.download(result)
    assert sab.added == []
    assert nzb.added == []


def test_sab_handle_still_polls_sab_when_preference_is_nzbget() -> None:
    sab = _Sab()
    nzb = _Nzb()
    provider = ProwlarrProvider(
        provider_id="usenet",
        protocol_filter="usenet",
        prowlarr=_Prowlarr(),  # type: ignore[arg-type]
        sabnzbd=sab,  # type: ignore[arg-type]
        nzbget=nzb,  # type: ignore[arg-type]
    )
    _connect(provider, client="nzbget")
    status = provider.get_status(DownloadHandle("usenet", "sab:SABnzbd_nzo_old", "r"))
    assert sab.found == ["SABnzbd_nzo_old"]
    assert status.state != "completed"
    assert status.state == "queued"
    missing = provider.get_status(DownloadHandle("usenet", "nzb:42", "r"))
    assert missing.state == "queued"
    assert missing.state != "completed"
    assert provider.cancel(DownloadHandle("usenet", "nzb:42", "r")) is True
    assert nzb.deleted == [42]


def test_new_sab_preference_still_uses_sab_prefix() -> None:
    sab = _Sab()
    nzb = _Nzb()
    provider = ProwlarrProvider(
        provider_id="usenet",
        protocol_filter="usenet",
        prowlarr=_Prowlarr(),  # type: ignore[arg-type]
        sabnzbd=sab,  # type: ignore[arg-type]
        nzbget=nzb,  # type: ignore[arg-type]
    )
    _connect(provider, client="sabnzbd")
    result = SearchResult(
        provider_id="usenet",
        result_id="nzb-1",
        display_name="Album",
        raw={"link": "http://indexer/album.nzb", "protocol": "usenet"},
    )
    handle = provider.download(result)
    assert handle.download_id == "sab:SABnzbd_nzo_old"
    assert nzb.added == []

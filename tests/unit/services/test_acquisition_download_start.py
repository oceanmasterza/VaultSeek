"""Regressions for a refused download start during poll and verification.

The 2026-09-21 real-profile tick failed Alice in Chains — Grind: Nicotine+ was
not connected, the runner tried the next Soulseek peer from SCORING, and
DownloadManager advanced SCORING -> DOWNLOAD_FAILED. That transition stays
illegal. The start is recorded as SCORING -> DOWNLOADING -> DOWNLOAD_FAILED,
and a later connected waterfall tier or a verification retry must still run.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJobState, AcquisitionJobType
from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    DownloadHandle,
    DownloadStatus,
    SearchResult,
)
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_runner import AcquisitionRunner
from vaultseek.services.acquisition_workflow import AcquisitionWorkflow
from vaultseek.services.download_manager import DownloadManager
from vaultseek.services.import_pipeline import ImportPipeline
from vaultseek.services.provider_manager import ProviderManager
from vaultseek.services.scoring_engine import ScoringEngine
from vaultseek.services.search_dispatcher import SearchDispatcher
from vaultseek.services.verification_engine import VerificationEngine


class _DisconnectedNicotine(StubAcquisitionProvider):
    """Registered but not connected, matching the startup log."""

    provider_id = "nicotine_plus"
    display_name = "Nicotine+"

    def connect(self, config: AcquisitionProviderConfig) -> bool:
        return False

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        return DownloadStatus(
            download_id=handle.download_id,
            state="failed",
            progress=0.0,
            message="Nicotine+ is not connected.",
        )


class _ConnectedUsenet(StubAcquisitionProvider):
    provider_id = "usenet"
    display_name = "Usenet"

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        return DownloadStatus(
            download_id=handle.download_id,
            state="downloading",
            progress=0.2,
        )


class _CountingDownload(StubAcquisitionProvider):
    provider_id = "high"
    display_name = "High"

    def __init__(self) -> None:
        super().__init__()
        self.status_calls = 0

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        self.status_calls += 1
        return DownloadStatus(
            download_id=handle.download_id,
            state="downloading",
            progress=0.4,
        )


class _EmptyComplete(StubAcquisitionProvider):
    provider_id = "high"
    display_name = "High"

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        return DownloadStatus(
            download_id=handle.download_id,
            state="completed",
            progress=1.0,
            local_paths=(self._path,),
        )


def _result(provider_id: str, result_id: str, display_name: str) -> SearchResult:
    return SearchResult(
        provider_id=provider_id,
        result_id=result_id,
        display_name=display_name,
        artist="Alice in Chains",
        album="Alice In Chains",
        title="Grind",
        format="mp3",
    )


def _stored(result: SearchResult) -> dict[str, object]:
    return {
        "provider_id": result.provider_id,
        "result_id": result.result_id,
        "display_name": result.display_name,
        "artist": result.artist,
        "album": result.album,
        "title": result.title,
        "format": result.format,
        "raw": {},
    }


def _score_row(result: SearchResult, score: float) -> dict[str, object]:
    return {
        "result_id": result.result_id,
        "provider_id": result.provider_id,
        "score": score,
    }


def _runner(
    engine: Engine,
    providers: list[StubAcquisitionProvider],
    *,
    connected: tuple[str, ...],
) -> tuple[AcquisitionRunner, AcquisitionEngine]:
    manager = ProviderManager(providers)
    for provider_id in connected:
        manager.connect(AcquisitionProviderConfig(provider_id=provider_id, enabled=True))
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    search = SearchDispatcher(manager, acq)
    downloads = DownloadManager(manager, acq)
    workflow = AcquisitionWorkflow(acq, downloads, VerificationEngine(acq), ImportPipeline(acq))
    runner = AcquisitionRunner(
        acq,
        search,
        ScoringEngine(),
        downloads,
        workflow,
        auto_acquire_threshold=0.50,
    )
    return runner, acq


def _to_downloading(acq: AcquisitionEngine, library_id: UUID) -> UUID:
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Alice in Chains",
        album="Alice In Chains",
        title="Grind",
    )
    acq.queue(job.id)
    acq.advance(job.id, AcquisitionJobState.SEARCHING)
    acq.advance(job.id, AcquisitionJobState.COLLECTING_RESULTS)
    acq.advance(job.id, AcquisitionJobState.SCORING)
    acq.advance(job.id, AcquisitionJobState.DOWNLOADING)
    return job.id


def _history(acq: AcquisitionEngine, job_id: UUID) -> str:
    loaded = acq.get(job_id)
    assert loaded is not None
    return "\n".join(loaded.history)


def test_poll_refused_nicotine_peer_ends_download_failed_and_continues(
    engine: Engine, library_id: UUID
) -> None:
    """Real startup: failed Nicotine download, next peer also unavailable."""
    other = _CountingDownload()
    runner, acq = _runner(
        engine,
        [_DisconnectedNicotine(), other],
        connected=("high",),
    )
    current = _result("nicotine_plus", "nic-current", "08-Grind.mp3")
    nxt = _result(
        "nicotine_plus",
        "nic-next",
        r"@@cwmue\MUSIC\Alice in Chains\alice in chains - Greatest Hits 2001\08-Grind.mp3",
    )
    job_id = _to_downloading(acq, library_id)
    acq.update_extra(
        job_id,
        {
            "download_handle": {
                "provider_id": "nicotine_plus",
                "download_id": "dl-grind",
                "result_id": current.result_id,
            },
            "attempted_result_ids": [current.result_id],
            "search_results": [_stored(current), _stored(nxt)],
            "scored_results": [_score_row(current, 0.90), _score_row(nxt, 0.75)],
        },
    )
    other_id = _to_downloading(acq, library_id)
    acq.update_extra(
        other_id,
        {
            "download_handle": {
                "provider_id": "high",
                "download_id": "dl-other",
                "result_id": "other",
            }
        },
    )

    updated = runner.poll_active_jobs(library_id)

    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.DOWNLOAD_FAILED
    history = _history(acq, job_id)
    assert "scoring -> downloading" in history
    assert "downloading -> download_failed" in history
    assert "scoring -> download_failed" not in history
    assert updated == 1
    assert other.status_calls >= 1
    still = acq.get(other_id)
    assert still is not None
    assert still.state is AcquisitionJobState.DOWNLOADING


def test_unavailable_nicotine_peer_still_starts_later_waterfall_tier(
    engine: Engine, library_id: UUID
) -> None:
    runner, acq = _runner(
        engine,
        [_DisconnectedNicotine(), _ConnectedUsenet()],
        connected=("usenet",),
    )
    current = _result("nicotine_plus", "nic-current", "08-Grind.mp3")
    nxt = _result(
        "nicotine_plus",
        "nic-next",
        r"@@cwmue\MUSIC\Alice in Chains\alice in chains - Greatest Hits 2001\08-Grind.mp3",
    )
    usenet = _result("usenet", "nzb-1", "Alice in Chains - Grind.nzb")
    job_id = _to_downloading(acq, library_id)
    acq.update_extra(
        job_id,
        {
            "download_handle": {
                "provider_id": "nicotine_plus",
                "download_id": "dl-grind",
                "result_id": current.result_id,
            },
            "attempted_result_ids": [current.result_id],
            "search_results": [_stored(current), _stored(nxt), _stored(usenet)],
            "scored_results": [
                _score_row(current, 0.90),
                _score_row(nxt, 0.75),
                _score_row(usenet, 0.70),
            ],
        },
    )

    runner.poll_active_jobs(library_id)

    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.DOWNLOADING
    assert loaded.extra.get("selected_provider_id") == "usenet"
    history = _history(acq, job_id)
    assert "scoring -> download_failed" not in history
    assert "downloading -> download_failed" in history
    assert "usenet:nzb-1" in history


def test_verification_failure_retries_offline_provider_legally(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    empty = tmp_path / "08-Grind.mp3"
    empty.write_bytes(b"")
    runner, acq = _runner(
        engine,
        [_EmptyComplete(empty), _DisconnectedNicotine()],
        connected=("high",),
    )
    current = _result("high", "high-1", "08-Grind.mp3")
    nxt = _result(
        "nicotine_plus",
        "nic-next",
        r"@@cwmue\MUSIC\Alice in Chains\alice in chains - Greatest Hits 2001\08-Grind.mp3",
    )
    job_id = _to_downloading(acq, library_id)
    acq.update_extra(
        job_id,
        {
            "download_handle": {
                "provider_id": "high",
                "download_id": "dl-empty",
                "result_id": current.result_id,
            },
            "attempted_result_ids": [current.result_id],
            "search_results": [_stored(current), _stored(nxt)],
            "scored_results": [_score_row(current, 0.90), _score_row(nxt, 0.75)],
        },
    )

    runner.poll_active_jobs(library_id)

    loaded = acq.get(job_id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.DOWNLOAD_FAILED
    history = _history(acq, job_id)
    assert "verifying -> verification_failed" in history
    assert "verification_failed -> scoring" in history
    assert "scoring -> downloading" in history
    assert "downloading -> download_failed" in history
    assert "scoring -> download_failed" not in history


def test_download_manager_unavailable_from_scoring_uses_downloading(
    engine: Engine, library_id: UUID
) -> None:
    manager = ProviderManager([_DisconnectedNicotine()])
    acq = AcquisitionEngine(manager, AcquisitionJobRepository(engine))
    downloads = DownloadManager(manager, acq)
    job = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_TRACK,
        artist="Alice in Chains",
        title="Grind",
    )
    acq.queue(job.id)
    acq.advance(job.id, AcquisitionJobState.SEARCHING)
    acq.advance(job.id, AcquisitionJobState.COLLECTING_RESULTS)
    acq.advance(job.id, AcquisitionJobState.SCORING)

    handle = downloads.start(job.id, _result("nicotine_plus", "nic-next", "08-Grind.mp3"))

    assert handle is None
    loaded = acq.get(job.id)
    assert loaded is not None
    assert loaded.state is AcquisitionJobState.DOWNLOAD_FAILED
    history = "\n".join(loaded.history)
    assert "scoring -> downloading" in history
    assert "downloading -> download_failed" in history
    assert "scoring -> download_failed" not in history

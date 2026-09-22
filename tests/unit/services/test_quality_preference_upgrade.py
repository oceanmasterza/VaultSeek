"""Scoped QUALITY_UPGRADE prefers lossless even when min bitrate is met."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.core.config import AcquisitionConfig
from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.acquisition_job import AcquisitionJobType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.library_quality import track_meets_quality_prefs
from vaultseek.services.provider_manager import ProviderManager
from vaultseek.services.quality_upgrade_analyzer import QualityUpgradeAnalyzer

_NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _mp3(library_id: UUID, *, bitrate: int = 320, path: str) -> Track:
    return Track(
        id=generate_uuid7(),
        library_id=library_id,
        zone=LibraryZone.LIBRARY,
        file_path=path,
        file_name=Path(path).name,
        file_size=100,
        file_modified=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
        title="Soul Messiah",
        codec="MP3",
        bitrate=bitrate,
        is_lossless=False,
        quality_score=40.0,
    )


def _flac(library_id: UUID, *, path: str) -> Track:
    return Track(
        id=generate_uuid7(),
        library_id=library_id,
        zone=LibraryZone.LIBRARY,
        file_path=path,
        file_name=Path(path).name,
        file_size=100,
        file_modified=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
        title="Soul Messiah",
        codec="FLAC",
        bitrate=1411,
        is_lossless=True,
        quality_score=95.0,
    )


def test_health_still_accepts_320_mp3_under_prefer_lossless_with_min_bitrate() -> None:
    """Library traffic lights keep minimum-acceptable semantics unchanged."""
    prefs = AcquisitionConfig(prefer_lossless=True, preferred_codec="", min_bitrate_kbps=320)
    track = _mp3(generate_uuid7(), bitrate=320, path="C:/lib/a.mp3")
    assert track_meets_quality_prefs(track, prefs) is True


def test_scoped_upgrade_creates_flac_job_for_320_mp3_when_prefer_lossless(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    tracks = TrackRepository(engine)
    audio = tmp_path / "soul.mp3"
    audio.write_bytes(b"mp3")
    track = _mp3(library_id, bitrate=320, path=str(audio))
    tracks.upsert(track)

    acq = AcquisitionEngine(ProviderManager([]), AcquisitionJobRepository(engine))
    analyzer = QualityUpgradeAnalyzer(tracks)
    prefs = AcquisitionConfig(prefer_lossless=True, preferred_codec="", min_bitrate_kbps=320)
    job = analyzer.create_job_for_track(acq, track.id, prefs)
    assert job is not None
    assert job.job_type is AcquisitionJobType.QUALITY_UPGRADE
    assert job.preferred_codec == "FLAC"
    assert (job.extra or {}).get("source_track_id") == str(track.id)


def test_scoped_upgrade_skips_already_lossless(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    tracks = TrackRepository(engine)
    audio = tmp_path / "soul.flac"
    audio.write_bytes(b"flac")
    track = _flac(library_id, path=str(audio))
    tracks.upsert(track)

    acq = AcquisitionEngine(ProviderManager([]), AcquisitionJobRepository(engine))
    analyzer = QualityUpgradeAnalyzer(tracks)
    prefs = AcquisitionConfig(prefer_lossless=True, preferred_codec="", min_bitrate_kbps=320)
    assert analyzer.create_job_for_track(acq, track.id, prefs) is None


def test_scoped_upgrade_skips_acceptable_mp3_when_prefer_lossless_off(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    tracks = TrackRepository(engine)
    audio = tmp_path / "soul.mp3"
    audio.write_bytes(b"mp3")
    track = _mp3(library_id, bitrate=320, path=str(audio))
    tracks.upsert(track)

    acq = AcquisitionEngine(ProviderManager([]), AcquisitionJobRepository(engine))
    analyzer = QualityUpgradeAnalyzer(tracks)
    prefs = AcquisitionConfig(prefer_lossless=False, preferred_codec="MP3", min_bitrate_kbps=192)
    assert track_meets_quality_prefs(track, prefs) is True
    assert analyzer.create_job_for_track(acq, track.id, prefs) is None

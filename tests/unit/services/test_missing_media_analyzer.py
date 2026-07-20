"""Unit tests for MissingMediaAnalyzer."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJobState, AcquisitionJobType
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.plugins.builtin.musicbrainz.provider import OfficialTrack, ReleaseTracklist
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.missing_media_analyzer import MediaGapKind, MissingMediaAnalyzer
from vaultseek.services.provider_manager import ProviderManager

_RELEASE_MBID = "11111111-2222-3333-4444-555555555555"
_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _seed_album(engine: Engine, library_id: UUID, artist_id: UUID) -> UUID:
    album = Album(
        id=generate_uuid7(),
        title="Test Album",
        sort_title="Test Album",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist_id,
        mbid=_RELEASE_MBID,
        track_count=3,
    )
    AlbumRepository(engine).create(album)
    return album.id


def _insert_track(
    engine: Engine,
    *,
    library_id: UUID,
    album_id: UUID,
    artist_id: UUID,
    track_number: int,
    title: str,
) -> None:
    track = Track(
        id=generate_uuid7(),
        library_id=library_id,
        zone=LibraryZone.LIBRARY,
        file_path=f"C:/library/{track_number:02d} - {title}.flac",
        file_name=f"{track_number:02d} - {title}.flac",
        file_size=1024,
        file_modified=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
        album_id=album_id,
        artist_id=artist_id,
        title=title,
        track_number=track_number,
    )
    TrackRepository(engine).upsert(track)


def _analyzer(engine: Engine, musicbrainz: MagicMock) -> MissingMediaAnalyzer:
    return MissingMediaAnalyzer(
        AlbumRepository(engine),
        TrackRepository(engine),
        musicbrainz,
        ArtistRepository(engine),
    )


def test_analyze_album_reports_missing_tracks(
    engine: Engine,
    library_id: UUID,
    artist_id: UUID,
) -> None:
    album_id = _seed_album(engine, library_id, artist_id)
    _insert_track(
        engine,
        library_id=library_id,
        album_id=album_id,
        artist_id=artist_id,
        track_number=1,
        title="First",
    )
    tracklist = ReleaseTracklist(
        release_mbid=_RELEASE_MBID,
        title="Test Album",
        artist="Test Artist",
        tracks=(
            OfficialTrack(number=1, title="First", recording_mbid="rec-1"),
            OfficialTrack(number=2, title="Second", recording_mbid="rec-2"),
            OfficialTrack(number=3, title="Third", recording_mbid="rec-3"),
        ),
    )
    musicbrainz = MagicMock()
    musicbrainz.lookup_release_tracklist.return_value = tracklist

    gaps = _analyzer(engine, musicbrainz).analyze_album(library_id, album_id)

    missing = [gap for gap in gaps if gap.kind is MediaGapKind.MISSING_TRACK]
    assert len(missing) == 2
    assert {gap.track_number for gap in missing} == {2, 3}
    assert any(gap.kind is MediaGapKind.INCOMPLETE_ALBUM for gap in gaps)


def test_analyze_album_returns_empty_when_fully_owned(
    engine: Engine,
    library_id: UUID,
    artist_id: UUID,
) -> None:
    album_id = _seed_album(engine, library_id, artist_id)
    for number, title in ((1, "First"), (2, "Second")):
        _insert_track(
            engine,
            library_id=library_id,
            album_id=album_id,
            artist_id=artist_id,
            track_number=number,
            title=title,
        )
    tracklist = ReleaseTracklist(
        release_mbid=_RELEASE_MBID,
        title="Test Album",
        artist="Test Artist",
        tracks=(
            OfficialTrack(number=1, title="First"),
            OfficialTrack(number=2, title="Second"),
        ),
    )
    musicbrainz = MagicMock()
    musicbrainz.lookup_release_tracklist.return_value = tracklist

    assert _analyzer(engine, musicbrainz).analyze_album(library_id, album_id) == []


def test_create_jobs_for_library_persists_missing_track_jobs(
    engine: Engine,
    library_id: UUID,
    artist_id: UUID,
) -> None:
    artist = ArtistRepository(engine).get(artist_id)
    assert artist is not None
    album_id = _seed_album(engine, library_id, artist_id)
    _insert_track(
        engine,
        library_id=library_id,
        album_id=album_id,
        artist_id=artist_id,
        track_number=1,
        title="First",
    )
    tracklist = ReleaseTracklist(
        release_mbid=_RELEASE_MBID,
        title="Test Album",
        artist=artist.name,
        tracks=(
            OfficialTrack(number=1, title="First"),
            OfficialTrack(number=2, title="Second"),
        ),
    )
    musicbrainz = MagicMock()
    musicbrainz.lookup_release_tracklist.return_value = tracklist
    acquisition_engine = AcquisitionEngine(
        ProviderManager([StubAcquisitionProvider()]),
        AcquisitionJobRepository(engine),
    )

    jobs = _analyzer(engine, musicbrainz).create_jobs_for_library(
        acquisition_engine,
        library_id,
        auto_queue=True,
        preferred_codec="FLAC",
    )

    assert len(jobs) == 1
    assert jobs[0].job_type is AcquisitionJobType.MISSING_TRACK
    assert jobs[0].title == "Second"
    assert jobs[0].artist == artist.name
    assert jobs[0].state is AcquisitionJobState.QUEUED
    assert jobs[0].preferred_codec == "FLAC"

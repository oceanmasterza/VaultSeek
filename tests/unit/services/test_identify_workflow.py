"""End-to-end identify workflow: matcher → assign → tags → jobs (isolated DB)."""

from __future__ import annotations

import base64
import zlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, insert

from vaultseek.core.config import PipelineConfig
from vaultseek.core.event_bus import EventBus
from vaultseek.core.exceptions import ReviewError
from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.tables import libraries
from vaultseek.db.uuid_utils import generate_uuid7, uuid_to_blob
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.artist import Artist
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.review_item import ReviewType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.interfaces.metadata import MetadataQuery
from vaultseek.services.dto.review_dto import ReviewItemCreate
from vaultseek.services.identify_retry_preview import IdentifyRetryPreviewService
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.library_tracklist_matcher import (
    AcquisitionProvenance,
    LibraryTracklistMatcher,
)
from vaultseek.services.review_queue_service import ReviewQueueService
from vaultseek.services.tag_writer import TagWriteRequest, write_embedded_tags

_NOW = datetime(2026, 9, 22, tzinfo=UTC)
_SALVATION_MBID = "2167db99-6fe0-4af8-8ae1-4fbe699008bf"
# Shared with test_tag_writer — zlib-compressed silent MP3 sample.
_MP3_Z = (
    "eNr7/7klhQEdRGTmpQMpfiBmZmBg0mBQIgRWEQL/CQGgXew+jr6uxnqW5grMYDfpTGBgEOFQYV3j"
    "y8A4C+SOWdeTa9Cc+v+zSgoDYwpjxJoFHAzMCkxLIx0EGBgOmMgvB5r57zwPRwITz+7r7iAbHvyS"
    "Pqnx/3OLCzNbx+yAijMyDNIf66Z8nF3BwJHB3HbyYE/qgRkbTlXwbRG5ufhzmPqjzyEONrI7HVc+"
    "EfnxkKVvsxjQD9v//+UR4mx52uBlwCzEkJC0zIsrXYjNTCTD+JmGxYGjDpGCHIyGK15otRu7TObg"
    "T/QpYTLwXzvFScrvmLKkdVOsYI9/4ycbfmFh/4hn+3bLzfsfPzv93MPwX0v6fLc2vZb+//a1kIRM"
    "m5Vp3dZNu6Tv/vfN/7kmJf7/j8mvmLgUGk6wMjAISP//HOLCxTxFPuHMoR4GIUG7NYYTHRjMDPSP"
    "9WleevLzeF3Iew2J+h8MJ2ad1WC8YbHJojm5wGq5T+EqQ3aT4oI/6raz/9iICLK/Cfl/7OmOFauN"
    "6x81tcn/Flm0aP//nYea2rg7+mvsHjU0WAmxtaz99GzLXV1YlAAAvp7p0A=="
)


@pytest.fixture
def library_id(engine: Engine) -> UUID:
    lib_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(libraries).values(
                id=uuid_to_blob(lib_id),
                name="Identify workflow",
                incoming_path="C:/incoming",
                staging_path="C:/staging",
                library_path="C:/library",
                archive_path="C:/archive",
                created_at=_NOW.isoformat(),
                updated_at=_NOW.isoformat(),
            )
        )
    return lib_id


def _seed_mp3(path: Path) -> None:
    path.write_bytes(zlib.decompress(base64.b64decode(_MP3_Z)))


def test_assignment_albums_and_slots_contract(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    artists = ArtistRepository(engine)
    albums = AlbumRepository(engine)
    tracks_repo = TrackRepository(engine)
    reviews = ReviewRepository(engine)
    artist = Artist(
        id=generate_uuid7(),
        name="Alphaville",
        sort_name="Alphaville",
        created_at=_NOW,
        updated_at=_NOW,
    )
    artists.create(artist)
    album = Album(
        id=generate_uuid7(),
        title="Salvation",
        sort_title="Salvation",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
        year=1999,
        mbid=_SALVATION_MBID,
    )
    albums.create(album)
    lib_file = tmp_path / "10 - Soul Messiah.flac"
    lib_file.write_bytes(b"flac")
    tracks_repo.upsert(
        Track(
            id=generate_uuid7(),
            library_id=library_id,
            zone=LibraryZone.LIBRARY,
            file_path=str(lib_file),
            file_name=lib_file.name,
            file_size=4,
            file_modified=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
            title="Soul Messiah",
            album_id=album.id,
            artist_id=artist.id,
            track_number=10,
            disc_number=1,
            is_lossless=True,
        )
    )
    service = ReviewQueueService(
        reviews,
        tracks_repo,
        EventBus(),
        album_repository=albums,
        artist_repository=artists,
    )
    choices = service.assignment_albums(library_id)
    assert len(choices) == 1
    assert choices[0].album_id == album.id
    assert choices[0].artist_name == "Alphaville"
    assert choices[0].album_title == "Salvation"
    assert choices[0].year == 1999
    slots = service.assignment_slots(library_id, album.id)
    assert len(slots) == 1
    assert slots[0].title == "Soul Messiah"
    assert slots[0].track_number == 10


def test_assign_album_slot_writes_tags_and_enqueues_pipeline(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    artists = ArtistRepository(engine)
    albums = AlbumRepository(engine)
    tracks_repo = TrackRepository(engine)
    reviews = ReviewRepository(engine)
    jobs = JobRepository(engine)
    queue = JobQueueService(jobs, PipelineConfig())
    artist = Artist(
        id=generate_uuid7(),
        name="Alphaville",
        sort_name="Alphaville",
        created_at=_NOW,
        updated_at=_NOW,
    )
    artists.create(artist)
    album = Album(
        id=generate_uuid7(),
        title="Salvation",
        sort_title="Salvation",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
        mbid=_SALVATION_MBID,
    )
    albums.create(album)
    lib_file = tmp_path / "lib" / "10 - Soul Messiah.flac"
    lib_file.parent.mkdir()
    lib_file.write_bytes(b"flac")
    tracks_repo.upsert(
        Track(
            id=generate_uuid7(),
            library_id=library_id,
            zone=LibraryZone.LIBRARY,
            file_path=str(lib_file),
            file_name=lib_file.name,
            file_size=4,
            file_modified=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
            title="Soul Messiah",
            album_id=album.id,
            artist_id=artist.id,
            track_number=10,
            is_lossless=True,
        )
    )
    incoming_path = tmp_path / "in" / "10 - Soul Messiah.mp3"
    incoming_path.parent.mkdir()
    _seed_mp3(incoming_path)
    track_id = generate_uuid7()
    tracks_repo.upsert(
        Track(
            id=track_id,
            library_id=library_id,
            zone=LibraryZone.INCOMING,
            file_path=str(incoming_path),
            file_name=incoming_path.name,
            file_size=incoming_path.stat().st_size,
            file_modified=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
            title="01a090ad",
            needs_review=True,
            bitrate=320000,
        )
    )
    service = ReviewQueueService(
        reviews,
        tracks_repo,
        EventBus(),
        job_queue=queue,
        album_repository=albums,
        artist_repository=artists,
    )
    item_id = service.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="Unknown",
            track_id=track_id,
            confidence=0.4,
        ),
        now=_NOW,
    )
    service.assign_album_slot(
        item_id,
        album_id=album.id,
        title="Soul Messiah",
        track_number=10,
        disc_number=1,
        artist_id=artist.id,
        now=_NOW,
    )
    updated = tracks_repo.get_by_id(track_id)
    assert updated is not None
    assert updated.album_id == album.id
    assert updated.title == "Soul Messiah"
    from mutagen.mp3 import EasyMP3

    tags = EasyMP3(str(incoming_path))
    assert tags["title"] == ["Soul Messiah"]
    assert tags["album"] == ["Salvation"]
    assert tags["artist"] == ["Alphaville"]
    assert reviews.list_pending_for_track(track_id) == []
    from vaultseek.models.entities.job import JobStatus

    enqueued = {
        job.job_type
        for status in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.COMPLETED)
        for job in jobs.list_by_status(status, library_id=library_id)
    }
    assert JobType.DETECT_DUPLICATES in enqueued or JobType.ORGANIZE_FILE in enqueued


def test_apply_safe_matches_reports_failure_without_stopping_batch(
    engine: Engine, library_id: UUID, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artists = ArtistRepository(engine)
    albums = AlbumRepository(engine)
    tracks_repo = TrackRepository(engine)
    reviews = ReviewRepository(engine)
    artist = Artist(
        id=generate_uuid7(),
        name="Alphaville",
        sort_name="Alphaville",
        created_at=_NOW,
        updated_at=_NOW,
    )
    artists.create(artist)
    album = Album(
        id=generate_uuid7(),
        title="Salvation",
        sort_title="Salvation",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
        mbid=_SALVATION_MBID,
    )
    albums.create(album)
    lib_file = tmp_path / "12 - Pandora's Lullaby.flac"
    lib_file.write_bytes(b"flac")
    tracks_repo.upsert(
        Track(
            id=generate_uuid7(),
            library_id=library_id,
            zone=LibraryZone.LIBRARY,
            file_path=str(lib_file),
            file_name=lib_file.name,
            file_size=4,
            file_modified=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
            title="Pandora's Lullaby",
            album_id=album.id,
            artist_id=artist.id,
            track_number=12,
            duration_ms=268000,
            is_lossless=True,
        )
    )
    ok_path = tmp_path / "12 - Pandora's Lullaby.mp3"
    _seed_mp3(ok_path)
    ok_id = generate_uuid7()
    tracks_repo.upsert(
        Track(
            id=ok_id,
            library_id=library_id,
            zone=LibraryZone.INCOMING,
            file_path=str(ok_path),
            file_name=ok_path.name,
            file_size=ok_path.stat().st_size,
            file_modified=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
            title="Pandora's Lullaby",
            track_number=12,
            duration_ms=268100,
            bitrate=320000,
            needs_review=True,
        )
    )
    review_queue = ReviewQueueService(
        reviews,
        tracks_repo,
        EventBus(),
        album_repository=albums,
        artist_repository=artists,
        library_matcher=LibraryTracklistMatcher(
            track_repo=tracks_repo,
            album_repo=albums,
            artist_repo=artists,
        ),
    )
    review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="Unknown",
            track_id=ok_id,
            confidence=0.3,
        ),
        now=_NOW,
    )

    def _always_fail(*_a: object, **_k: object) -> None:
        raise ReviewError("simulated failure")

    monkeypatch.setattr(review_queue, "assign_album_slot", _always_fail)
    preview = IdentifyRetryPreviewService(
        review_repo=reviews,
        track_repo=tracks_repo,
        file_identity_repo=FileIdentityRepository(engine),
        library_matcher=LibraryTracklistMatcher(
            track_repo=tracks_repo, album_repo=albums, artist_repo=artists
        ),
        review_queue=review_queue,
    )
    report = preview.apply_safe_matches(library_id, dry_run=False)
    assert report.failed >= 1
    assert any(row.status == "failed" for row in report.results)
    dry = preview.apply_safe_matches(library_id, dry_run=True)
    assert dry.applied == 0
    assert dry.results == ()


def test_matcher_seven_salvation_titles_with_better_copies(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    artists = ArtistRepository(engine)
    albums = AlbumRepository(engine)
    tracks_repo = TrackRepository(engine)
    artist = Artist(
        id=generate_uuid7(),
        name="Alphaville",
        sort_name="Alphaville",
        created_at=_NOW,
        updated_at=_NOW,
    )
    artists.create(artist)
    album = Album(
        id=generate_uuid7(),
        title="Salvation",
        sort_title="Salvation",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
        mbid=_SALVATION_MBID,
    )
    albums.create(album)
    songs = [
        (1, "Point Of Know Return", 240000),
        (2, "Control", 230000),
        (3, "Spirit Of The Age", 250000),
        (4, "Dangerous Places", 245000),
        (10, "Soul Messiah", 292000),
        (11, "New Horizons", 260000),
        (12, "Pandora's Lullaby", 268000),
    ]
    for number, title, duration in songs:
        path = tmp_path / "lib" / f"{number:02d} - {title}.flac"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"flac")
        tracks_repo.upsert(
            Track(
                id=generate_uuid7(),
                library_id=library_id,
                zone=LibraryZone.LIBRARY,
                file_path=str(path),
                file_name=path.name,
                file_size=4,
                file_modified=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
                title=title,
                album_id=album.id,
                artist_id=artist.id,
                track_number=number,
                duration_ms=duration,
                is_lossless=True,
            )
        )
    matcher = LibraryTracklistMatcher(
        track_repo=tracks_repo, album_repo=albums, artist_repo=artists
    )
    provenance = AcquisitionProvenance(
        artist="Alphaville", album="Salvation", mb_release_id=_SALVATION_MBID
    )
    for number, title, duration in songs:
        incoming = Track(
            id=generate_uuid7(),
            library_id=library_id,
            zone=LibraryZone.INCOMING,
            file_path=str(tmp_path / "in" / f"{number:02d} - {title}.mp3"),
            file_name=f"{number:02d} - {title}.mp3",
            file_size=1,
            file_modified=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
            title=title,
            track_number=number,
            duration_ms=duration + 50,
            bitrate=320000,
        )
        result = matcher.match(
            incoming,
            MetadataQuery(
                title=title,
                artist="Alphaville",
                track_number=number,
                duration_ms=duration + 50,
            ),
            provenance=provenance,
        )
        assert result.unique is not None, title
        assert result.unique.album_title == "Salvation", title
        assert result.unique.exact_release is True, title
        assert result.unique.existing_is_better is True, title


def test_tag_write_request_api_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "song.mp3"
    _seed_mp3(path)
    result = write_embedded_tags(
        str(path),
        TagWriteRequest(title="Soul Messiah", artist="Alphaville", album="Salvation"),
        backup_dir=tmp_path / "backups",
    )
    assert result.wrote is True
    assert result.backup_path is not None
    from mutagen.mp3 import EasyMP3

    tags = EasyMP3(str(path))
    assert tags["title"] == ["Soul Messiah"]

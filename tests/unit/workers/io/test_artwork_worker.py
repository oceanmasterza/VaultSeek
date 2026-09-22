"""Unit tests for vaultseek.workers.io.artwork_worker.ArtworkWorker."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image
from sqlalchemy import Engine, insert

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artwork_repo import ArtworkRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.tables import albums
from vaultseek.db.uuid_utils import generate_uuid7, uuid_to_blob
from vaultseek.models.entities.job import Job, JobStatus, JobType
from vaultseek.models.interfaces.artwork import ArtworkQuery, ArtworkResult
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.review_queue_service import ReviewQueueService
from vaultseek.workers.io.artwork_worker import ArtworkWorker

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "green").save(buffer, "PNG")
    return buffer.getvalue()


class _StubProvider:
    def __init__(
        self,
        provider_id: str,
        priority: int,
        result: ArtworkResult | None,
    ) -> None:
        self.provider_id = provider_id
        self.priority = priority
        self._result = result
        self.calls = 0
        self.queries: list[ArtworkQuery] = []

    def fetch(self, query: ArtworkQuery) -> ArtworkResult | None:
        self.calls += 1
        self.queries.append(query)
        return self._result


def _result(source: str, width: int, height: int, *, data: bytes | None = None) -> ArtworkResult:
    payload = data if data is not None else _png(width, height)
    return ArtworkResult(
        source=source,
        data=payload,
        mime_type="image/png",
        width=width,
        height=height,
        confidence=0.9,
        source_id=None,
    )


def _attach_album(
    engine: Engine,
    track_repo: TrackRepository,
    track_id: UUID,
    *,
    title: str = "OK Computer",
    mbid: str | None = None,
) -> UUID:
    """Give a track a real album row so artwork search is allowed."""
    from dataclasses import replace

    album_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(albums).values(
                id=uuid_to_blob(album_id),
                title=title,
                sort_title=title,
                mbid=mbid,
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    track = track_repo.get_by_id(track_id)
    assert track is not None
    track_repo.upsert(replace(track, album_id=album_id))
    return album_id


@pytest.fixture
def artwork_repo(engine: Engine) -> ArtworkRepository:
    return ArtworkRepository(engine)


@pytest.fixture
def album_repo(engine: Engine) -> AlbumRepository:
    return AlbumRepository(engine)


@pytest.fixture
def artwork_dir(tmp_path: Path) -> Path:
    return tmp_path / "artwork_cache"


def _make_worker(
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    providers: list[_StubProvider],
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    artwork_dir: Path,
) -> ArtworkWorker:
    return ArtworkWorker(
        track_repo,
        album_repo,
        artwork_repo,
        providers,  # type: ignore[arg-type]
        review_queue,
        job_queue,
        artwork_dir=artwork_dir,
        min_width=500,
        min_height=500,
    )


def _running_job(
    job_queue: JobQueueService, job_repo: JobRepository, library_id: UUID, track_id: UUID
) -> Job:
    job_id = job_queue.enqueue(
        JobType.FETCH_ARTWORK, library_id, {"track_id": str(track_id)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)
    job = job_repo.get(job_id)
    assert job is not None
    return job


def test_good_artwork_is_stored_linked_and_written_to_cache(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    _attach_album(engine, track_repo, track_id)
    provider = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 1200, 1200))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )
    job = _running_job(job_queue, job_repo, library_id, track_id)

    worker.execute(job)

    assert job_repo.get(job.id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    stored = artwork_repo.get_primary_for_track(track_id)
    assert stored is not None
    assert (stored.width, stored.height) == (1200, 1200)
    assert Path(stored.file_path).is_file()
    assert Path(stored.file_path).is_relative_to(artwork_dir)
    assert review_queue.get_pending(library_id) == []


def test_no_artwork_does_not_park_track_review(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    _attach_album(engine, track_repo, track_id)
    provider = _StubProvider("cover_art_archive", 10, None)
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )
    job = _running_job(job_queue, job_repo, library_id, track_id)

    worker.execute(job)

    updated = job_repo.get(job.id)
    assert updated is not None
    assert updated.status is JobStatus.COMPLETED
    assert updated.payload.get("outcome") == "missing"
    assert review_queue.get_pending(library_id) == []
    assert artwork_repo.has_artwork_for_track(track_id) is False


def test_confident_track_miss_still_leaves_review_empty(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    from dataclasses import replace

    _attach_album(engine, track_repo, track_id)
    track = track_repo.get_by_id(track_id)
    assert track is not None
    track_repo.upsert(replace(track, overall_confidence=0.95, needs_review=False))
    provider = _StubProvider("cover_art_archive", 10, None)
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )

    worker.execute(_running_job(job_queue, job_repo, library_id, track_id))

    assert review_queue.get_pending(library_id) == []
    assert artwork_repo.has_artwork_for_track(track_id) is False


def test_low_res_artwork_is_stored_without_review_blocker(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    _attach_album(engine, track_repo, track_id)
    provider = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 200, 200))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )
    job = _running_job(job_queue, job_repo, library_id, track_id)

    worker.execute(job)

    stored = artwork_repo.get_primary_for_track(track_id)
    assert stored is not None
    assert (stored.width, stored.height) == (200, 200)
    assert job_repo.get(job.id).payload.get("outcome") == "low_res"  # type: ignore[union-attr]
    assert review_queue.get_pending(library_id) == []


def test_good_embedded_art_skips_network_provider(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    _attach_album(engine, track_repo, track_id)
    caa = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 1200, 1200))
    embedded = _StubProvider("embedded_art", 50, _result("embedded_art", 800, 800))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [caa, embedded], review_queue, job_queue, artwork_dir
    )
    job = _running_job(job_queue, job_repo, library_id, track_id)

    worker.execute(job)

    stored = artwork_repo.get_primary_for_track(track_id)
    assert stored is not None
    assert stored.source == "embedded_art"
    assert caa.calls == 0
    assert embedded.calls == 1


def test_network_used_when_embedded_is_below_minimum(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    _attach_album(engine, track_repo, track_id)
    caa = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 900, 900))
    embedded = _StubProvider("embedded_art", 50, _result("embedded_art", 300, 300))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [caa, embedded], review_queue, job_queue, artwork_dir
    )
    job = _running_job(job_queue, job_repo, library_id, track_id)

    worker.execute(job)

    stored = artwork_repo.get_primary_for_track(track_id)
    assert stored is not None
    assert stored.source == "cover_art_archive"
    assert caa.calls == 1
    assert embedded.calls == 1


def test_largest_candidate_wins_when_none_meet_the_minimum(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    _attach_album(engine, track_repo, track_id)
    caa = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 150, 150))
    embedded = _StubProvider("embedded_art", 50, _result("embedded_art", 400, 400))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [caa, embedded], review_queue, job_queue, artwork_dir
    )
    job = _running_job(job_queue, job_repo, library_id, track_id)

    worker.execute(job)

    stored = artwork_repo.get_primary_for_track(track_id)
    assert stored is not None
    assert stored.source == "embedded_art"
    pending = review_queue.get_pending(library_id)
    assert pending == []
    assert job_repo.get(job.id).payload.get("outcome") == "low_res"  # type: ignore[union-attr]


def test_embedded_result_sets_has_embedded_art_even_when_network_wins(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    _attach_album(engine, track_repo, track_id)
    caa = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 900, 900))
    embedded = _StubProvider("embedded_art", 50, _result("embedded_art", 300, 300))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [caa, embedded], review_queue, job_queue, artwork_dir
    )
    job = _running_job(job_queue, job_repo, library_id, track_id)

    worker.execute(job)

    track = track_repo.get_by_id(track_id)
    assert track is not None
    assert track.has_embedded_art is True
    stored = artwork_repo.get_primary_for_track(track_id)
    assert stored is not None
    assert stored.source == "cover_art_archive"


def test_identical_bytes_across_tracks_share_one_artwork_row(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    from vaultseek.db.tables import tracks as tracks_table

    album_id = _attach_album(engine, track_repo, track_id)
    other_track_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(tracks_table).values(
                id=uuid_to_blob(other_track_id),
                library_id=uuid_to_blob(library_id),
                album_id=uuid_to_blob(album_id),
                zone="incoming",
                file_path=f"C:/incoming/{other_track_id}.flac",
                file_name=f"{other_track_id}.flac",
                file_size=1024,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    shared_bytes = _png(800, 800)
    provider = _StubProvider(
        "cover_art_archive", 10, _result("cover_art_archive", 800, 800, data=shared_bytes)
    )
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )

    worker.execute(_running_job(job_queue, job_repo, library_id, track_id))
    worker.execute(_running_job(job_queue, job_repo, library_id, other_track_id))

    first = artwork_repo.get_primary_for_track(track_id)
    second = artwork_repo.get_primary_for_track(other_track_id)
    assert first is not None and second is not None
    assert first.id == second.id
    cache_files = list(artwork_dir.rglob("*.png"))
    assert len(cache_files) == 1
    assert provider.calls == 1


def test_artwork_is_linked_to_the_album_when_the_track_has_one(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    album_id = _attach_album(engine, track_repo, track_id)
    provider = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 900, 900))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )

    worker.execute(_running_job(job_queue, job_repo, library_id, track_id))

    album_art = artwork_repo.get_primary_for_album(album_id)
    assert album_art is not None
    assert album_art.source == "cover_art_archive"


def test_missing_track_fails_the_job(
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    artwork_dir: Path,
) -> None:
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [], review_queue, job_queue, artwork_dir
    )
    missing = generate_uuid7()
    job = _running_job(job_queue, job_repo, library_id, missing)

    worker.execute(job)

    updated = job_repo.get(job.id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert updated.error_message is not None
    assert "not found" in updated.error_message


def test_rerun_is_idempotent(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    _attach_album(engine, track_repo, track_id)
    shared_bytes = _png(700, 700)
    provider = _StubProvider(
        "cover_art_archive", 10, _result("cover_art_archive", 700, 700, data=shared_bytes)
    )
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )

    worker.execute(_running_job(job_queue, job_repo, library_id, track_id))
    worker.execute(_running_job(job_queue, job_repo, library_id, track_id))

    stored = artwork_repo.get_primary_for_track(track_id)
    assert stored is not None
    assert len(list(artwork_dir.rglob("*.png"))) == 1
    assert provider.calls == 1


def test_unknown_album_defers_without_provider_search(
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    provider = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 900, 900))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )
    job = _running_job(job_queue, job_repo, library_id, track_id)

    worker.execute(job)

    updated = job_repo.get(job.id)
    assert updated is not None
    assert updated.status is JobStatus.COMPLETED
    assert updated.payload.get("outcome") == "deferred"
    assert updated.payload.get("reason") == "album_unknown"
    assert provider.calls == 0
    assert artwork_repo.has_artwork_for_track(track_id) is False
    assert review_queue.get_pending(library_id) == []


def test_query_never_uses_recording_or_track_title_fallback(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    from dataclasses import replace

    album_id = _attach_album(engine, track_repo, track_id, title="Salvation")
    track = track_repo.get_by_id(track_id)
    assert track is not None
    track_repo.upsert(
        replace(
            track,
            album_id=album_id,
            mb_recording_id="33333333-3333-3333-3333-333333333333",
            title="Pandora's Lullaby",
        )
    )
    provider = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 900, 900))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )

    worker.execute(_running_job(job_queue, job_repo, library_id, track_id))

    assert provider.calls == 1
    query = provider.queries[0]
    assert query.mb_recording_id is None
    assert query.album == "Salvation"
    # ArtworkQuery has no song-title field; recording id must stay unset.
    assert not hasattr(ArtworkQuery, "title")


def test_same_album_mates_reuse_cover_without_redownload(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    from vaultseek.db.tables import tracks as tracks_table

    album_id = _attach_album(engine, track_repo, track_id)
    mate_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(tracks_table).values(
                id=uuid_to_blob(mate_id),
                library_id=uuid_to_blob(library_id),
                album_id=uuid_to_blob(album_id),
                zone="library",
                file_path=f"C:/library/{mate_id}.flac",
                file_name=f"{mate_id}.flac",
                file_size=1024,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    provider = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 1000, 1000))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )

    worker.execute(_running_job(job_queue, job_repo, library_id, track_id))
    worker.execute(_running_job(job_queue, job_repo, library_id, mate_id))

    first = artwork_repo.get_primary_for_track(track_id)
    second = artwork_repo.get_primary_for_track(mate_id)
    album_art = artwork_repo.get_primary_for_album(album_id)
    assert first is not None and second is not None and album_art is not None
    assert first.id == second.id == album_art.id
    assert provider.calls == 1
    assert len(list(artwork_dir.rglob("*.png"))) == 1


def test_embedded_art_from_another_release_is_not_applied(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    from dataclasses import replace

    from sqlalchemy import insert

    from vaultseek.db.tables import artists
    from vaultseek.db.tables import tracks as tracks_table

    salvation_id = generate_uuid7()
    no_limit_id = generate_uuid7()
    alphaville_id = generate_uuid7()
    unlimited_id = generate_uuid7()
    no_limit_track_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(artists).values(
                id=uuid_to_blob(alphaville_id),
                name="Alphaville",
                sort_name="Alphaville",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
        conn.execute(
            insert(artists).values(
                id=uuid_to_blob(unlimited_id),
                name="2 Unlimited",
                sort_name="2 Unlimited",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
        for album_id, title, artist_id in (
            (salvation_id, "Salvation (Deluxe Version)", alphaville_id),
            (no_limit_id, "No Limit - EP", unlimited_id),
        ):
            conn.execute(
                insert(albums).values(
                    id=uuid_to_blob(album_id),
                    title=title,
                    sort_title=title,
                    album_artist_id=uuid_to_blob(artist_id),
                    created_at="2026-07-15T00:00:00",
                    updated_at="2026-07-15T00:00:00",
                )
            )
        conn.execute(
            insert(tracks_table).values(
                id=uuid_to_blob(no_limit_track_id),
                library_id=uuid_to_blob(library_id),
                album_id=uuid_to_blob(no_limit_id),
                zone="library",
                file_path=f"C:/library/{no_limit_track_id}.mp3",
                file_name=f"{no_limit_track_id}.mp3",
                file_size=1024,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    salvation_track = track_repo.get_by_id(track_id)
    assert salvation_track is not None
    track_repo.upsert(replace(salvation_track, album_id=salvation_id))
    stolen = _png(1400, 1400)
    own_cover = _png(1200, 1200)
    embedded = _StubProvider("embedded_art", 50, _result("embedded_art", 1400, 1400, data=stolen))
    network = _StubProvider(
        "cover_art_archive", 10, _result("cover_art_archive", 1200, 1200, data=own_cover)
    )
    worker = _make_worker(
        track_repo,
        album_repo,
        artwork_repo,
        [network, embedded],
        review_queue,
        job_queue,
        artwork_dir,
    )

    worker.execute(_running_job(job_queue, job_repo, library_id, track_id))
    worker.execute(_running_job(job_queue, job_repo, library_id, no_limit_track_id))

    salvation_art = artwork_repo.get_primary_for_album(salvation_id)
    no_limit_art = artwork_repo.get_primary_for_album(no_limit_id)
    assert salvation_art is not None
    assert salvation_art.source == "embedded_art"
    assert no_limit_art is not None
    assert no_limit_art.source == "cover_art_archive"
    assert no_limit_art.id != salvation_art.id
    assert network.calls == 1
    assert embedded.calls == 2


def test_same_album_miss_does_not_create_review_blocker(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    from vaultseek.db.tables import tracks as tracks_table

    album_id = _attach_album(engine, track_repo, track_id)
    mate_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(tracks_table).values(
                id=uuid_to_blob(mate_id),
                library_id=uuid_to_blob(library_id),
                album_id=uuid_to_blob(album_id),
                zone="library",
                file_path=f"C:/library/{mate_id}.flac",
                file_name=f"{mate_id}.flac",
                file_size=1024,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    provider = _StubProvider("cover_art_archive", 10, None)
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )

    job_a = _running_job(job_queue, job_repo, library_id, track_id)
    job_b = _running_job(job_queue, job_repo, library_id, mate_id)
    worker.execute(job_a)
    worker.execute(job_b)

    assert job_repo.get(job_a.id).payload.get("outcome") == "missing"  # type: ignore[union-attr]
    assert job_repo.get(job_b.id).payload.get("outcome") == "missing"  # type: ignore[union-attr]
    assert review_queue.get_pending(library_id) == []
    assert artwork_repo.get_primary_for_album(album_id) is None


def test_concurrent_same_album_jobs_fetch_cover_once(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    import threading
    import time

    from vaultseek.db.tables import tracks as tracks_table

    album_id = _attach_album(engine, track_repo, track_id)
    mate_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(tracks_table).values(
                id=uuid_to_blob(mate_id),
                library_id=uuid_to_blob(library_id),
                album_id=uuid_to_blob(album_id),
                zone="library",
                file_path=f"C:/library/{mate_id}.flac",
                file_name=f"{mate_id}.flac",
                file_size=1024,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )

    class _SlowProvider:
        provider_id = "cover_art_archive"
        priority = 10

        def __init__(self) -> None:
            self.calls = 0
            self._lock = threading.Lock()
            self._payload = _result("cover_art_archive", 900, 900)

        def fetch(self, query: ArtworkQuery) -> ArtworkResult | None:
            with self._lock:
                self.calls += 1
            time.sleep(0.08)
            return self._payload

    provider = _SlowProvider()
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )
    job_a = _running_job(job_queue, job_repo, library_id, track_id)
    job_b = _running_job(job_queue, job_repo, library_id, mate_id)
    errors: list[BaseException] = []

    def _run(job: Job) -> None:
        try:
            worker.execute(job)
        except BaseException as exc:  # noqa: BLE001 — collect for assertion
            errors.append(exc)

    threads = [
        threading.Thread(target=_run, args=(job_a,)),
        threading.Thread(target=_run, args=(job_b,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert provider.calls == 1
    first = artwork_repo.get_primary_for_track(track_id)
    second = artwork_repo.get_primary_for_track(mate_id)
    album_art = artwork_repo.get_primary_for_album(album_id)
    assert first is not None and second is not None and album_art is not None
    assert first.id == second.id == album_art.id


def test_concurrent_independent_albums_do_not_share_a_global_lock(
    engine: Engine,
    track_repo: TrackRepository,
    album_repo: AlbumRepository,
    artwork_repo: ArtworkRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    artwork_dir: Path,
) -> None:
    import threading
    import time

    from vaultseek.db.tables import tracks as tracks_table

    album_a = _attach_album(engine, track_repo, track_id, title="Album A")
    album_b = generate_uuid7()
    track_b = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(albums).values(
                id=uuid_to_blob(album_b),
                title="Album B",
                sort_title="Album B",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
        conn.execute(
            insert(tracks_table).values(
                id=uuid_to_blob(track_b),
                library_id=uuid_to_blob(library_id),
                album_id=uuid_to_blob(album_b),
                zone="library",
                file_path=f"C:/library/{track_b}.flac",
                file_name=f"{track_b}.flac",
                file_size=1024,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )

    class _SlowProvider:
        provider_id = "cover_art_archive"
        priority = 10

        def __init__(self) -> None:
            self.calls = 0
            self._lock = threading.Lock()
            self._inflight = 0
            self.max_inflight = 0
            self._by_album = {
                "Album A": _result("cover_art_archive", 900, 900, data=_png(900, 900)),
                "Album B": _result("cover_art_archive", 910, 910, data=_png(910, 910)),
            }

        def fetch(self, query: ArtworkQuery) -> ArtworkResult | None:
            with self._lock:
                self.calls += 1
                self._inflight += 1
                self.max_inflight = max(self.max_inflight, self._inflight)
            time.sleep(0.08)
            with self._lock:
                self._inflight -= 1
            album = query.album or ""
            return self._by_album.get(album) or self._by_album["Album A"]

    provider = _SlowProvider()
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )
    job_a = _running_job(job_queue, job_repo, library_id, track_id)
    job_b = _running_job(job_queue, job_repo, library_id, track_b)

    threads = [
        threading.Thread(target=worker.execute, args=(job_a,)),
        threading.Thread(target=worker.execute, args=(job_b,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert provider.calls == 2
    assert provider.max_inflight >= 2
    assert artwork_repo.get_primary_for_album(album_a) is not None
    assert artwork_repo.get_primary_for_album(album_b) is not None

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
from vaultseek.models.entities.review_item import ReviewType
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

    def fetch(self, query: ArtworkQuery) -> ArtworkResult | None:
        self.calls += 1
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


def test_no_artwork_parks_an_artwork_missing_review_item(
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
    provider = _StubProvider("cover_art_archive", 10, None)
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )
    job = _running_job(job_queue, job_repo, library_id, track_id)

    worker.execute(job)

    assert job_repo.get(job.id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    pending = review_queue.get_pending(library_id)
    assert [item.review_type for item in pending] == [ReviewType.ARTWORK_MISSING]
    assert artwork_repo.has_artwork_for_track(track_id) is False


def test_confident_track_skips_artwork_missing_review(
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


def test_low_res_artwork_is_stored_but_flagged_for_review(
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
    provider = _StubProvider("cover_art_archive", 10, _result("cover_art_archive", 200, 200))
    worker = _make_worker(
        track_repo, album_repo, artwork_repo, [provider], review_queue, job_queue, artwork_dir
    )
    job = _running_job(job_queue, job_repo, library_id, track_id)

    worker.execute(job)

    stored = artwork_repo.get_primary_for_track(track_id)
    assert stored is not None
    assert (stored.width, stored.height) == (200, 200)
    pending = review_queue.get_pending(library_id)
    assert [item.review_type for item in pending] == [ReviewType.ARTWORK_LOW_RES]
    assert pending[0].description is not None
    assert "200x200" in pending[0].description


def test_good_embedded_art_skips_network_provider(
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
    assert [item.review_type for item in pending] == [ReviewType.ARTWORK_LOW_RES]


def test_embedded_result_sets_has_embedded_art_even_when_network_wins(
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

    other_track_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(tracks_table).values(
                id=uuid_to_blob(other_track_id),
                library_id=uuid_to_blob(library_id),
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
    from dataclasses import replace

    album_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(albums).values(
                id=uuid_to_blob(album_id),
                title="OK Computer",
                sort_title="OK Computer",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    track = track_repo.get_by_id(track_id)
    assert track is not None
    track_repo.upsert(replace(track, album_id=album_id))
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

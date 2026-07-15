"""Unit tests for musicvault.db.repositories.track_repo.TrackRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.track import LibraryZone, Track

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_track(library_id: UUID, **overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": library_id,
        "zone": LibraryZone.LIBRARY,
        "file_path": f"C:/library/{generate_uuid7()}.flac",
        "file_name": "track.flac",
        "file_size": 1024,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def test_upsert_and_get_by_id_round_trips_every_field(
    engine: Engine, library_id: UUID, artist_id: UUID
) -> None:
    repo = TrackRepository(engine)
    track = _make_track(
        library_id,
        artist_id=artist_id,
        title="Indicator",
        track_number=1,
        disc_number=1,
        duration_ms=300_000,
        bitrate=1000,
        bit_depth=24,
        sample_rate=96000,
        channels=2,
        codec="flac",
        is_lossless=True,
        quality_score=100,
        mb_recording_id="mb-rec-1",
        composer="Allen Watts",
        genre="Trance",
        year=2024,
        has_embedded_art=True,
        is_corrupt=False,
        overall_confidence=0.97,
        needs_review=False,
    )

    repo.upsert(track)
    loaded = repo.get_by_id(track.id)

    assert loaded == track


def test_get_by_id_returns_none_for_missing_track(engine: Engine) -> None:
    repo = TrackRepository(engine)

    assert repo.get_by_id(generate_uuid7()) is None


def test_get_by_path_finds_matching_track(engine: Engine, library_id: UUID) -> None:
    repo = TrackRepository(engine)
    track = _make_track(library_id, file_path="C:/library/unique-path.flac")
    repo.upsert(track)

    assert repo.get_by_path("C:/library/unique-path.flac") == track
    assert repo.get_by_path("C:/library/no-such-path.flac") is None


def test_upsert_batch_persists_multiple_tracks_and_returns_count(
    engine: Engine, library_id: UUID
) -> None:
    repo = TrackRepository(engine)
    batch = [_make_track(library_id) for _ in range(5)]

    count = repo.upsert_batch(batch)

    assert count == 5
    loaded_ids = {loaded.id for t in batch if (loaded := repo.get_by_id(t.id)) is not None}
    assert loaded_ids == {t.id for t in batch}


def test_upsert_batch_of_empty_sequence_returns_zero(engine: Engine) -> None:
    repo = TrackRepository(engine)

    assert repo.upsert_batch([]) == 0


def test_get_by_library_filters_by_zone(engine: Engine, library_id: UUID) -> None:
    repo = TrackRepository(engine)
    in_library = _make_track(library_id, zone=LibraryZone.LIBRARY)
    in_staging = _make_track(library_id, zone=LibraryZone.STAGING)
    repo.upsert(in_library)
    repo.upsert(in_staging)

    results = repo.get_by_library(library_id, LibraryZone.LIBRARY)

    assert {t.id for t in results} == {in_library.id}


def test_get_by_library_without_zone_returns_every_zone(engine: Engine, library_id: UUID) -> None:
    repo = TrackRepository(engine)
    in_library = _make_track(library_id, zone=LibraryZone.LIBRARY)
    in_staging = _make_track(library_id, zone=LibraryZone.STAGING)
    repo.upsert(in_library)
    repo.upsert(in_staging)

    results = repo.get_by_library(library_id)

    assert {t.id for t in results} == {in_library.id, in_staging.id}


def test_get_by_library_respects_offset_and_limit(engine: Engine, library_id: UUID) -> None:
    repo = TrackRepository(engine)
    for i in range(5):
        repo.upsert(_make_track(library_id, file_path=f"C:/library/track-{i}.flac"))

    page = repo.get_by_library(library_id, offset=2, limit=2)

    assert len(page) == 2


def test_update_zone_moves_a_track_between_zones(engine: Engine, library_id: UUID) -> None:
    repo = TrackRepository(engine)
    track = _make_track(library_id, zone=LibraryZone.INCOMING)
    repo.upsert(track)

    repo.update_zone(track.id, LibraryZone.STAGING)

    loaded = repo.get_by_id(track.id)
    assert loaded is not None
    assert loaded.zone is LibraryZone.STAGING

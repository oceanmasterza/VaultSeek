"""Unit tests for musicvault.db.tables.

These tests exercise the schema directly against a real (temp file)
SQLite database rather than mocking SQLAlchemy, because the whole point
of this module is DDL correctness — foreign keys, uniqueness, and
defaults only mean something when SQLite itself enforces them.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, insert, select, text
from sqlalchemy.exc import IntegrityError

from musicvault.db.tables import (
    duplicate_groups,
    file_identity,
    jobs,
    libraries,
    metadata,
    metadata_confidence,
    operations,
    rollback_snapshots,
    tracks,
)
from musicvault.db.uuid_utils import generate_uuid7, uuid_to_blob

EXPECTED_TABLE_NAMES = {
    "libraries",
    "artists",
    "albums",
    "tracks",
    "file_identity",
    "metadata_confidence",
    "jobs",
    "review_items",
    "rules",
    "duplicate_groups",
    "duplicate_members",
    "operations",
    "change_history",
    "rollback_snapshots",
    "media_server_state",
}


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """A real temp-file SQLite engine with foreign keys enforced and the
    full schema created — mirrors how the app will actually run."""
    from sqlalchemy import create_engine

    db_path = tmp_path / "schema_test.db"
    eng = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(eng, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    metadata.create_all(eng)
    yield eng
    eng.dispose()


def _insert_library(eng: Engine) -> bytes:
    library_id = uuid_to_blob(generate_uuid7())
    with eng.begin() as conn:
        conn.execute(
            insert(libraries).values(
                id=library_id,
                name="Test Library",
                incoming_path="C:/incoming",
                staging_path="C:/staging",
                library_path="C:/library",
                archive_path="C:/archive",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    return library_id


def _insert_track(eng: Engine, library_id: bytes) -> bytes:
    track_id = uuid_to_blob(generate_uuid7())
    with eng.begin() as conn:
        conn.execute(
            insert(tracks).values(
                id=track_id,
                library_id=library_id,
                zone="library",
                file_path=f"C:/library/{track_id.hex()}.flac",
                file_name=f"{track_id.hex()}.flac",
                file_size=1024,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    return track_id


def test_create_all_produces_exactly_the_15_specified_tables(engine: Engine) -> None:
    assert set(metadata.tables) == EXPECTED_TABLE_NAMES
    assert len(metadata.tables) == 15


def test_deferred_undocumented_tables_are_not_created(engine: Engine) -> None:
    deferred = {"artwork", "track_artwork", "album_artwork", "plugin_state", "library_stats"}
    assert deferred.isdisjoint(metadata.tables)


def test_libraries_row_applies_documented_defaults(engine: Engine) -> None:
    library_id = _insert_library(engine)

    with engine.connect() as conn:
        row = conn.execute(
            select(libraries.c.watch_enabled, libraries.c.auto_approve_threshold).where(
                libraries.c.id == library_id
            )
        ).one()

    assert row.watch_enabled == 0
    assert row.auto_approve_threshold == pytest.approx(0.90)


def test_jobs_row_applies_documented_defaults(engine: Engine) -> None:
    library_id = _insert_library(engine)
    job_id = uuid_to_blob(generate_uuid7())

    with engine.begin() as conn:
        conn.execute(
            insert(jobs).values(
                id=job_id,
                library_id=library_id,
                job_type="scan_directory",
                status="pending",
                payload="{}",
                created_at="2026-07-15T00:00:00",
            )
        )

    with engine.connect() as conn:
        row = conn.execute(
            select(jobs.c.priority, jobs.c.attempt_count, jobs.c.max_attempts).where(
                jobs.c.id == job_id
            )
        ).one()

    assert (row.priority, row.attempt_count, row.max_attempts) == (100, 0, 3)


def test_tracks_file_path_uniqueness_is_enforced(engine: Engine) -> None:
    library_id = _insert_library(engine)
    duplicate_path = "C:/library/same.flac"

    with engine.begin() as conn:
        conn.execute(
            insert(tracks).values(
                id=uuid_to_blob(generate_uuid7()),
                library_id=library_id,
                zone="library",
                file_path=duplicate_path,
                file_name="same.flac",
                file_size=1,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(tracks).values(
                id=uuid_to_blob(generate_uuid7()),
                library_id=library_id,
                zone="library",
                file_path=duplicate_path,
                file_name="same.flac",
                file_size=2,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )


def test_tracks_rejects_foreign_key_to_nonexistent_library(engine: Engine) -> None:
    bogus_library_id = uuid_to_blob(generate_uuid7())

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(tracks).values(
                id=uuid_to_blob(generate_uuid7()),
                library_id=bogus_library_id,
                zone="library",
                file_path="C:/library/orphan.flac",
                file_name="orphan.flac",
                file_size=1,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )


def test_jobs_self_referential_parent_job_id(engine: Engine) -> None:
    library_id = _insert_library(engine)
    parent_id = uuid_to_blob(generate_uuid7())
    child_id = uuid_to_blob(generate_uuid7())

    with engine.begin() as conn:
        conn.execute(
            insert(jobs).values(
                id=parent_id,
                library_id=library_id,
                job_type="scan_directory",
                status="completed",
                payload="{}",
                created_at="2026-07-15T00:00:00",
            )
        )
        conn.execute(
            insert(jobs).values(
                id=child_id,
                library_id=library_id,
                job_type="hash_file",
                status="pending",
                payload="{}",
                parent_job_id=parent_id,
                created_at="2026-07-15T00:00:00",
            )
        )

    with engine.connect() as conn:
        row = conn.execute(select(jobs.c.parent_job_id).where(jobs.c.id == child_id)).one()

    assert row.parent_job_id == parent_id


def test_operations_and_rollback_snapshots_circular_fk_round_trip(engine: Engine) -> None:
    """operations.snapshot_id -> rollback_snapshots.id and
    rollback_snapshots.operation_id -> operations.id reference each other;
    both must be insertable by creating the operation first (with a NULL
    snapshot_id), then the snapshot, then backfilling the operation."""
    operation_id = uuid_to_blob(generate_uuid7())
    snapshot_id = uuid_to_blob(generate_uuid7())

    with engine.begin() as conn:
        conn.execute(
            insert(operations).values(
                id=operation_id,
                operation_type="metadata_fix",
                status="running",
                started_at="2026-07-15T00:00:00",
            )
        )
        conn.execute(
            insert(rollback_snapshots).values(
                id=snapshot_id,
                operation_id=operation_id,
                snapshot_data=b"compressed-json",
                created_at="2026-07-15T00:00:00",
            )
        )
        conn.execute(
            operations.update()
            .where(operations.c.id == operation_id)
            .values(snapshot_id=snapshot_id)
        )

    with engine.connect() as conn:
        row = conn.execute(
            select(operations.c.snapshot_id).where(operations.c.id == operation_id)
        ).one()

    assert row.snapshot_id == snapshot_id


def test_metadata_confidence_unique_track_and_field(engine: Engine) -> None:
    library_id = _insert_library(engine)
    track_id = _insert_track(engine, library_id)

    with engine.begin() as conn:
        conn.execute(
            insert(metadata_confidence).values(
                id=uuid_to_blob(generate_uuid7()),
                track_id=track_id,
                field_name="artist",
                confidence=0.95,
                source="musicbrainz",
                updated_at="2026-07-15T00:00:00",
            )
        )

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(metadata_confidence).values(
                id=uuid_to_blob(generate_uuid7()),
                track_id=track_id,
                field_name="artist",
                confidence=0.80,
                source="local_tags",
                updated_at="2026-07-15T00:00:00",
            )
        )


def test_file_identity_primary_key_is_the_track_foreign_key(engine: Engine) -> None:
    library_id = _insert_library(engine)
    track_id = _insert_track(engine, library_id)

    with engine.begin() as conn:
        conn.execute(
            insert(file_identity).values(
                track_id=track_id,
                content_hash_sha256="a" * 64,
                file_size=1024,
                file_modified="2026-07-15T00:00:00",
            )
        )

    with engine.connect() as conn:
        row = conn.execute(
            select(file_identity.c.content_hash_sha256).where(file_identity.c.track_id == track_id)
        ).one()

    assert row.content_hash_sha256 == "a" * 64


def test_duplicate_groups_status_defaults_to_open(engine: Engine) -> None:
    group_id = uuid_to_blob(generate_uuid7())

    with engine.begin() as conn:
        conn.execute(
            insert(duplicate_groups).values(
                id=group_id,
                match_type="fingerprint",
                match_confidence=0.99,
                track_count=2,
                detected_at="2026-07-15T00:00:00",
            )
        )

    with engine.connect() as conn:
        row = conn.execute(
            select(duplicate_groups.c.status).where(duplicate_groups.c.id == group_id)
        ).one()

    assert row.status == "open"


def test_needs_review_partial_index_exists(engine: Engine) -> None:
    with engine.connect() as conn:
        names = {
            row.name
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'index'"))
        }

    assert "idx_tracks_needs_review" in names

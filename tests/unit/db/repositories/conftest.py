"""Shared fixtures for repository tests.

Every repository test needs a real, schema-initialized SQLite database
with foreign keys enforced, and — since `jobs`, `review_items`, `rules`,
and `file_identity` all require a valid `library_id` (and
`file_identity` requires a valid `track_id`) — a library and track row
already inserted to satisfy those foreign keys. There is still no
`LibraryRepository` (no phase creates one yet — libraries are seeded by
the user via the GUI in later phases, not scanned/upserted in bulk like
tracks), so the `library_id` fixture inserts directly via Core. The
`track_id` fixture could go through `TrackRepository` now that it
exists, but stays on a direct Core insert too, to keep both fixtures
consistent and independent of the repository under test in
`test_track_repo.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, event, insert

from musicvault.db.tables import artists, libraries, metadata, tracks
from musicvault.db.uuid_utils import generate_uuid7, uuid_to_blob


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    db_path = tmp_path / "repo_test.db"
    eng = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(eng, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def library_id(engine: Engine) -> UUID:
    lib_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(libraries).values(
                id=uuid_to_blob(lib_id),
                name="Test Library",
                incoming_path="C:/incoming",
                staging_path="C:/staging",
                library_path="C:/library",
                archive_path="C:/archive",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    return lib_id


@pytest.fixture
def artist_id(engine: Engine) -> UUID:
    """A valid `artists.id` for tests that need a real FK target on
    `tracks.artist_id`/`albums.album_artist_id` without exercising
    `ArtistRepository` itself."""
    art_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(artists).values(
                id=uuid_to_blob(art_id),
                name="Test Artist",
                sort_name="Artist, Test",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    return art_id


@pytest.fixture
def track_id(engine: Engine, library_id: UUID) -> UUID:
    trk_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(tracks).values(
                id=uuid_to_blob(trk_id),
                library_id=uuid_to_blob(library_id),
                zone="library",
                file_path=f"C:/library/{trk_id}.flac",
                file_name=f"{trk_id}.flac",
                file_size=1024,
                file_modified="2026-07-15T00:00:00",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    return trk_id

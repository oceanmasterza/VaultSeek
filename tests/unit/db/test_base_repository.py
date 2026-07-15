"""Unit tests for musicvault.db.repositories.base.

Uses the `jobs` table as the vehicle for these tests — see Scope
Decision 2 in docs/architecture/07-roadmap.md (Phase 2) for why the
"batch upsert under a second" acceptance criterion is proven against
`jobs` rather than the not-yet-built `tracks` repository.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, insert, select

from musicvault.db.repositories.base import batch_upsert
from musicvault.db.tables import jobs, libraries, metadata
from musicvault.db.uuid_utils import generate_uuid7, uuid_to_blob


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    from sqlalchemy import create_engine

    db_path = tmp_path / "base_repo_test.db"
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


def _make_job_row(library_id: bytes, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": uuid_to_blob(generate_uuid7()),
        "library_id": library_id,
        "job_type": "scan_directory",
        "status": "pending",
        "payload": "{}",
        "created_at": "2026-07-15T00:00:00",
    }
    row.update(overrides)
    return row


def test_batch_upsert_noop_on_empty_rows(engine: Engine) -> None:
    with engine.begin() as conn:
        batch_upsert(conn, jobs, [], conflict_columns=["id"])

    with engine.connect() as conn:
        count = conn.execute(select(jobs.c.id)).all()

    assert count == []


def test_batch_upsert_inserts_new_rows(engine: Engine) -> None:
    library_id = _insert_library(engine)
    rows = [_make_job_row(library_id) for _ in range(5)]

    with engine.begin() as conn:
        batch_upsert(conn, jobs, rows, conflict_columns=["id"])

    with engine.connect() as conn:
        inserted_ids = {row.id for row in conn.execute(select(jobs.c.id))}

    assert inserted_ids == {row["id"] for row in rows}


def test_batch_upsert_updates_existing_rows_on_conflict(engine: Engine) -> None:
    library_id = _insert_library(engine)
    job_id = uuid_to_blob(generate_uuid7())

    with engine.begin() as conn:
        batch_upsert(
            conn,
            jobs,
            [_make_job_row(library_id, id=job_id, status="pending")],
            conflict_columns=["id"],
        )

    with engine.begin() as conn:
        batch_upsert(
            conn,
            jobs,
            [_make_job_row(library_id, id=job_id, status="completed")],
            conflict_columns=["id"],
        )

    with engine.connect() as conn:
        row = conn.execute(select(jobs.c.status, jobs.c.id).where(jobs.c.id == job_id)).one()

    assert row.status == "completed"


def test_batch_upsert_does_not_duplicate_rows_on_conflict(engine: Engine) -> None:
    library_id = _insert_library(engine)
    job_id = uuid_to_blob(generate_uuid7())

    with engine.begin() as conn:
        batch_upsert(conn, jobs, [_make_job_row(library_id, id=job_id)], conflict_columns=["id"])
        batch_upsert(conn, jobs, [_make_job_row(library_id, id=job_id)], conflict_columns=["id"])

    with engine.connect() as conn:
        matching = conn.execute(select(jobs.c.id).where(jobs.c.id == job_id)).all()

    assert len(matching) == 1


def test_batch_upsert_500_jobs_completes_in_under_one_second(engine: Engine) -> None:
    """The literal acceptance criterion for Phase 2 (see roadmap Scope
    Decision 2): batch upsert 500 rows in under a second."""
    library_id = _insert_library(engine)
    rows = [_make_job_row(library_id) for _ in range(500)]

    start = time.monotonic()
    with engine.begin() as conn:
        batch_upsert(conn, jobs, rows, conflict_columns=["id"])
    elapsed = time.monotonic() - start

    with engine.connect() as conn:
        row_count = len(conn.execute(select(jobs.c.id)).all())

    assert row_count == 500
    assert elapsed < 1.0

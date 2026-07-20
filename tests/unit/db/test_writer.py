"""Unit tests for vaultseek.db.writer.DatabaseWriter."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, event, select

from vaultseek.db.tables import artists, metadata
from vaultseek.db.uuid_utils import generate_uuid7, uuid_to_blob
from vaultseek.db.writer import DatabaseWriter, WriteDTO

_NOW = datetime(2026, 7, 15, tzinfo=UTC).isoformat()


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    db_path = tmp_path / "writer_test.db"
    eng = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(eng, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    metadata.create_all(eng)
    yield eng
    eng.dispose()


def _artist_row(name: str) -> dict[str, object]:
    return {
        "id": uuid_to_blob(generate_uuid7()),
        "name": name,
        "sort_name": name,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _artist_names(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return {row.name for row in conn.execute(select(artists.c.name))}


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 10.0) -> bool:
    """Poll ``predicate`` until it's True or ``timeout`` seconds elapse.

    Used only for the two tests that assert automatic (non-`stop()`-driven)
    flushing — every other test relies on `stop()`'s deterministic drain
    instead of timing.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_submit_then_stop_persists_the_write(engine: Engine) -> None:
    writer = DatabaseWriter(engine)
    writer.start()

    writer.submit(WriteDTO(table="artists", operation="upsert", rows=[_artist_row("Allen Watts")]))
    writer.stop()

    assert _artist_names(engine) == {"Allen Watts"}


def test_stop_drains_everything_still_in_the_inbound_queue(engine: Engine) -> None:
    writer = DatabaseWriter(engine, flush_interval_ms=60_000)  # effectively never idle-flushes
    writer.start()

    for i in range(20):
        writer.submit(
            WriteDTO(table="artists", operation="upsert", rows=[_artist_row(f"Artist {i}")])
        )
    writer.stop()

    assert _artist_names(engine) == {f"Artist {i}" for i in range(20)}


def test_flushes_automatically_once_batch_size_is_reached(engine: Engine) -> None:
    writer = DatabaseWriter(engine, batch_size=2, flush_interval_ms=60_000)
    writer.start()
    try:
        writer.submit(
            WriteDTO(
                table="artists",
                operation="upsert",
                rows=[_artist_row("A"), _artist_row("B")],
            )
        )
        assert _wait_until(lambda: _artist_names(engine) == {"A", "B"})
    finally:
        writer.stop()


def test_flushes_automatically_after_the_idle_interval(engine: Engine) -> None:
    writer = DatabaseWriter(engine, batch_size=5_000, flush_interval_ms=50)
    writer.start()
    try:
        writer.submit(WriteDTO(table="artists", operation="upsert", rows=[_artist_row("Solo")]))
        assert _wait_until(lambda: _artist_names(engine) == {"Solo"})
    finally:
        writer.stop()


def test_multiple_dtos_for_different_tables_apply_in_one_flush(engine: Engine) -> None:
    from sqlalchemy import insert

    from vaultseek.db.tables import jobs, libraries

    library_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(libraries).values(
                id=uuid_to_blob(library_id),
                name="Test Library",
                incoming_path="C:/incoming",
                staging_path="C:/staging",
                library_path="C:/library",
                archive_path="C:/archive",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )

    writer = DatabaseWriter(engine)
    writer.start()

    job_id = generate_uuid7()
    writer.submit(WriteDTO(table="artists", operation="upsert", rows=[_artist_row("Multi")]))
    writer.submit(
        WriteDTO(
            table="jobs",
            operation="upsert",
            rows=[
                {
                    "id": uuid_to_blob(job_id),
                    "library_id": uuid_to_blob(library_id),
                    "job_type": "scan_directory",
                    "status": "pending",
                    "priority": 100,
                    "payload": "{}",
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "created_at": _NOW,
                }
            ],
        )
    )
    writer.stop()

    assert "Multi" in _artist_names(engine)
    with engine.connect() as conn:
        job_row = conn.execute(select(jobs.c.status).where(jobs.c.id == uuid_to_blob(job_id))).one()
    assert job_row.status == "pending"


def test_an_unsupported_operation_is_logged_and_does_not_kill_the_writer_thread(
    engine: Engine,
) -> None:
    """A bad DTO poisons only its own batch (an intentional trade-off — see
    the `_flush_if_pending` docstring) but must not kill the thread, so a
    *later* batch still succeeds. Submitted with a real gap between them
    (longer than the idle flush interval) so they land in separate flushes."""
    writer = DatabaseWriter(engine, flush_interval_ms=50)
    writer.start()

    writer.submit(WriteDTO(table="artists", operation="delete", rows=[_artist_row("Ghost")]))
    time.sleep(0.2)  # let the first (failing) batch flush and fail on its own

    writer.submit(WriteDTO(table="artists", operation="upsert", rows=[_artist_row("Survivor")]))
    writer.stop()

    names = _artist_names(engine)
    assert "Survivor" in names
    assert "Ghost" not in names


def test_stop_without_start_does_not_raise(engine: Engine) -> None:
    writer = DatabaseWriter(engine)

    writer.stop()  # no thread was ever started — must be a no-op, not a crash

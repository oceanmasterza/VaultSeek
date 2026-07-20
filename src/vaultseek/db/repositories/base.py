"""Generic batch upsert helper shared by every repository.

Uses SQLite's ``INSERT ... ON CONFLICT DO UPDATE`` so a batch of rows can
be inserted or updated in a single statement, rather than one round trip
per row — this is what makes "batch upsert 500 rows in under a second"
(see Phase 2's acceptance criteria in docs/architecture/07-roadmap.md)
achievable. Every concrete repository (``JobRepository``,
``ReviewRepository``, ...) builds its plain-dict rows and delegates the
actual SQL to this one, well-tested function rather than reimplementing
upsert logic per table.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


def batch_upsert(
    conn: Connection,
    table: Table,
    rows: Sequence[dict[str, Any]],
    *,
    conflict_columns: Sequence[str],
) -> None:
    """Insert ``rows`` into ``table``, overwriting in place on conflict.

    ``conflict_columns`` names the column(s) that uniquely identify a row
    — almost always the primary key. Every column present in the row
    dicts *other than* the conflict columns is overwritten with the new
    value when a conflict occurs. All rows are assumed to have the same
    keys (every repository builds them from a single entity type).

    No-ops if ``rows`` is empty.
    """
    if not rows:
        return

    statement = sqlite_insert(table).values(list(rows))
    update_columns = {
        column_name: statement.excluded[column_name]
        for column_name in rows[0]
        if column_name not in conflict_columns
    }
    statement = statement.on_conflict_do_update(
        index_elements=list(conflict_columns), set_=update_columns
    )
    conn.execute(statement)

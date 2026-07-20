"""MetadataConfidenceRepository — persistence for `metadata_confidence`."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, delete, select

from vaultseek.db.repositories.base import batch_upsert
from vaultseek.db.tables import metadata_confidence as metadata_confidence_table
from vaultseek.db.uuid_utils import generate_uuid7, uuid_to_blob
from vaultseek.models.value_objects.field_confidence import FieldConfidence


class MetadataConfidenceRepository:
    """Reads and writes per-field confidence rows for a track."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_fields(
        self,
        track_id: UUID,
        fields: Sequence[FieldConfidence],
        *,
        now: datetime | None = None,
    ) -> int:
        """Replace the arbitrated field set for ``track_id``.

        Deletes any existing rows for the track first, then inserts the
        new winners — arbitration always produces a complete field set
        for the fields it considered, so a wipe-and-write keeps orphans
        from previous runs from lingering.
        """
        stamp = (now if now is not None else datetime.now(UTC)).isoformat()
        rows = [
            {
                "id": uuid_to_blob(generate_uuid7()),
                "track_id": uuid_to_blob(track_id),
                "field_name": item.field,
                "value": None if item.value is None else str(item.value),
                "confidence": item.confidence,
                "source": item.source,
                "updated_at": stamp,
            }
            for item in fields
        ]
        with self._engine.begin() as conn:
            conn.execute(
                delete(metadata_confidence_table).where(
                    metadata_confidence_table.c.track_id == uuid_to_blob(track_id)
                )
            )
            if rows:
                batch_upsert(
                    conn,
                    metadata_confidence_table,
                    rows,
                    conflict_columns=["track_id", "field_name"],
                )
        return len(rows)

    def list_for_track(self, track_id: UUID) -> list[FieldConfidence]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(metadata_confidence_table).where(
                    metadata_confidence_table.c.track_id == uuid_to_blob(track_id)
                )
            ).all()
        return [_from_row(row) for row in rows]


def _from_row(row: Row[Any]) -> FieldConfidence:
    raw_value = row.value
    value: str | int | float | None
    if raw_value is None:
        value = None
    else:
        try:
            value = int(raw_value)
        except ValueError:
            try:
                value = float(raw_value)
            except ValueError:
                value = raw_value
    return FieldConfidence(
        field=row.field_name,
        value=value,
        confidence=float(row.confidence),
        source=row.source,
    )

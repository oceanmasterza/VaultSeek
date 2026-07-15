"""FileIdentityRepository — persistence for the `file_identity` table.

`FileIdentity.matches_current_file` (a pure, dependency-free method on
the value object itself) is what a future scanner service will call to
decide whether the hash/fingerprint workers can be skipped — this
repository is only responsible for getting the stored identity in and
out of SQLite.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, select

from musicvault.db.repositories.base import batch_upsert
from musicvault.db.tables import file_identity as file_identity_table
from musicvault.db.uuid_utils import blob_to_uuid, uuid_to_blob
from musicvault.models.value_objects.file_identity import FileIdentity


class FileIdentityRepository:
    """Reads and writes `FileIdentity` value objects against `file_identity`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert(self, identity: FileIdentity) -> None:
        with self._engine.begin() as conn:
            batch_upsert(
                conn,
                file_identity_table,
                [_to_row(identity)],
                conflict_columns=["track_id"],
            )

    def get(self, track_id: UUID) -> FileIdentity | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(file_identity_table).where(
                    file_identity_table.c.track_id == uuid_to_blob(track_id)
                )
            ).first()
        return _from_row(row) if row is not None else None


def _to_row(identity: FileIdentity) -> dict[str, object]:
    return {
        "track_id": uuid_to_blob(identity.track_id),
        "content_hash_sha256": identity.content_hash_sha256,
        "fingerprint_data": identity.fingerprint_data,
        "fingerprint_duration": identity.fingerprint_duration,
        "fingerprint_hash": identity.fingerprint_hash,
        "acoustid_id": identity.acoustid_id,
        "acoustid_score": identity.acoustid_score,
        "file_size": identity.file_size,
        "file_modified": identity.file_modified.isoformat(),
        "hash_computed_at": (
            identity.hash_computed_at.isoformat() if identity.hash_computed_at else None
        ),
        "fingerprint_computed_at": (
            identity.fingerprint_computed_at.isoformat()
            if identity.fingerprint_computed_at
            else None
        ),
    }


def _from_row(row: Row[Any]) -> FileIdentity:
    return FileIdentity(
        track_id=blob_to_uuid(row.track_id),
        content_hash_sha256=row.content_hash_sha256,
        file_size=row.file_size,
        file_modified=datetime.fromisoformat(row.file_modified),
        fingerprint_data=row.fingerprint_data,
        fingerprint_duration=row.fingerprint_duration,
        fingerprint_hash=row.fingerprint_hash,
        acoustid_id=row.acoustid_id,
        acoustid_score=row.acoustid_score,
        hash_computed_at=(
            datetime.fromisoformat(row.hash_computed_at) if row.hash_computed_at else None
        ),
        fingerprint_computed_at=(
            datetime.fromisoformat(row.fingerprint_computed_at)
            if row.fingerprint_computed_at
            else None
        ),
    )

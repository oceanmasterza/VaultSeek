"""TrustedFolderRepository — album folders confirmed by fingerprint sampling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, Row, select

from vaultseek.db.tables import trusted_folders
from vaultseek.db.uuid_utils import blob_to_uuid, uuid_to_blob


@dataclass(frozen=True, slots=True)
class TrustedFolder:
    library_id: UUID
    folder_path: str
    release_mbid: str
    official_track_count: int
    sample_confirmed: int
    trusted_at: datetime


class TrustedFolderRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, library_id: UUID, folder_path: str) -> TrustedFolder | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(trusted_folders)
                .where(trusted_folders.c.library_id == uuid_to_blob(library_id))
                .where(trusted_folders.c.folder_path == folder_path)
            ).first()
        return _from_row(row) if row is not None else None

    def is_trusted(self, library_id: UUID, folder_path: str) -> bool:
        return self.get(library_id, folder_path) is not None

    def upsert(self, entry: TrustedFolder) -> None:
        from vaultseek.db.repositories.base import batch_upsert

        with self._engine.begin() as conn:
            batch_upsert(
                conn,
                trusted_folders,
                [_to_row(entry)],
                conflict_columns=["library_id", "folder_path"],
            )


def _to_row(entry: TrustedFolder) -> dict[str, object]:
    return {
        "library_id": uuid_to_blob(entry.library_id),
        "folder_path": entry.folder_path,
        "release_mbid": entry.release_mbid,
        "official_track_count": entry.official_track_count,
        "sample_confirmed": entry.sample_confirmed,
        "trusted_at": entry.trusted_at.isoformat(),
    }


def _from_row(row: Row[object]) -> TrustedFolder:
    return TrustedFolder(
        library_id=blob_to_uuid(row.library_id),
        folder_path=row.folder_path,
        release_mbid=row.release_mbid,
        official_track_count=row.official_track_count,
        sample_confirmed=row.sample_confirmed,
        trusted_at=datetime.fromisoformat(row.trusted_at),
    )

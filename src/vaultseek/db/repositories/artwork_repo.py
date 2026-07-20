"""ArtworkRepository — persistence for `artwork` + link tables.

Images are deduplicated by ``content_hash_sha256``: :meth:`upsert_image`
returns the existing row's id when the same bytes were already stored,
so re-fetching artwork (retried jobs, shared album art across tracks)
never creates duplicate rows or duplicate cache files.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, func, or_, select

from vaultseek.db.repositories.base import batch_upsert
from vaultseek.db.tables import album_artwork, albums, artists, track_artwork
from vaultseek.db.tables import artwork as artwork_table
from vaultseek.db.tables import tracks as tracks_table
from vaultseek.db.uuid_utils import blob_to_uuid, uuid_to_blob
from vaultseek.models.entities.artwork import Artwork, ArtworkRole
from vaultseek.services.dto.browse_dto import ArtworkBrowseRow


class ArtworkRepository:
    """Reads and writes `Artwork` entities and their track/album links."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_image(self, artwork: Artwork) -> UUID:
        """Insert the image row, or return the existing id for the same
        content hash (images are globally deduplicated)."""
        existing = self.get_by_content_hash(artwork.content_hash_sha256)
        if existing is not None:
            return existing.id
        with self._engine.begin() as conn:
            batch_upsert(conn, artwork_table, [_to_row(artwork)], conflict_columns=["id"])
        return artwork.id

    def get(self, artwork_id: UUID) -> Artwork | None:
        statement = select(artwork_table).where(artwork_table.c.id == uuid_to_blob(artwork_id))
        with self._engine.connect() as conn:
            row = conn.execute(statement).first()
        return _from_row(row) if row is not None else None

    def get_by_content_hash(self, content_hash: str) -> Artwork | None:
        statement = select(artwork_table).where(artwork_table.c.content_hash_sha256 == content_hash)
        with self._engine.connect() as conn:
            row = conn.execute(statement).first()
        return _from_row(row) if row is not None else None

    def link_track(
        self,
        track_id: UUID,
        artwork_id: UUID,
        *,
        role: ArtworkRole = ArtworkRole.FRONT,
        is_primary: bool = True,
    ) -> None:
        row = {
            "track_id": uuid_to_blob(track_id),
            "artwork_id": uuid_to_blob(artwork_id),
            "role": role.value,
            "is_primary": is_primary,
        }
        with self._engine.begin() as conn:
            batch_upsert(conn, track_artwork, [row], conflict_columns=["track_id", "artwork_id"])

    def link_album(
        self,
        album_id: UUID,
        artwork_id: UUID,
        *,
        role: ArtworkRole = ArtworkRole.FRONT,
        is_primary: bool = True,
    ) -> None:
        row = {
            "album_id": uuid_to_blob(album_id),
            "artwork_id": uuid_to_blob(artwork_id),
            "role": role.value,
            "is_primary": is_primary,
        }
        with self._engine.begin() as conn:
            batch_upsert(conn, album_artwork, [row], conflict_columns=["album_id", "artwork_id"])

    def get_primary_for_track(self, track_id: UUID) -> Artwork | None:
        statement = (
            select(artwork_table)
            .join(track_artwork, track_artwork.c.artwork_id == artwork_table.c.id)
            .where(track_artwork.c.track_id == uuid_to_blob(track_id))
            .where(track_artwork.c.is_primary)
        )
        with self._engine.connect() as conn:
            row = conn.execute(statement).first()
        return _from_row(row) if row is not None else None

    def get_primary_for_album(self, album_id: UUID) -> Artwork | None:
        statement = (
            select(artwork_table)
            .join(album_artwork, album_artwork.c.artwork_id == artwork_table.c.id)
            .where(album_artwork.c.album_id == uuid_to_blob(album_id))
            .where(album_artwork.c.is_primary)
        )
        with self._engine.connect() as conn:
            row = conn.execute(statement).first()
        return _from_row(row) if row is not None else None

    def has_artwork_for_track(self, track_id: UUID) -> bool:
        statement = (
            select(track_artwork.c.artwork_id)
            .where(track_artwork.c.track_id == uuid_to_blob(track_id))
            .limit(1)
        )
        with self._engine.connect() as conn:
            return conn.execute(statement).first() is not None

    def list_browse_for_library(
        self,
        library_id: UUID,
        *,
        missing_only: bool = False,
        query: str | None = None,
        limit: int = 500,
        min_width: int = 500,
        min_height: int = 500,
        offset: int = 0,
    ) -> list[ArtworkBrowseRow]:
        """Album-centric artwork status for tracks in this library."""
        lib = uuid_to_blob(library_id)
        track_count = func.count(tracks_table.c.id).label("track_count")
        statement = (
            select(
                albums.c.id.label("album_id"),
                albums.c.title,
                artists.c.name.label("artist_name"),
                track_count,
                artwork_table.c.source,
                artwork_table.c.width,
                artwork_table.c.height,
            )
            .select_from(tracks_table)
            .join(albums, albums.c.id == tracks_table.c.album_id)
            .outerjoin(artists, artists.c.id == albums.c.album_artist_id)
            .outerjoin(album_artwork, album_artwork.c.album_id == albums.c.id)
            .outerjoin(artwork_table, artwork_table.c.id == album_artwork.c.artwork_id)
            .where(tracks_table.c.library_id == lib)
            .group_by(
                albums.c.id,
                albums.c.title,
                artists.c.name,
                artwork_table.c.source,
                artwork_table.c.width,
                artwork_table.c.height,
            )
            .order_by(artists.c.name, albums.c.title)
            .offset(offset)
            .limit(limit)
        )
        if query:
            like = f"%{query}%"
            statement = statement.where(
                or_(albums.c.title.ilike(like), artists.c.name.ilike(like))
            )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()

        results: list[ArtworkBrowseRow] = []
        for row in rows:
            width = int(row.width) if row.width is not None else None
            height = int(row.height) if row.height is not None else None
            has_cover = width is not None
            if has_cover and width is not None and height is not None:
                if width < min_width or height < min_height:
                    status = "low_res"
                else:
                    status = "ok"
            else:
                status = "missing"
            if missing_only and status == "ok":
                continue
            results.append(
                ArtworkBrowseRow(
                    album_id=blob_to_uuid(row.album_id),
                    track_id=None,
                    label=row.title,
                    artist_name=row.artist_name,
                    track_count=int(row.track_count),
                    has_cover=has_cover,
                    cover_source=row.source,
                    width=width,
                    height=height,
                    status=status,
                )
            )
        return results


def _to_row(artwork: Artwork) -> dict[str, object]:
    return {
        "id": uuid_to_blob(artwork.id),
        "content_hash_sha256": artwork.content_hash_sha256,
        "source": artwork.source,
        "source_id": artwork.source_id,
        "mime_type": artwork.mime_type,
        "width": artwork.width,
        "height": artwork.height,
        "file_size": artwork.file_size,
        "file_path": artwork.file_path,
        "created_at": artwork.created_at.isoformat(),
    }


def _from_row(row: Row[Any]) -> Artwork:
    return Artwork(
        id=blob_to_uuid(row.id),
        content_hash_sha256=row.content_hash_sha256,
        source=row.source,
        mime_type=row.mime_type,
        width=row.width,
        height=row.height,
        file_size=row.file_size,
        file_path=row.file_path,
        created_at=datetime.fromisoformat(row.created_at),
        source_id=row.source_id,
    )

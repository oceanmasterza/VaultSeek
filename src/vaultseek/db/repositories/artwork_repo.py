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

from sqlalchemy import Engine, Row, and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from vaultseek.db.repositories.base import batch_upsert
from vaultseek.db.tables import album_artwork, albums, artists, track_artwork
from vaultseek.db.tables import artwork as artwork_table
from vaultseek.db.tables import tracks as tracks_table
from vaultseek.db.uuid_utils import blob_to_uuid, uuid_to_blob
from vaultseek.models.dto.browse_dto import ArtworkBrowseRow
from vaultseek.models.entities.artwork import Artwork, ArtworkRole
from vaultseek.models.services.album_context import release_cover_key


class ArtworkRepository:
    """Reads and writes `Artwork` entities and their track/album links."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_image(self, artwork: Artwork) -> UUID:
        """Insert the image row, or return the existing id for the same
        content hash (images are globally deduplicated).

        Concurrent workers can race past the pre-check; catch the unique
        ``content_hash_sha256`` violation and reuse the winner's id.
        """
        existing = self.get_by_content_hash(artwork.content_hash_sha256)
        if existing is not None:
            return existing.id
        try:
            with self._engine.begin() as conn:
                batch_upsert(conn, artwork_table, [_to_row(artwork)], conflict_columns=["id"])
        except IntegrityError:
            raced = self.get_by_content_hash(artwork.content_hash_sha256)
            if raced is not None:
                return raced.id
            raise
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

    def set_release_provenance(
        self, artwork_id: UUID, *, source_id: str, source: str | None = None
    ) -> None:
        """Attach a trusted release id when the image row still has none."""
        values: dict[str, object] = {"source_id": source_id}
        if source is not None:
            values["source"] = source
        with self._engine.begin() as conn:
            conn.execute(
                update(artwork_table)
                .where(artwork_table.c.id == uuid_to_blob(artwork_id))
                .where(
                    or_(
                        artwork_table.c.source_id.is_(None),
                        artwork_table.c.source_id == "",
                    )
                )
                .values(**values)
            )

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
            if is_primary:
                conn.execute(
                    update(track_artwork)
                    .where(track_artwork.c.track_id == uuid_to_blob(track_id))
                    .where(track_artwork.c.artwork_id != uuid_to_blob(artwork_id))
                    .values(is_primary=False)
                )
            batch_upsert(conn, track_artwork, [row], conflict_columns=["track_id", "artwork_id"])

    def link_album(
        self,
        album_id: UUID,
        artwork_id: UUID,
        *,
        role: ArtworkRole = ArtworkRole.FRONT,
        is_primary: bool = True,
    ) -> bool:
        """Link artwork to an album. Returns False when it would become another release's cover.

        Provenance (``artwork.source_id`` matching ``albums.mbid``) may claim a
        primary even when a different release was the sole prior linkee. Ambiguous
        embedded bytes already primary for another cover key stay blocked.
        Edition spellings of one release may still share a cover.
        """
        trusted = is_primary and self._release_provenanced(artwork_id, album_id)
        if is_primary and not trusted and self.primary_conflicts_with_album(artwork_id, album_id):
            return False
        row = {
            "album_id": uuid_to_blob(album_id),
            "artwork_id": uuid_to_blob(artwork_id),
            "role": role.value,
            "is_primary": is_primary,
        }
        with self._engine.begin() as conn:
            if is_primary:
                conn.execute(
                    update(album_artwork)
                    .where(album_artwork.c.album_id == uuid_to_blob(album_id))
                    .where(album_artwork.c.artwork_id != uuid_to_blob(artwork_id))
                    .values(is_primary=False)
                )
            batch_upsert(conn, album_artwork, [row], conflict_columns=["album_id", "artwork_id"])
            if trusted:
                self._demote_conflicting_primaries(conn, artwork_id, album_id)
        return True

    def primary_conflicts_with_album(self, artwork_id: UUID, album_id: UUID) -> bool:
        """True when this image must not be shown or linked as this album's cover.

        File/slot counts and timestamps never decide identity. Trusted
        ``source_id`` / release MBID matches always win. Same cover-key editions
        may share. Ambiguous cross-release primaries without provenance conflict.
        """
        if self._release_provenanced(artwork_id, album_id):
            return False
        if self._foreign_provenance(artwork_id, album_id):
            return True
        current = self._album_cover_key(album_id)
        if current is None:
            return False
        linkee_keys = self._primary_cover_keys(artwork_id)
        if not linkee_keys:
            return False
        trusted_keys = self._trusted_primary_cover_keys(artwork_id)
        if trusted_keys and current not in trusted_keys:
            return True
        if len(linkee_keys) > 1:
            # Multiple distinct releases already primary — ambiguous without trust.
            return True
        return current not in linkee_keys

    def _release_provenanced(self, artwork_id: UUID, album_id: UUID) -> bool:
        source_id, mbid = self._artwork_and_album_ids(artwork_id, album_id)
        if not source_id or not mbid:
            return False
        return str(source_id) == str(mbid)

    def _foreign_provenance(self, artwork_id: UUID, album_id: UUID) -> bool:
        """True when the image is already bound to a different release MBID."""
        source_id, mbid = self._artwork_and_album_ids(artwork_id, album_id)
        if not source_id:
            return False
        if mbid and str(source_id) == str(mbid):
            return False
        if mbid and str(source_id) != str(mbid):
            return True
        # Album has no MBID: foreign only when another album owns this source_id.
        statement = (
            select(albums.c.id)
            .where(albums.c.mbid == source_id)
            .where(albums.c.id != uuid_to_blob(album_id))
            .limit(1)
        )
        with self._engine.connect() as conn:
            return conn.execute(statement).first() is not None

    def _artwork_and_album_ids(
        self, artwork_id: UUID, album_id: UUID
    ) -> tuple[str | None, str | None]:
        with self._engine.connect() as conn:
            source_id = conn.execute(
                select(artwork_table.c.source_id).where(
                    artwork_table.c.id == uuid_to_blob(artwork_id)
                )
            ).scalar_one_or_none()
            mbid = conn.execute(
                select(albums.c.mbid).where(albums.c.id == uuid_to_blob(album_id))
            ).scalar_one_or_none()
        return (
            str(source_id) if source_id else None,
            str(mbid) if mbid else None,
        )

    def _album_cover_key(self, album_id: UUID) -> tuple[str, str] | None:
        statement = (
            select(albums.c.title, artists.c.name)
            .select_from(albums)
            .outerjoin(artists, artists.c.id == albums.c.album_artist_id)
            .where(albums.c.id == uuid_to_blob(album_id))
        )
        with self._engine.connect() as conn:
            row = conn.execute(statement).first()
        if row is None:
            return None
        return release_cover_key(row.name, row.title)

    def _primary_cover_keys(self, artwork_id: UUID) -> set[tuple[str, str]]:
        statement = (
            select(albums.c.title, artists.c.name)
            .select_from(album_artwork)
            .join(albums, albums.c.id == album_artwork.c.album_id)
            .outerjoin(artists, artists.c.id == albums.c.album_artist_id)
            .where(album_artwork.c.artwork_id == uuid_to_blob(artwork_id))
            .where(album_artwork.c.is_primary.is_(True))
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return {release_cover_key(row.name, row.title) for row in rows}

    def _trusted_primary_cover_keys(self, artwork_id: UUID) -> set[tuple[str, str]]:
        statement = (
            select(albums.c.title, artists.c.name, albums.c.mbid, artwork_table.c.source_id)
            .select_from(album_artwork)
            .join(albums, albums.c.id == album_artwork.c.album_id)
            .join(artwork_table, artwork_table.c.id == album_artwork.c.artwork_id)
            .outerjoin(artists, artists.c.id == albums.c.album_artist_id)
            .where(album_artwork.c.artwork_id == uuid_to_blob(artwork_id))
            .where(album_artwork.c.is_primary.is_(True))
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        keys: set[tuple[str, str]] = set()
        for row in rows:
            if row.source_id and row.mbid and str(row.source_id) == str(row.mbid):
                keys.add(release_cover_key(row.name, row.title))
        return keys

    def _demote_conflicting_primaries(self, conn: Any, artwork_id: UUID, album_id: UUID) -> None:
        """Clear primary on albums whose cover key differs from the trusted claimer."""
        owner_key = self._album_cover_key(album_id)
        if owner_key is None:
            return
        statement = (
            select(album_artwork.c.album_id, albums.c.title, artists.c.name)
            .select_from(album_artwork)
            .join(albums, albums.c.id == album_artwork.c.album_id)
            .outerjoin(artists, artists.c.id == albums.c.album_artist_id)
            .where(album_artwork.c.artwork_id == uuid_to_blob(artwork_id))
            .where(album_artwork.c.is_primary.is_(True))
            .where(album_artwork.c.album_id != uuid_to_blob(album_id))
        )
        for row in conn.execute(statement).all():
            if release_cover_key(row.name, row.title) == owner_key:
                continue
            conn.execute(
                update(album_artwork)
                .where(album_artwork.c.artwork_id == uuid_to_blob(artwork_id))
                .where(album_artwork.c.album_id == row.album_id)
                .values(is_primary=False)
            )

    def get_primary_for_track(self, track_id: UUID) -> Artwork | None:
        statement = (
            select(artwork_table)
            .join(track_artwork, track_artwork.c.artwork_id == artwork_table.c.id)
            .where(track_artwork.c.track_id == uuid_to_blob(track_id))
            .where(track_artwork.c.is_primary.is_(True))
            .order_by(artwork_table.c.created_at.desc(), artwork_table.c.id)
            .limit(1)
        )
        with self._engine.connect() as conn:
            row = conn.execute(statement).first()
        return _from_row(row) if row is not None else None

    def get_primary_for_album(self, album_id: UUID) -> Artwork | None:
        """Primary cover for this release, never another album's image.

        When several primaries exist, prefer art whose ``source_id`` is this
        album's MusicBrainz release id, then the newest image. Ambiguous
        cross-release primaries without provenance are skipped.
        """
        album_blob = uuid_to_blob(album_id)
        owns_release = and_(
            albums.c.mbid.is_not(None),
            artwork_table.c.source_id.is_not(None),
            artwork_table.c.source_id == albums.c.mbid,
        )
        statement = (
            select(artwork_table)
            .join(album_artwork, album_artwork.c.artwork_id == artwork_table.c.id)
            .join(albums, albums.c.id == album_artwork.c.album_id)
            .where(album_artwork.c.album_id == album_blob)
            .where(album_artwork.c.is_primary.is_(True))
            .order_by(
                case((owns_release, 0), else_=1),
                artwork_table.c.created_at.desc(),
                artwork_table.c.id,
            )
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        for row in rows:
            artwork = _from_row(row)
            if not self.primary_conflicts_with_album(artwork.id, album_id):
                return artwork
        return None

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
        release_slot = case(
            (
                and_(
                    tracks_table.c.track_number.is_not(None),
                    tracks_table.c.track_number > 0,
                ),
                func.printf(
                    "%d:%d:%s",
                    tracks_table.c.disc_number,
                    tracks_table.c.track_number,
                    func.lower(func.coalesce(tracks_table.c.title, "")),
                ),
            ),
            else_=func.hex(tracks_table.c.id),
        )
        track_count = func.count(func.distinct(release_slot)).label("track_count")
        statement = (
            select(
                albums.c.id.label("album_id"),
                albums.c.title,
                artists.c.name.label("artist_name"),
                track_count,
                artwork_table.c.id.label("artwork_id"),
                artwork_table.c.source,
                artwork_table.c.width,
                artwork_table.c.height,
                artwork_table.c.file_path,
            )
            .select_from(tracks_table)
            .join(albums, albums.c.id == tracks_table.c.album_id)
            .outerjoin(artists, artists.c.id == albums.c.album_artist_id)
            .outerjoin(album_artwork, album_artwork.c.album_id == albums.c.id)
            .outerjoin(artwork_table, artwork_table.c.id == album_artwork.c.artwork_id)
            .where(tracks_table.c.library_id == lib)
            .where(
                or_(
                    album_artwork.c.is_primary.is_(True),
                    album_artwork.c.artwork_id.is_(None),
                )
            )
            .group_by(
                albums.c.id,
                albums.c.title,
                artists.c.name,
                artwork_table.c.id,
                artwork_table.c.source,
                artwork_table.c.width,
                artwork_table.c.height,
                artwork_table.c.file_path,
            )
            .order_by(artists.c.name, albums.c.title)
            .offset(offset)
            .limit(limit)
        )
        if query:
            like = f"%{query}%"
            statement = statement.where(or_(albums.c.title.ilike(like), artists.c.name.ilike(like)))
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()

        results: list[ArtworkBrowseRow] = []
        for row in rows:
            album_id = blob_to_uuid(row.album_id)
            artwork_id = blob_to_uuid(row.artwork_id) if row.artwork_id is not None else None
            conflicts = artwork_id is not None and self.primary_conflicts_with_album(
                artwork_id, album_id
            )
            width = None if conflicts or row.width is None else int(row.width)
            height = None if conflicts or row.height is None else int(row.height)
            has_cover = width is not None
            if has_cover and width is not None and height is not None:
                status = "low_res" if width < min_width or height < min_height else "ok"
            else:
                status = "missing"
            if missing_only and status == "ok":
                continue
            results.append(
                ArtworkBrowseRow(
                    album_id=album_id,
                    track_id=None,
                    label=row.title,
                    artist_name=row.artist_name,
                    track_count=int(row.track_count),
                    has_cover=has_cover,
                    cover_source=None if conflicts else row.source,
                    width=width,
                    height=height,
                    status=status,
                    cover_path=None if conflicts else row.file_path,
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

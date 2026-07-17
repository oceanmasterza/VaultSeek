"""DuplicateRepository — persistence for `duplicate_groups` / `duplicate_members`.

Also owns the candidate-discovery SQL (which tracks share a content
hash, Chromaprint hash, or MusicBrainz recording ID) — keeping the
joins here lets :class:`~musicvault.models.services.duplicate_matcher.DuplicateMatcher`
stay pure. Per-track lookups are indexed via the Phase 9 migration
(`file_identity.fingerprint_hash`, `file_identity.content_hash_sha256`,
`duplicate_members.track_id`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, delete, insert, select, update

from musicvault.db.repositories.base import batch_upsert
from musicvault.db.tables import duplicate_groups, duplicate_members, file_identity, tracks
from musicvault.db.uuid_utils import blob_to_uuid, uuid_to_blob
from musicvault.models.entities.duplicate_group import (
    DuplicateGroup,
    DuplicateMember,
    GroupResolution,
    GroupStatus,
    MatchType,
)


class DuplicateRepository:
    """Reads and writes duplicate groups and their members."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save_group(self, group: DuplicateGroup, members: list[DuplicateMember]) -> None:
        """Upsert a group and replace its full member list atomically.

        The group row is upserted (not deleted) so `review_items` rows
        pointing at it via `duplicate_group_id` keep a valid FK target.
        """
        with self._engine.begin() as conn:
            conn.execute(
                delete(duplicate_members).where(
                    duplicate_members.c.group_id == uuid_to_blob(group.id)
                )
            )
            batch_upsert(conn, duplicate_groups, [_group_to_row(group)], conflict_columns=["id"])
            conn.execute(
                insert(duplicate_members),
                [_member_to_row(member) for member in members],
            )

    def get_group(self, group_id: UUID) -> DuplicateGroup | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(duplicate_groups).where(duplicate_groups.c.id == uuid_to_blob(group_id))
            ).first()
        return _group_from_row(row) if row is not None else None

    def get_members(self, group_id: UUID) -> list[DuplicateMember]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(duplicate_members)
                .where(duplicate_members.c.group_id == uuid_to_blob(group_id))
                .order_by(duplicate_members.c.quality_score.desc())
            ).all()
        return [_member_from_row(row) for row in rows]

    def list_open_by_library(self, library_id: UUID) -> list[DuplicateGroup]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(duplicate_groups)
                .where(duplicate_groups.c.library_id == uuid_to_blob(library_id))
                .where(duplicate_groups.c.status == GroupStatus.OPEN.value)
            ).all()
        return [_group_from_row(row) for row in rows]

    def find_open_group_for_track(
        self, track_id: UUID, match_type: MatchType
    ) -> DuplicateGroup | None:
        """The open group of ``match_type`` this track already belongs to, if any."""
        statement = (
            select(duplicate_groups)
            .join(
                duplicate_members,
                duplicate_members.c.group_id == duplicate_groups.c.id,
            )
            .where(duplicate_members.c.track_id == uuid_to_blob(track_id))
            .where(duplicate_groups.c.match_type == match_type.value)
            .where(duplicate_groups.c.status == GroupStatus.OPEN.value)
        )
        with self._engine.connect() as conn:
            row = conn.execute(statement).first()
        return _group_from_row(row) if row is not None else None

    def set_status(
        self,
        group_id: UUID,
        status: GroupStatus,
        *,
        resolution: GroupResolution | None = None,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(duplicate_groups)
                .where(duplicate_groups.c.id == uuid_to_blob(group_id))
                .values(
                    status=status.value,
                    resolution=resolution.value if resolution is not None else None,
                )
            )

    def has_open_group(self, track_id: UUID) -> bool:
        """True if this track belongs to any *open* duplicate group."""
        statement = (
            select(duplicate_members.c.group_id)
            .join(
                duplicate_groups,
                duplicate_groups.c.id == duplicate_members.c.group_id,
            )
            .where(duplicate_members.c.track_id == uuid_to_blob(track_id))
            .where(duplicate_groups.c.status == GroupStatus.OPEN.value)
            .limit(1)
        )
        with self._engine.connect() as conn:
            return conn.execute(statement).first() is not None

    def has_lossless_duplicate(self, track_id: UUID) -> bool:
        """True if this track shares an *open* group with a lossless other member."""
        other = duplicate_members.alias("other")
        statement = (
            select(other.c.track_id)
            .select_from(duplicate_members)
            .join(
                duplicate_groups,
                duplicate_groups.c.id == duplicate_members.c.group_id,
            )
            .join(other, other.c.group_id == duplicate_members.c.group_id)
            .join(tracks, tracks.c.id == other.c.track_id)
            .where(duplicate_members.c.track_id == uuid_to_blob(track_id))
            .where(other.c.track_id != uuid_to_blob(track_id))
            .where(duplicate_groups.c.status == GroupStatus.OPEN.value)
            .where(tracks.c.is_lossless.is_(True))
            .limit(1)
        )
        with self._engine.connect() as conn:
            return conn.execute(statement).first() is not None

    def find_matching_track_ids(
        self,
        library_id: UUID,
        track_id: UUID,
        *,
        content_hash: str | None = None,
        fingerprint_hash: str | None = None,
        mb_recording_id: str | None = None,
    ) -> dict[MatchType, list[UUID]]:
        """Other tracks in the library sharing any exact matching key.

        Returns per-tier candidate lists (excluding ``track_id`` itself);
        tiers with no key provided or no matches are omitted.
        """
        results: dict[MatchType, list[UUID]] = {}
        with self._engine.connect() as conn:
            if content_hash:
                rows = conn.execute(
                    select(file_identity.c.track_id)
                    .join(tracks, tracks.c.id == file_identity.c.track_id)
                    .where(tracks.c.library_id == uuid_to_blob(library_id))
                    .where(file_identity.c.content_hash_sha256 == content_hash)
                    .where(file_identity.c.track_id != uuid_to_blob(track_id))
                ).all()
                if rows:
                    results[MatchType.HASH] = [blob_to_uuid(row.track_id) for row in rows]
            if fingerprint_hash:
                rows = conn.execute(
                    select(file_identity.c.track_id)
                    .join(tracks, tracks.c.id == file_identity.c.track_id)
                    .where(tracks.c.library_id == uuid_to_blob(library_id))
                    .where(file_identity.c.fingerprint_hash == fingerprint_hash)
                    .where(file_identity.c.track_id != uuid_to_blob(track_id))
                ).all()
                if rows:
                    results[MatchType.FINGERPRINT] = [blob_to_uuid(row.track_id) for row in rows]
            if mb_recording_id:
                rows = conn.execute(
                    select(tracks.c.id)
                    .where(tracks.c.library_id == uuid_to_blob(library_id))
                    .where(tracks.c.mb_recording_id == mb_recording_id)
                    .where(tracks.c.id != uuid_to_blob(track_id))
                ).all()
                if rows:
                    results[MatchType.MBID] = [blob_to_uuid(row.id) for row in rows]
        return results


def _group_to_row(group: DuplicateGroup) -> dict[str, object]:
    return {
        "id": uuid_to_blob(group.id),
        "library_id": uuid_to_blob(group.library_id),
        "match_type": group.match_type.value,
        "match_confidence": group.match_confidence,
        "best_track_id": uuid_to_blob(group.best_track_id) if group.best_track_id else None,
        "track_count": group.track_count,
        "detected_at": group.detected_at.isoformat(),
        "status": group.status.value,
        "resolution": group.resolution.value if group.resolution else None,
    }


def _group_from_row(row: Row[Any]) -> DuplicateGroup:
    return DuplicateGroup(
        id=blob_to_uuid(row.id),
        library_id=blob_to_uuid(row.library_id),
        match_type=MatchType(row.match_type),
        match_confidence=row.match_confidence,
        best_track_id=blob_to_uuid(row.best_track_id) if row.best_track_id else None,
        track_count=row.track_count,
        detected_at=datetime.fromisoformat(row.detected_at),
        status=GroupStatus(row.status),
        resolution=GroupResolution(row.resolution) if row.resolution else None,
    )


def _member_to_row(member: DuplicateMember) -> dict[str, object]:
    return {
        "group_id": uuid_to_blob(member.group_id),
        "track_id": uuid_to_blob(member.track_id),
        "quality_score": member.quality_score,
        "is_best": member.is_best,
        "zone": member.zone,
    }


def _member_from_row(row: Row[Any]) -> DuplicateMember:
    return DuplicateMember(
        group_id=blob_to_uuid(row.group_id),
        track_id=blob_to_uuid(row.track_id),
        quality_score=row.quality_score,
        is_best=bool(row.is_best),
        zone=row.zone,
    )

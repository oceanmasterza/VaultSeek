"""Reset library processing state without deleting the library itself.

Keeps zone paths, watch settings, rules, and media-server config.
Optionally clears catalog track rows so the next Incoming scan rebuilds
from files still on disk in Incoming (files already moved to Staging /
Library stay on disk but disappear from the dashboard until re-imported).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Engine, delete, select, update

from vaultseek.db.tables import (
    change_history,
    duplicate_groups,
    duplicate_members,
    file_identity,
    jobs,
    metadata_confidence,
    review_items,
    track_artwork,
    tracks,
    trusted_folders,
)
from vaultseek.db.uuid_utils import uuid_to_blob


@dataclass(frozen=True, slots=True)
class LibraryResetResult:
    jobs_deleted: int
    reviews_deleted: int
    tracks_deleted: int
    duplicate_groups_deleted: int


def reset_library_processing(
    engine: Engine,
    library_id: UUID,
    *,
    clear_catalog: bool = False,
) -> LibraryResetResult:
    """Clear queues (and optionally catalog rows) for ``library_id``.

    Always deletes jobs and review items for the library. When
    ``clear_catalog`` is True, also removes track-linked rows and tracks
    for that library (files on disk are not moved or deleted).
    """
    lib = uuid_to_blob(library_id)
    with engine.begin() as conn:
        # Break self-FK on jobs.parent_job_id so deletes succeed.
        conn.execute(
            update(jobs).where(jobs.c.library_id == lib).values(parent_job_id=None)
        )
        jobs_deleted = conn.execute(delete(jobs).where(jobs.c.library_id == lib)).rowcount or 0
        reviews_deleted = (
            conn.execute(delete(review_items).where(review_items.c.library_id == lib)).rowcount
            or 0
        )
        conn.execute(delete(trusted_folders).where(trusted_folders.c.library_id == lib))

        tracks_deleted = 0
        groups_deleted = 0
        if clear_catalog:
            track_ids = (
                conn.execute(select(tracks.c.id).where(tracks.c.library_id == lib))
                .scalars()
                .all()
            )
            group_ids = (
                conn.execute(
                    select(duplicate_groups.c.id).where(duplicate_groups.c.library_id == lib)
                )
                .scalars()
                .all()
            )

            if group_ids:
                conn.execute(
                    delete(duplicate_members).where(duplicate_members.c.group_id.in_(group_ids))
                )
                # Clear best_track_id before deleting tracks.
                conn.execute(
                    update(duplicate_groups)
                    .where(duplicate_groups.c.id.in_(group_ids))
                    .values(best_track_id=None)
                )

            if track_ids:
                conn.execute(
                    delete(change_history).where(change_history.c.track_id.in_(track_ids))
                )
                conn.execute(
                    delete(track_artwork).where(track_artwork.c.track_id.in_(track_ids))
                )
                conn.execute(
                    delete(metadata_confidence).where(
                        metadata_confidence.c.track_id.in_(track_ids)
                    )
                )
                conn.execute(
                    delete(file_identity).where(file_identity.c.track_id.in_(track_ids))
                )
                conn.execute(
                    delete(duplicate_members).where(
                        duplicate_members.c.track_id.in_(track_ids)
                    )
                )

            if group_ids:
                groups_deleted = (
                    conn.execute(
                        delete(duplicate_groups).where(duplicate_groups.c.id.in_(group_ids))
                    ).rowcount
                    or 0
                )

            if track_ids:
                tracks_deleted = (
                    conn.execute(delete(tracks).where(tracks.c.id.in_(track_ids))).rowcount
                    or 0
                )

    return LibraryResetResult(
        jobs_deleted=int(jobs_deleted),
        reviews_deleted=int(reviews_deleted),
        tracks_deleted=int(tracks_deleted),
        duplicate_groups_deleted=int(groups_deleted),
    )

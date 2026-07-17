"""OrganizerWorker — runs `organize_file` jobs (physical zone moves).

I/O-bound (Tier 2 — filesystem + DB). Validates the zone transition
against :class:`~musicvault.models.services.organize_engine.OrganizeEngine`'s
state machine, moves the file into the target zone's organized folder
structure, updates the track row, and writes an `operations` +
`change_history` audit pair for the Phase 12 rollback engine.

Safe-move policy (no algorithm is documented — this is the
implementation's fill-in): destinations are never overwritten. On a
name collision the new file gets a `` (1)`` / `` (2)`` suffix.
:func:`shutil.move` handles cross-volume moves via copy2 + unlink;
nothing is ever hard-deleted.

**Auto-approve** (docs/architecture/10-revision-v2.md watch-folder
flow): after completing a move *into staging*, if the track's
`overall_confidence` meets the library's `auto_approve_threshold`, it
has no pending review items, and it belongs to no open duplicate group,
a follow-up `organize_file` job to `library` is enqueued — completing
the zero-click incoming → staging → library flow. `sync_media_server`
enqueue stays Phase 15.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from musicvault.db.repositories.album_repo import AlbumRepository
from musicvault.db.repositories.artist_repo import ArtistRepository
from musicvault.db.repositories.duplicate_repo import DuplicateRepository
from musicvault.db.repositories.library_repo import LibraryRepository
from musicvault.db.repositories.operation_repo import OperationRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.job import Job, JobType
from musicvault.models.entities.library import Library
from musicvault.models.entities.operation import (
    ChangeRecord,
    ChangeType,
    Operation,
    OperationStatus,
    OperationType,
)
from musicvault.models.entities.track import LibraryZone, Track
from musicvault.models.services.organize_engine import OrganizeEngine
from musicvault.services.job_queue_service import JobQueueService


class OrganizerWorker:
    def __init__(
        self,
        track_repo: TrackRepository,
        library_repo: LibraryRepository,
        artist_repo: ArtistRepository,
        album_repo: AlbumRepository,
        review_repo: ReviewRepository,
        duplicate_repo: DuplicateRepository,
        operation_repo: OperationRepository,
        organize_engine: OrganizeEngine,
        job_queue: JobQueueService,
    ) -> None:
        self._tracks = track_repo
        self._libraries = library_repo
        self._artists = artist_repo
        self._albums = album_repo
        self._reviews = review_repo
        self._duplicates = duplicate_repo
        self._operations = operation_repo
        self._engine = organize_engine
        self._job_queue = job_queue

    def execute(self, job: Job) -> None:
        track_id = UUID(job.payload["track_id"])
        target = LibraryZone(job.payload["target_zone"])
        track = self._tracks.get_by_id(track_id)
        if track is None:
            self._job_queue.mark_failed(job.id, f"Track {track_id} not found")
            return
        if track.zone is target:
            # Idempotent redelivery (e.g. retried job) — nothing to do.
            self._job_queue.mark_completed(job.id)
            return
        if not self._engine.can_transition(track.zone, target):
            self._job_queue.mark_failed(
                job.id,
                f"Illegal zone transition {track.zone.value} -> {target.value} "
                f"for track {track_id}",
            )
            return
        library = self._libraries.get(job.library_id)
        if library is None:
            self._job_queue.mark_failed(job.id, f"Library {job.library_id} not found")
            return
        source = Path(track.file_path)
        if not source.is_file():
            self._job_queue.mark_failed(job.id, f"Source file missing: {track.file_path}")
            return

        now = datetime.now(UTC)
        destination = self._compute_destination(library, target, track)
        final = _safe_move(source, destination)

        updated = replace(
            track,
            zone=target,
            file_path=str(final),
            file_name=final.name,
            updated_at=now,
        )
        self._tracks.upsert(updated)
        self._record_move(track, updated, now)

        if target is LibraryZone.STAGING and self._should_auto_approve(updated, library):
            self._job_queue.enqueue(
                JobType.ORGANIZE_FILE,
                job.library_id,
                {"track_id": str(track_id), "target_zone": LibraryZone.LIBRARY.value},
                parent_job_id=job.id,
                now=now,
            )
        self._job_queue.mark_completed(job.id)

    def _compute_destination(self, library: Library, target: LibraryZone, track: Track) -> Path:
        artist_name: str | None = None
        if track.artist_id is not None:
            artist = self._artists.get(track.artist_id)
            if artist is not None:
                artist_name = artist.name
        album_title: str | None = None
        album_year: int | None = None
        if track.album_id is not None:
            album = self._albums.get(track.album_id)
            if album is not None:
                album_title = album.title
                album_year = album.year
        return Path(
            self._engine.destination_path(
                library,
                target,
                track,
                artist_name=artist_name,
                album_title=album_title,
                album_year=album_year,
            )
        )

    def _record_move(self, before: Track, after: Track, now: datetime) -> None:
        operation_id = generate_uuid7()
        self._operations.record(
            Operation(
                id=operation_id,
                operation_type=OperationType.FILE_MOVE,
                status=OperationStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                affected_count=1,
                description=(
                    f"Moved '{before.file_name}' from {before.zone.value} to {after.zone.value}"
                ),
            ),
            [
                ChangeRecord(
                    id=generate_uuid7(),
                    operation_id=operation_id,
                    change_type=ChangeType.MOVE,
                    timestamp=now,
                    track_id=after.id,
                    old_file_path=before.file_path,
                    new_file_path=after.file_path,
                    old_zone=before.zone.value,
                    new_zone=after.zone.value,
                )
            ],
        )

    def _should_auto_approve(self, track: Track, library: Library) -> bool:
        if track.needs_review:
            return False
        if track.overall_confidence is None:
            return False
        if track.overall_confidence < library.auto_approve_threshold:
            return False
        if self._reviews.list_pending_for_track(track.id):
            return False
        return not self._duplicates.has_open_group(track.id)


def _safe_move(source: Path, destination: Path) -> Path:
    """Move ``source`` to ``destination``, suffixing on collision.

    Never overwrites an existing file; parent directories are created
    as needed.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    final = destination
    counter = 1
    while final.exists():
        final = destination.with_name(f"{destination.stem} ({counter}){destination.suffix}")
        counter += 1
    shutil.move(str(source), str(final))
    return final

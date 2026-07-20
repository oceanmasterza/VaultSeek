"""OrganizerWorker — runs `organize_file` jobs (physical zone moves).

I/O-bound (Tier 2 — filesystem + DB). Validates the zone transition
against :class:`~vaultseek.models.services.organize_engine.OrganizeEngine`'s
state machine, moves the file into the target zone's organized folder
structure, updates the track row, and writes an `operations` +
`change_history` + `rollback_snapshots` audit triple so
:class:`~vaultseek.services.operation_orchestrator.OperationOrchestrator`
can reverse the move.

**In-place processing:** originals stay in Incoming through identify/rules.
The usual success path is a single move **incoming → library**. Staging →
library auto-approve remains for tracks already in staging (legacy /
manual). Moves into ``library`` enqueue ``sync_media_server``.

Safe-move policy: destinations are never overwritten. On a name collision
the new file gets a `` (1)`` / `` (2)`` suffix. :func:`shutil.move` handles
cross-volume moves via copy2 + unlink. After an Incoming → elsewhere move,
leftover non-audio junk (``.nfo``, covers, empty album folders, …) is
removed once no audio remains in that folder tree.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from loguru import logger
from sqlalchemy.exc import IntegrityError

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.repositories.metadata_confidence_repo import MetadataConfidenceRepository
from vaultseek.db.repositories.operation_repo import (
    OperationRepository,
    build_move_snapshot_payload,
    encode_snapshot_data,
)
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.job import Job, JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.operation import (
    ChangeRecord,
    ChangeType,
    Operation,
    OperationStatus,
    OperationType,
    RollbackSnapshot,
)
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.services.organize_engine import OrganizeEngine
from vaultseek.services.incoming_cleanup import cleanup_incoming_after_move
from vaultseek.services.job_queue_service import JobQueueService


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
        *,
        metadata_confidence_repo: MetadataConfidenceRepository | None = None,
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
        self._confidence = metadata_confidence_repo

    def execute(self, job: Job) -> None:
        track_id = UUID(job.payload["track_id"])
        target = LibraryZone(job.payload["target_zone"])
        track = self._tracks.get_by_id(track_id)
        if track is None:
            self._job_queue.mark_failed(job.id, f"Track {track_id} not found")
            return
        if track.zone is target:
            # Idempotent redelivery (e.g. retried job) — nothing to do.
            summary = f"Already in {target.value}: {track.file_name}"
            self._job_queue.mark_completed(
                job.id,
                summary=summary,
                result={"outcome": "noop", "summary": summary, "target_zone": target.value},
            )
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
        try:
            self._tracks.upsert(updated)
        except IntegrityError:
            collided = Path(updated.file_path)
            final = _unique_sibling(collided)
            if collided.exists() and collided != final:
                collided.rename(final)
            updated = replace(updated, file_path=str(final), file_name=final.name)
            self._tracks.upsert(updated)
        self._record_move(track, updated, now)

        cleaned: list[str] = []
        if track.zone is LibraryZone.INCOMING:
            cleaned = cleanup_incoming_after_move(source, Path(library.incoming_path))
            if cleaned:
                logger.info(
                    "Cleaned {} leftover Incoming path(s) after moving {}",
                    len(cleaned),
                    track.file_name,
                )

        # Legacy/manual: tracks already in staging may still auto-promote.
        if target is LibraryZone.STAGING and self._should_auto_approve(updated, library):
            self._job_queue.enqueue(
                JobType.ORGANIZE_FILE,
                job.library_id,
                {"track_id": str(track_id), "target_zone": LibraryZone.LIBRARY.value},
                parent_job_id=job.id,
                now=now,
            )
        if target is LibraryZone.LIBRARY:
            self._enqueue_media_sync_if_idle(job.library_id, parent_job_id=job.id, now=now)
        summary = f"Moved to {target.value}: {final.name}"
        if cleaned:
            summary += f" · cleaned {len(cleaned)} leftover Incoming item(s)"
        self._job_queue.mark_completed(
            job.id,
            summary=summary,
            result={
                "outcome": "moved",
                "summary": summary,
                "target_zone": target.value,
                "file_path": str(final),
                "incoming_cleaned": len(cleaned),
            },
        )

    def _enqueue_media_sync_if_idle(
        self,
        library_id: UUID,
        *,
        parent_job_id: UUID,
        now: datetime,
    ) -> None:
        """Enqueue at most one in-flight ``sync_media_server`` per library.

        Same coalesce pattern as watch-folder scans — bulk library imports
        must not stampede media servers.
        """
        stats = self._job_queue.get_stats(library_id, now=now)
        if stats.by_type.get(JobType.SYNC_MEDIA_SERVER.value, 0) > 0:
            return
        self._job_queue.enqueue(
            JobType.SYNC_MEDIA_SERVER,
            library_id,
            {},
            parent_job_id=parent_job_id,
            now=now,
        )

    def _compute_destination(self, library: Library, target: LibraryZone, track: Track) -> Path:
        artist_name: str | None = None
        if track.artist_id is not None:
            artist = self._artists.get(track.artist_id)
            if artist is not None:
                artist_name = artist.name
        if artist_name is None and self._confidence is not None:
            for field in self._confidence.list_for_track(track.id):
                if field.field == "artist" and field.value:
                    artist_name = str(field.value)
                    break
        album_title: str | None = None
        album_year: int | None = None
        if track.album_id is not None:
            album = self._albums.get(track.album_id)
            if album is not None:
                album_title = album.title
                album_year = album.year
        if album_title is None and self._confidence is not None:
            for field in self._confidence.list_for_track(track.id):
                if field.field == "album" and field.value:
                    album_title = str(field.value)
                    break
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
        """Write operation + change_history + rollback snapshot (Phase 12)."""
        operation_id = generate_uuid7()
        snapshot_id = generate_uuid7()
        change = ChangeRecord(
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
        operation = Operation(
            id=operation_id,
            operation_type=OperationType.FILE_MOVE,
            status=OperationStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            affected_count=1,
            description=(
                f"Moved '{before.file_name}' from {before.zone.value} to {after.zone.value}"
            ),
            snapshot_id=snapshot_id,
        )
        snapshot = RollbackSnapshot(
            id=snapshot_id,
            operation_id=operation_id,
            snapshot_data=encode_snapshot_data(build_move_snapshot_payload([change])),
            created_at=now,
        )
        self._operations.record_with_snapshot(operation, [change], snapshot)

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

    Retries briefly on Windows ``WinError 32`` (file in use) — common when
    Explorer preview, antivirus, or a just-finished fingerprint still holds
    the handle. Never overwrites an existing file.
    """
    import time

    destination.parent.mkdir(parents=True, exist_ok=True)
    final = destination
    counter = 1
    while final.exists():
        final = destination.with_name(f"{destination.stem} ({counter}){destination.suffix}")
        counter += 1

    last_exc: OSError | None = None
    for attempt in range(1, 8):
        try:
            shutil.move(str(source), str(final))
            return final
        except OSError as exc:
            last_exc = exc
            # WinError 32 / errno 13 — file locked; back off and retry.
            if getattr(exc, "winerror", None) == 32 or exc.errno in {13, 11}:
                time.sleep(0.15 * attempt)
                continue
            raise
    assert last_exc is not None
    raise last_exc


def _unique_sibling(path: Path) -> Path:
    """Return ``path`` or the next free ``stem (n).suffix`` sibling."""
    if not path.exists():
        # Path may be reserved in DB but not on disk — still avoid the DB collision.
        candidate = path
        counter = 1
        # Caller already hit UNIQUE; force at least one suffix.
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        while candidate.exists():
            counter += 1
            candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        return candidate
    counter = 1
    candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
    while candidate.exists():
        counter += 1
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
    return candidate

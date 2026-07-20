"""OperationOrchestrator — safety gate for mutating library operations.

See docs/architecture/04-service-layer.md ("OperationOrchestrator"):
preview → execute → rollback, with a rollback snapshot attached to every
mutation. Phase 12 MVP:

- **preview** / **execute** for ``file_move`` — compute the destination
  (and optionally enqueue an ``organize_file`` job). Physical moves still
  run in :class:`~vaultseek.workers.io.organizer_worker.OrganizerWorker`,
  which now writes the snapshot + change_history pair.
- **rollback** — reverse a completed ``file_move`` using change_history
  (and the snapshot when present). Zone-machine validation is skipped:
  undo must be allowed even when the reverse transition is not a normal
  forward path (e.g. library → staging).

Metadata tag rewrites and artwork embedding stay deferred.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from vaultseek.core.exceptions import OperationError, RollbackError
from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.repositories.operation_repo import (
    OperationRepository,
    decode_snapshot_data,
)
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.operation import (
    ChangeRecord,
    ChangeType,
    Operation,
    OperationStatus,
    OperationType,
)
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.services.organize_engine import OrganizeEngine
from vaultseek.services.dto.operation_dto import OperationRequest, OperationResult
from vaultseek.services.job_queue_service import JobQueueService


class OperationOrchestrator:
    def __init__(
        self,
        operation_repo: OperationRepository,
        track_repo: TrackRepository,
        library_repo: LibraryRepository,
        artist_repo: ArtistRepository,
        album_repo: AlbumRepository,
        organize_engine: OrganizeEngine,
        *,
        job_queue: JobQueueService | None = None,
    ) -> None:
        self._operations = operation_repo
        self._tracks = track_repo
        self._libraries = library_repo
        self._artists = artist_repo
        self._albums = album_repo
        self._organize = organize_engine
        self._job_queue = job_queue

    def preview(self, request: OperationRequest) -> OperationResult:
        """Describe what a mutation would do without touching the filesystem."""
        if request.operation_type is not OperationType.FILE_MOVE:
            raise OperationError(
                f"Unsupported operation type for preview: {request.operation_type.value}"
            )
        track, library, destination = self._resolve_move(request)
        return OperationResult(
            success=True,
            message=(
                f"Would move '{track.file_name}' from {track.zone.value} "
                f"to {request.target_zone.value}"
            ),
            affected_count=1,
            details={
                "track_id": str(track.id),
                "old_file_path": track.file_path,
                "new_file_path": str(destination),
                "old_zone": track.zone.value,
                "new_zone": request.target_zone.value,
                "library_id": str(library.id),
                "dry_run": True,
            },
        )

    def execute(self, request: OperationRequest) -> OperationResult:
        """Enqueue a real ``organize_file`` job, or return a preview when dry-run.

        Snapshots are created by the OrganizerWorker when the job runs —
        not here — so the audit trail is tied to the actual filesystem
        result (including collision suffixes).
        """
        if request.dry_run:
            return self.preview(request)
        if request.operation_type is not OperationType.FILE_MOVE:
            raise OperationError(
                f"Unsupported operation type for execute: {request.operation_type.value}"
            )
        if self._job_queue is None:
            raise OperationError("Job queue is not wired; cannot execute file moves")
        track, _library, destination = self._resolve_move(request)
        now = datetime.now(UTC)
        job_id = self._job_queue.enqueue(
            JobType.ORGANIZE_FILE,
            track.library_id,
            {
                "track_id": str(track.id),
                "target_zone": request.target_zone.value,
            },
            now=now,
        )
        return OperationResult(
            success=True,
            message=(f"Enqueued move of '{track.file_name}' to {request.target_zone.value}"),
            affected_count=1,
            details={
                "job_id": str(job_id),
                "track_id": str(track.id),
                "planned_destination": str(destination),
                "old_zone": track.zone.value,
                "new_zone": request.target_zone.value,
            },
        )

    def rollback(self, operation_id: UUID, *, now: datetime | None = None) -> OperationResult:
        """Reverse a completed ``file_move`` operation."""
        restored_at = now or datetime.now(UTC)
        operation = self._operations.get(operation_id)
        if operation is None:
            raise RollbackError(f"Operation {operation_id} not found")
        if operation.status is OperationStatus.ROLLED_BACK:
            raise RollbackError(f"Operation {operation_id} is already rolled back")
        if operation.status is not OperationStatus.COMPLETED:
            raise RollbackError(
                f"Operation {operation_id} is {operation.status.value}, "
                "only completed operations can be rolled back"
            )
        if operation.operation_type is not OperationType.FILE_MOVE:
            raise RollbackError(
                f"Cannot roll back operation type {operation.operation_type.value} yet"
            )

        changes = self._operations.list_changes(operation_id)
        if not changes:
            # Fall back to snapshot payload (Phase 12 ops always have both).
            changes = self._changes_from_snapshot(operation)

        reversed_count = 0
        details: list[dict[str, str]] = []
        for change in reversed(changes):
            if change.change_type is not ChangeType.MOVE:
                continue
            detail = self._reverse_move(change, restored_at)
            details.append(detail)
            reversed_count += 1

        if reversed_count == 0:
            raise RollbackError(f"Operation {operation_id} has no reversible move changes")

        self._operations.set_status(
            operation_id, OperationStatus.ROLLED_BACK, completed_at=restored_at
        )
        snapshot = self._operations.get_snapshot_for_operation(operation_id)
        if snapshot is not None:
            self._operations.mark_snapshot_restored(snapshot.id, restored_at)

        updated = self._operations.get(operation_id)
        return OperationResult(
            success=True,
            operation_id=operation_id,
            message=f"Rolled back {reversed_count} file move(s)",
            affected_count=reversed_count,
            details={"reversed": details},
            operation=updated,
        )

    def list_recent(self, *, limit: int = 50) -> list[Operation]:
        """Newest mutating operations first (zone-aware history browse)."""
        return self._operations.list_recent(limit=limit)

    def history_for_track(self, track_id: UUID) -> list[ChangeRecord]:
        """Zone-aware change history for one track, oldest first."""
        return self._operations.list_changes_for_track(track_id)

    def _resolve_move(self, request: OperationRequest) -> tuple[Track, Library, Path]:
        track = self._tracks.get_by_id(request.track_id)
        if track is None:
            raise OperationError(f"Track {request.track_id} not found")
        if track.zone is request.target_zone:
            raise OperationError(
                f"Track {request.track_id} is already in {request.target_zone.value}"
            )
        if not self._organize.can_transition(track.zone, request.target_zone):
            raise OperationError(
                f"Illegal zone transition {track.zone.value} -> {request.target_zone.value}"
            )
        library = self._libraries.get(track.library_id)
        if library is None:
            raise OperationError(f"Library {track.library_id} not found")
        destination = self._destination_for(library, request.target_zone, track)
        return track, library, destination

    def _destination_for(self, library: Library, target: LibraryZone, track: Track) -> Path:
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
            self._organize.destination_path(
                library,
                target,
                track,
                artist_name=artist_name,
                album_title=album_title,
                album_year=album_year,
            )
        )

    def _changes_from_snapshot(self, operation: Operation) -> list[ChangeRecord]:
        snapshot = self._operations.get_snapshot_for_operation(operation.id)
        if snapshot is None:
            return []
        payload = decode_snapshot_data(snapshot.snapshot_data)
        changes: list[ChangeRecord] = []
        for raw in payload.get("changes") or []:
            track_raw = raw.get("track_id")
            changes.append(
                ChangeRecord(
                    id=operation.id,  # placeholder — not persisted
                    operation_id=operation.id,
                    change_type=ChangeType(raw["change_type"]),
                    timestamp=operation.started_at,
                    track_id=UUID(track_raw) if track_raw else None,
                    old_file_path=raw.get("old_file_path"),
                    new_file_path=raw.get("new_file_path"),
                    old_zone=raw.get("old_zone"),
                    new_zone=raw.get("new_zone"),
                )
            )
        return changes

    def _reverse_move(self, change: ChangeRecord, now: datetime) -> dict[str, str]:
        if change.track_id is None:
            raise RollbackError("Move change is missing track_id")
        if not change.old_file_path or not change.new_file_path or not change.old_zone:
            raise RollbackError("Move change is missing path/zone fields")

        track = self._tracks.get_by_id(change.track_id)
        if track is None:
            raise RollbackError(f"Track {change.track_id} not found for rollback")

        source = Path(change.new_file_path)
        # Prefer the track's current path if the file was moved again after
        # this operation — still try the recorded new path first.
        if not source.is_file():
            source = Path(track.file_path)
        if not source.is_file():
            raise RollbackError(f"Cannot roll back move: file missing at {change.new_file_path}")

        destination = Path(change.old_file_path)
        final = _safe_move(source, destination)
        restored_zone = LibraryZone(change.old_zone)
        updated = replace(
            track,
            zone=restored_zone,
            file_path=str(final),
            file_name=final.name,
            updated_at=now,
        )
        self._tracks.upsert(updated)
        return {
            "track_id": str(track.id),
            "from_path": str(source),
            "to_path": str(final),
            "from_zone": change.new_zone or track.zone.value,
            "to_zone": restored_zone.value,
        }


def _safe_move(source: Path, destination: Path) -> Path:
    """Move ``source`` to ``destination``, suffixing on collision (never overwrite)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    final = destination
    counter = 1
    while final.exists():
        final = destination.with_name(f"{destination.stem} ({counter}){destination.suffix}")
        counter += 1
    shutil.move(str(source), str(final))
    return final

"""HashWorker — SHA-256 content hashing for the `hash_file` job.

CPU-bound (Tier 1 — see docs/architecture/08-performance.md, "Three-Tier
Worker Model"), so :func:`compute_hash` — the function actually
submitted to a `ProcessPoolExecutor` — must not hold or touch a
database connection: child processes don't get one (docs/architecture/
08-performance.md, "Memory Budget": "Child processes in ProcessPool do
not hold SQLite connections — results returned as dicts, parent enqueues
WriteDTO"). It takes and returns only plain, picklable data.

Everything that needs the database — deciding whether the content
actually changed, persisting `file_identity`, chaining to
`fingerprint_file` — happens in :meth:`HashWorker.handle_result`, which
runs back in the main process once the pool's `Future` completes (see
:class:`vaultseek.services.job_dispatcher.JobDispatcher`).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.writer import DatabaseWriter, WriteDTO
from vaultseek.models.entities.job import Job, JobType
from vaultseek.models.value_objects.file_identity import FileIdentity
from vaultseek.services.folder_trust import FolderTrustService
from vaultseek.services.job_queue_service import JobQueueService

_CHUNK_SIZE = 1024 * 1024  # 1 MiB — bounds memory use regardless of file size.


def compute_hash(payload: dict[str, Any]) -> dict[str, Any]:
    """The picklable unit of work for a ProcessPoolExecutor worker.

    ``payload`` is a `hash_file` job's `Job.payload` — ``{"track_id":
    str, "file_path": str}`` (see :class:`~vaultseek.workers.io.scanner_worker.ScannerWorker`,
    which enqueues these jobs). Never raises — I/O failures are reported
    back as a plain ``{"track_id", "error"}`` dict, since exceptions
    raised inside a worker process are awkward to rely on surviving the
    trip back across the process boundary intact.
    """
    track_id = payload["track_id"]
    file_path = Path(payload["file_path"])
    try:
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
                digest.update(chunk)
        stat = file_path.stat()
    except OSError as exc:
        return {"track_id": track_id, "error": str(exc)}

    return {
        "track_id": track_id,
        "content_hash_sha256": digest.hexdigest(),
        "file_size": stat.st_size,
        "file_modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
    }


class HashWorker:
    """Owns the database-facing half of the `hash_file` pipeline stage —
    see the module docstring for why this is split from :func:`compute_hash`.
    """

    def __init__(
        self,
        file_identity_repo: FileIdentityRepository,
        database_writer: DatabaseWriter,
        job_queue: JobQueueService,
        *,
        track_repo: TrackRepository | None = None,
        folder_trust: FolderTrustService | None = None,
        fingerprint_mode: str = "all",
    ) -> None:
        self._file_identity_repo = file_identity_repo
        self._writer = database_writer
        self._job_queue = job_queue
        self._tracks = track_repo
        self._folder_trust = folder_trust
        self._fingerprint_mode = fingerprint_mode

    def handle_result(self, job: Job, result: dict[str, Any]) -> None:
        """Process one :func:`compute_hash` result: persist
        `file_identity`, enqueue `fingerprint_file` only if the content
        hash actually changed (a cheap stat mismatch upstream in
        `ScannerWorker` can still hash identically — this is the
        authoritative check), and mark the `hash_file` job done.
        """
        error = result.get("error")
        if error is not None:
            if _is_missing_file_error(str(error)) and self._recover_moved_file(job):
                return
            self._job_queue.mark_failed(
                job.id,
                str(error),
                terminal=_is_missing_file_error(str(error)),
            )
            return

        track_id = UUID(result["track_id"])
        new_hash = result["content_hash_sha256"]
        file_size = result["file_size"]
        file_modified = datetime.fromisoformat(result["file_modified"])
        previous = self._file_identity_repo.get(track_id)
        content_changed = previous is None or previous.content_hash_sha256 != new_hash
        now = datetime.now(UTC)

        # Content changed → wipe stale fingerprint/AcoustID fields.
        # Content unchanged → preserve them (a size/mtime blip can still
        # hash identically; overwriting here would force needless
        # Chromaprint work on the next chain hop).
        if previous is not None and not content_changed:
            identity = replace(
                previous,
                content_hash_sha256=new_hash,
                file_size=file_size,
                file_modified=file_modified,
                hash_computed_at=now,
            )
        else:
            identity = FileIdentity(
                track_id=track_id,
                content_hash_sha256=new_hash,
                file_size=file_size,
                file_modified=file_modified,
                hash_computed_at=now,
            )
        self._writer.submit(
            WriteDTO(
                table="file_identity",
                operation="upsert",
                rows=[FileIdentityRepository.to_row(identity)],
                job_id=job.id,
                conflict_columns=("track_id",),
            )
        )

        if content_changed or bool(job.payload.get("force")):
            file_path = job.payload["file_path"]
            track = None
            if self._tracks is not None:
                track = self._tracks.get_by_id(track_id)
                if track is not None:
                    file_path = track.file_path
            skip_fingerprint = (
                self._fingerprint_mode == "sample"
                and self._folder_trust is not None
                and track is not None
                and self._folder_trust.is_trusted_for_track(track)
                and not bool(job.payload.get("force"))
            )
            if skip_fingerprint:
                self._job_queue.enqueue(
                    JobType.IDENTIFY_METADATA,
                    job.library_id,
                    {"track_id": str(track_id)},
                    parent_job_id=job.id,
                )
            else:
                fp_payload: dict[str, object] = {
                    "track_id": str(track_id),
                    "file_path": file_path,
                }
                if job.payload.get("force"):
                    fp_payload["force"] = True
                self._job_queue.enqueue(
                    JobType.FINGERPRINT_FILE,
                    job.library_id,
                    fp_payload,
                    parent_job_id=job.id,
                )
        self._job_queue.mark_completed(job.id)

    def _recover_moved_file(self, job: Job) -> bool:
        """If the track was organized away from the payload path, re-hash there once."""
        if self._tracks is None:
            return False
        track_id = UUID(job.payload["track_id"])
        track = self._tracks.get_by_id(track_id)
        if track is None:
            return False
        current = Path(track.file_path)
        payload_path = str(job.payload.get("file_path") or "")
        if str(current) == payload_path or not current.is_file():
            return False
        if self._job_queue.has_active_for_track(JobType.HASH_FILE, job.library_id, track_id):
            self._job_queue.mark_completed(job.id)
            return True
        self._job_queue.enqueue(
            JobType.HASH_FILE,
            job.library_id,
            {"track_id": str(track_id), "file_path": str(current)},
            parent_job_id=job.id,
        )
        self._job_queue.mark_completed(job.id)
        return True


def _is_missing_file_error(message: str) -> bool:
    lower = message.lower()
    return (
        "no such file" in lower
        or "cannot find the file" in lower
        or "the system cannot find the file" in lower
        or "errno 2" in lower
    )

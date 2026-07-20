"""FingerprintWorker — Chromaprint generation for the `fingerprint_file` job.

CPU-bound (Tier 1 — see docs/architecture/08-performance.md, "Three-Tier
Worker Model"). :func:`compute_fingerprint` is the picklable ProcessPool
unit of work; :meth:`FingerprintWorker.handle_result` runs back in the
main process to persist `file_identity` fingerprint columns and chain to
`identify_metadata` (MetadataWorker itself is Phase 6).

Skip logic for *unchanged files* already lives upstream in
:class:`~vaultseek.workers.io.scanner_worker.ScannerWorker` (size/mtime)
and :class:`~vaultseek.workers.cpu.hash_worker.HashWorker` (content hash).
This worker only runs when the content hash changed (or is new). A
defensive early-complete path covers crash-recovery re-delivery when a
fingerprint is already stored for the current identity snapshot.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.writer import DatabaseWriter, WriteDTO
from vaultseek.models.entities.job import Job, JobType
from vaultseek.plugins.builtin.chromaprint import generate_chromaprint
from vaultseek.services.job_queue_service import JobQueueService


def compute_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    """The picklable unit of work for a ProcessPoolExecutor worker.

    ``payload`` is a `fingerprint_file` job's `Job.payload` —
    ``{"track_id": str, "file_path": str}`` (see
    :class:`~vaultseek.workers.cpu.hash_worker.HashWorker`, which
    enqueues these). Never raises — failures are reported as a plain
    ``{"track_id", "error"}`` dict so they survive the process boundary.
    """
    track_id = payload["track_id"]
    file_path = Path(payload["file_path"])
    try:
        result = generate_chromaprint(file_path)
    except (OSError, RuntimeError) as exc:
        return {"track_id": track_id, "error": str(exc)}

    return {
        "track_id": track_id,
        "fingerprint_data": result.fingerprint_data,
        "fingerprint_duration": result.duration_seconds,
        "fingerprint_hash": result.fingerprint_hash,
    }


class FingerprintWorker:
    """Owns the database-facing half of the `fingerprint_file` pipeline
    stage — see the module docstring for why this is split from
    :func:`compute_fingerprint`.
    """

    def __init__(
        self,
        file_identity_repo: FileIdentityRepository,
        database_writer: DatabaseWriter,
        job_queue: JobQueueService,
    ) -> None:
        self._file_identity_repo = file_identity_repo
        self._writer = database_writer
        self._job_queue = job_queue

    def already_fingerprinted(self, job: Job) -> bool:
        """True when this identity snapshot already has Chromaprint data.

        Used by :class:`~vaultseek.services.job_dispatcher.JobDispatcher`
        to skip ProcessPool work on crash-recovery re-delivery: complete
        the job and chain to ``identify_metadata`` without recomputing.
        Force-rescan jobs always recompute.
        """
        if job.payload.get("force"):
            return False
        track_id = UUID(job.payload["track_id"])
        identity = self._file_identity_repo.get(track_id)
        return identity is not None and identity.fingerprint_data is not None

    def complete_without_recompute(self, job: Job) -> None:
        """Mark the job done and chain to metadata when fingerprint data
        is already present (see :meth:`already_fingerprinted`)."""
        track_id = UUID(job.payload["track_id"])
        self._job_queue.enqueue(
            JobType.IDENTIFY_METADATA,
            job.library_id,
            {"track_id": str(track_id)},
            parent_job_id=job.id,
        )
        self._job_queue.mark_completed(job.id)

    def handle_result(self, job: Job, result: dict[str, Any]) -> None:
        """Persist Chromaprint fields onto the existing `file_identity`
        row and enqueue ``identify_metadata``."""
        error = result.get("error")
        if error is not None:
            self._job_queue.mark_failed(job.id, error)
            return

        track_id = UUID(result["track_id"])
        previous = self._file_identity_repo.get(track_id)
        if previous is None:
            self._job_queue.mark_failed(
                job.id,
                f"No file_identity row for track {track_id} — hash_file must run first",
            )
            return

        identity = replace(
            previous,
            fingerprint_data=result["fingerprint_data"],
            fingerprint_duration=result["fingerprint_duration"],
            fingerprint_hash=result["fingerprint_hash"],
            fingerprint_computed_at=datetime.now(UTC),
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
        self._job_queue.enqueue(
            JobType.IDENTIFY_METADATA,
            job.library_id,
            {"track_id": str(track_id)},
            parent_job_id=job.id,
        )
        self._job_queue.mark_completed(job.id)

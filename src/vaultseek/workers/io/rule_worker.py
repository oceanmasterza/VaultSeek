"""RuleWorker — runs `evaluate_rules` jobs through RulesEngine.

I/O / DB-bound (Tier 2). Seeds default rules on first evaluation for a
library, builds :class:`~vaultseek.services.dto.rule_dto.RuleContext`
(including the real ``has_lossless_duplicate`` flag from Phase 9
duplicate groups), evaluates enabled rules, and applies actions.

**In-place processing:** files stay in *incoming* until identity is
confirmed. When confidence meets the library auto-approve threshold and
the track is not flagged for review / open duplicates, this worker
enqueues a single ``organize_file`` move **incoming → library**.
Otherwise the file is left in incoming for the Review queue (approval
then moves incoming → library). Staging is no longer an automatic hop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.models.entities.job import Job, JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.rules_engine import RulesEngine


class RuleWorker:
    def __init__(
        self,
        track_repo: TrackRepository,
        rules_engine: RulesEngine,
        duplicate_repo: DuplicateRepository,
        job_queue: JobQueueService,
        *,
        library_repo: LibraryRepository | None = None,
    ) -> None:
        self._tracks = track_repo
        self._rules = rules_engine
        self._duplicates = duplicate_repo
        self._job_queue = job_queue
        self._libraries = library_repo

    def execute(self, job: Job) -> None:
        track_id = UUID(job.payload["track_id"])
        track = self._tracks.get_by_id(track_id)
        if track is None:
            self._job_queue.mark_failed(job.id, f"Track {track_id} not found")
            return

        now = datetime.now(UTC)
        self._rules.ensure_defaults(job.library_id, now=now)
        context = self._rules.build_context(
            track,
            has_lossless_duplicate=self._duplicates.has_lossless_duplicate(track_id),
        )
        matches = self._rules.evaluate(track, context)
        current = self._rules.apply_matches(track, matches, now=now)

        if current.zone is LibraryZone.INCOMING:
            library = (
                self._libraries.get(job.library_id) if self._libraries is not None else None
            )
            if _ready_for_library(current, library, self._duplicates):
                self._job_queue.enqueue(
                    JobType.ORGANIZE_FILE,
                    job.library_id,
                    {
                        "track_id": str(track_id),
                        "target_zone": LibraryZone.LIBRARY.value,
                    },
                    parent_job_id=job.id,
                    now=now,
                )
        self._job_queue.mark_completed(job.id)


def _ready_for_library(
    track: Track,
    library: Library | None,
    duplicates: DuplicateRepository,
) -> bool:
    """True when the original may leave Incoming for the final library folder."""
    if track.needs_review:
        return False
    if track.overall_confidence is None:
        return False
    threshold = library.auto_approve_threshold if library is not None else 0.90
    if track.overall_confidence < threshold:
        return False
    if duplicates.has_open_group(track.id):
        return False
    return True

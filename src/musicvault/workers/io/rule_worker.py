"""RuleWorker — runs `evaluate_rules` jobs through RulesEngine.

I/O / DB-bound (Tier 2). Seeds default rules on first evaluation for a
library, builds :class:`~musicvault.services.dto.rule_dto.RuleContext`
(including the real ``has_lossless_duplicate`` flag from Phase 9
duplicate groups), evaluates enabled rules, and applies actions. As the
pipeline's last analysis stage, it then enqueues the Phase 10 organize
step: tracks still in *incoming* move to *staging* ("processed but not
approved" — docs/architecture/10-revision-v2.md watch-folder flow);
auto-approve from staging to library is decided by
:class:`~musicvault.workers.io.organizer_worker.OrganizerWorker` after
that move completes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from musicvault.db.repositories.duplicate_repo import DuplicateRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.models.entities.job import Job, JobType
from musicvault.models.entities.track import LibraryZone
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.rules_engine import RulesEngine


class RuleWorker:
    def __init__(
        self,
        track_repo: TrackRepository,
        rules_engine: RulesEngine,
        duplicate_repo: DuplicateRepository,
        job_queue: JobQueueService,
    ) -> None:
        self._tracks = track_repo
        self._rules = rules_engine
        self._duplicates = duplicate_repo
        self._job_queue = job_queue

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
            self._job_queue.enqueue(
                JobType.ORGANIZE_FILE,
                job.library_id,
                {"track_id": str(track_id), "target_zone": LibraryZone.STAGING.value},
                parent_job_id=job.id,
                now=now,
            )
        self._job_queue.mark_completed(job.id)

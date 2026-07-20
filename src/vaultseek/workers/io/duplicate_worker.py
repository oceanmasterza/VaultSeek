"""DuplicateWorker — runs `detect_duplicates` jobs through DuplicateMatcher.

I/O / DB-bound (Tier 2). Finds other tracks in the library sharing an
exact matching key (content hash > Chromaprint hash > MusicBrainz
recording ID), persists a duplicate group with quality-ranked members,
and either auto-keeps the highest-quality copy (confident tracks) or
creates a ``possible_duplicate`` review item.

**Album policy:** fingerprint / MB recording matches only count when both
tracks share the same album context (same release). The same song on two
different albums is kept as two collection entries. Identical file bytes
(``hash``) are always duplicates regardless of tags.

Chains to `evaluate_rules` so the rules engine sees the real
``has_lossless_duplicate`` flag.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.duplicate_group import (
    DuplicateMember,
    GroupResolution,
    GroupStatus,
    MatchType,
)
from vaultseek.models.entities.job import Job, JobType
from vaultseek.models.entities.review_item import ReviewType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.services.album_context import same_album_context
from vaultseek.models.services.duplicate_matcher import DuplicateMatcher
from vaultseek.services.dto.review_dto import ReviewItemCreate
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.review_queue_service import ReviewQueueService

# Tier order: identical bytes beat identical audio beat same recording.
_TIER_ORDER = (MatchType.HASH, MatchType.FINGERPRINT, MatchType.MBID)
_AUTO_RESOLVE_THRESHOLD = 0.90


class DuplicateWorker:
    def __init__(
        self,
        track_repo: TrackRepository,
        file_identity_repo: FileIdentityRepository,
        duplicate_repo: DuplicateRepository,
        matcher: DuplicateMatcher,
        review_queue: ReviewQueueService,
        job_queue: JobQueueService,
        *,
        album_repo: AlbumRepository | None = None,
    ) -> None:
        self._tracks = track_repo
        self._identities = file_identity_repo
        self._duplicates = duplicate_repo
        self._matcher = matcher
        self._reviews = review_queue
        self._job_queue = job_queue
        self._albums = album_repo

    def execute(self, job: Job) -> None:
        track_id = UUID(job.payload["track_id"])
        track = self._tracks.get_by_id(track_id)
        if track is None:
            self._job_queue.mark_failed(job.id, f"Track {track_id} not found")
            return

        now = datetime.now(UTC)
        identity = self._identities.get(track_id)
        candidates = self._duplicates.find_matching_track_ids(
            job.library_id,
            track_id,
            content_hash=identity.content_hash_sha256 if identity else None,
            fingerprint_hash=identity.fingerprint_hash if identity else None,
            mb_recording_id=track.mb_recording_id,
        )
        candidates = self._filter_by_album_policy(track, candidates)

        match_type = next((tier for tier in _TIER_ORDER if tier in candidates), None)
        if match_type is not None:
            self._persist_group(job.library_id, track, candidates[match_type], match_type, now)

        self._job_queue.enqueue(
            JobType.EVALUATE_RULES,
            job.library_id,
            {"track_id": str(track_id)},
            parent_job_id=job.id,
            now=now,
        )
        self._job_queue.mark_completed(job.id)

    def _filter_by_album_policy(
        self,
        track: Track,
        candidates: dict[MatchType, list[UUID]],
    ) -> dict[MatchType, list[UUID]]:
        """Drop fingerprint/MBID hits that belong to a different album."""
        filtered: dict[MatchType, list[UUID]] = {}
        for match_type, track_ids in candidates.items():
            if match_type is MatchType.HASH:
                filtered[match_type] = track_ids
                continue
            same_album = [
                other_id
                for other_id in track_ids
                if (other := self._tracks.get_by_id(other_id)) is not None
                and same_album_context(track, other, self._albums)
            ]
            if same_album:
                filtered[match_type] = same_album
        return filtered

    def _persist_group(
        self,
        library_id: UUID,
        track: Track,
        matched_ids: list[UUID],
        match_type: MatchType,
        now: datetime,
    ) -> None:
        members = [track] + [
            loaded
            for track_id in matched_ids
            if (loaded := self._tracks.get_by_id(track_id)) is not None
        ]
        if len(members) < 2:
            return

        scored = [self._ensure_quality_score(member, now) for member in members]

        existing = self._duplicates.find_open_group_for_track(track.id, match_type)
        group_id = existing.id if existing is not None else generate_uuid7()
        group, group_members = self._matcher.build_group(
            group_id, library_id, scored, match_type, detected_at=now
        )
        self._duplicates.save_group(group, group_members)

        best = next(member for member in group_members if member.is_best)
        if _ready_to_auto_keep_best(track):
            self._auto_keep_best(library_id, group.id, group_members, now)
            return

        self._reviews.create_item(
            ReviewItemCreate(
                library_id=library_id,
                review_type=ReviewType.POSSIBLE_DUPLICATE,
                title=f"{group.track_count} duplicate copies detected ({match_type.value})",
                track_id=track.id,
                duplicate_group_id=group.id,
                confidence=group.match_confidence,
                description=(
                    f"Matched by {match_type.value}; best copy has "
                    f"quality score {best.quality_score}"
                ),
                payload={
                    "group_id": str(group.id),
                    "match_type": match_type.value,
                    "best_track_id": str(group.best_track_id),
                    "track_ids": [str(member.track_id) for member in group_members],
                },
            ),
            now=now,
        )

    def _auto_keep_best(
        self,
        library_id: UUID,
        group_id: UUID,
        members: list[DuplicateMember],
        now: datetime,
    ) -> None:
        """Keep the highest-quality copy; archive the rest without Review."""
        self._duplicates.set_status(
            group_id,
            GroupStatus.RESOLVED,
            resolution=GroupResolution.KEPT_BEST,
        )
        for member in members:
            if member.is_best:
                continue
            self._job_queue.enqueue(
                JobType.ORGANIZE_FILE,
                library_id,
                {
                    "track_id": str(member.track_id),
                    "target_zone": LibraryZone.ARCHIVE.value,
                },
                now=now,
            )

    def _ensure_quality_score(self, track: Track, now: datetime) -> Track:
        score = self._matcher.score(track)
        if track.quality_score == score:
            return track
        updated = replace(track, quality_score=score, updated_at=now)
        self._tracks.upsert(updated)
        return updated


def _ready_to_auto_keep_best(track: Track) -> bool:
    if track.needs_review:
        return False
    if track.overall_confidence is None:
        return False
    return track.overall_confidence >= _AUTO_RESOLVE_THRESHOLD

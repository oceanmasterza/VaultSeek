"""ReviewQueueService — human approval gate for uncertain metadata.

Auto-created by :class:`~vaultseek.workers.io.metadata_worker.MetadataWorker`
when arbitration sets ``needs_review``. Approve / reject / defer / edit
are called by the Review UI (Phase 14) or tests today.

Since Phase 10, approval also triggers zone moves (via `organize_file`
jobs) when ``job_queue`` is wired:

- approving a ``rule_action`` item executes its parked ``move_to_zone``
  actions (other parked action types stay manual until a richer
  re-apply flow exists);
- approving a ``possible_duplicate`` item resolves the duplicate group
  as ``kept_best`` and archives the non-best members whose zone allows
  it;
- approving any other track-linked item promotes an *incoming* or
  *staging* track straight to the library (originals stay in incoming
  until confirmation).

When ``job_queue`` is not provided (lightweight test setups), approval
only resolves the item and clears ``needs_review`` — the Phase 7
behavior.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from vaultseek.core.event_bus import EventBus
from vaultseek.core.exceptions import ReviewError
from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.duplicate_group import GroupResolution, GroupStatus
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.review_item import ReviewItem, ReviewStatus, ReviewType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.interfaces.metadata import ArbitrationResult
from vaultseek.models.services.organize_engine import OrganizeEngine
from vaultseek.services.dto.review_dto import ReviewItemCreate
from vaultseek.services.events import ReviewItemAddedEvent
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.library_tracklist_matcher import (
    AcquisitionProvenance,
    AlbumSlotRecommendation,
    LibraryTracklistMatcher,
    _duration_close,
)
from vaultseek.services.recording_identity import recordings_compatible
from vaultseek.services.tag_writer import TagWriteRequest, TagWriteResult, write_embedded_tags

_PROVIDER_CONFLICT_GAP = 0.10
_EDITABLE_TRACK_FIELDS = frozenset(
    {
        "title",
        "year",
        "genre",
        "composer",
        "track_number",
        "disc_number",
        "mb_recording_id",
        "artist_id",
        "album_id",
    }
)
_TITLE_BY_TYPE = {
    ReviewType.UNKNOWN_ARTIST: "Unknown or low-confidence artist",
    ReviewType.UNKNOWN_ALBUM: "Unknown or low-confidence album",
    ReviewType.METADATA_CONFLICT: "Providers disagree on metadata",
}
_OBSOLETE_IDENTITY_TYPES = frozenset(
    {
        ReviewType.UNKNOWN_ARTIST,
        ReviewType.UNKNOWN_ALBUM,
        ReviewType.METADATA_CONFLICT,
        ReviewType.ARTWORK_MISSING,
        ReviewType.ARTWORK_LOW_RES,
    }
)


@dataclass(frozen=True, slots=True)
class AlbumChoice:
    """Same-library album option for the Review Assign chooser."""

    album_id: UUID
    artist_name: str
    album_title: str
    year: int | None


@dataclass(frozen=True, slots=True)
class AlbumSlotChoice:
    """Existing track slot on a same-library album for Assign."""

    title: str
    track_number: int | None
    disc_number: int
    artist_id: UUID | None


class ReviewQueueService:
    def __init__(
        self,
        review_repository: ReviewRepository,
        track_repository: TrackRepository,
        event_bus: EventBus,
        *,
        confidence_threshold: float = 0.90,
        job_queue: JobQueueService | None = None,
        duplicate_repository: DuplicateRepository | None = None,
        library_matcher: LibraryTracklistMatcher | None = None,
        album_repository: AlbumRepository | None = None,
        artist_repository: ArtistRepository | None = None,
        provenance_lookup: Callable[[Track], AcquisitionProvenance | None] | None = None,
        quality_upgrader: Callable[[UUID], None] | None = None,
        tag_writer: Callable[..., TagWriteResult] | None = None,
    ) -> None:
        self._reviews = review_repository
        self._tracks = track_repository
        self._events = event_bus
        self._threshold = confidence_threshold
        self._job_queue = job_queue
        self._duplicates = duplicate_repository
        self._library_matcher = library_matcher
        self._albums = album_repository
        self._artists = artist_repository
        self._provenance_lookup = provenance_lookup
        self._quality_upgrader = quality_upgrader
        self._tag_writer = tag_writer or write_embedded_tags
        self._organize = OrganizeEngine()

    def create_item(self, item: ReviewItemCreate, *, now: datetime | None = None) -> UUID:
        """Insert a pending review item, or refresh an existing pending one
        for the same ``(track_id, review_type)`` (idempotent re-identify).

        Acquisition failures without a track also dedupe on
        ``payload.acquisition_job_id``.
        """
        created_at = _resolve_now(now)
        existing: ReviewItem | None = None
        if item.track_id is not None:
            existing = self._reviews.find_pending(
                track_id=item.track_id, review_type=item.review_type
            )
        if existing is None:
            job_id_raw = (item.payload or {}).get("acquisition_job_id")
            if job_id_raw:
                try:
                    job_uuid = UUID(str(job_id_raw))
                except ValueError:
                    job_uuid = None
                if job_uuid is not None:
                    existing = self._reviews.find_pending_for_acquisition_job(
                        library_id=item.library_id,
                        acquisition_job_id=job_uuid,
                        review_type=item.review_type,
                    )
        if existing is not None:
            # Skip no-op refreshes — re-parking hundreds of acquisition failures
            # every automation tick was flooding the event bus and freezing the UI.
            same_content = (
                existing.title == item.title
                and (existing.description or "") == (item.description or "")
                and existing.confidence == item.confidence
                and (existing.payload or {}) == (item.payload or {})
            )
            if same_content:
                return existing.id
            self._reviews.update_pending_content(
                existing.id,
                title=item.title,
                description=item.description,
                confidence=item.confidence,
                payload=item.payload,
            )
            self._events.publish(
                ReviewItemAddedEvent(
                    review_id=existing.id,
                    library_id=item.library_id,
                    review_type=item.review_type,
                    track_id=item.track_id,
                )
            )
            return existing.id

        review_id = generate_uuid7()
        self._reviews.create(
            ReviewItem(
                id=review_id,
                library_id=item.library_id,
                review_type=item.review_type,
                status=ReviewStatus.PENDING,
                title=item.title,
                created_at=created_at,
                track_id=item.track_id,
                album_id=item.album_id,
                duplicate_group_id=item.duplicate_group_id,
                description=item.description,
                confidence=item.confidence,
                payload=item.payload,
            )
        )
        self._events.publish(
            ReviewItemAddedEvent(
                review_id=review_id,
                library_id=item.library_id,
                review_type=item.review_type,
                track_id=item.track_id,
            )
        )
        return review_id

    def create_from_arbitration(
        self,
        *,
        library_id: UUID,
        track_id: UUID,
        result: ArbitrationResult,
        now: datetime | None = None,
    ) -> UUID:
        """Classify and enqueue a review item from an :class:`ArbitrationResult`."""
        review_type = classify_review_type(result, self._threshold)
        payload = _payload_from_result(result)
        track = self._tracks.get_by_id(track_id)
        if track is not None and self._library_matcher is not None:
            provenance = (
                self._provenance_lookup(track) if self._provenance_lookup is not None else None
            )
            recommendations = self._library_matcher.recommend(track, provenance=provenance)
            if recommendations:
                payload["album_recommendations"] = [
                    _recommendation_payload(item) for item in recommendations[:12]
                ]
        return self.create_item(
            ReviewItemCreate(
                library_id=library_id,
                review_type=review_type,
                title=_display_title(result, review_type),
                track_id=track_id,
                description=_describe(result, review_type),
                confidence=result.overall_confidence,
                payload=payload,
            ),
            now=now,
        )

    def album_recommendations(self, item_id: UUID) -> tuple[AlbumSlotRecommendation, ...]:
        """Fresh library tracklist recommendations for a pending Review item."""
        item = self._require_pending(item_id)
        if item.track_id is None or self._library_matcher is None:
            return ()
        track = self._tracks.get_by_id(item.track_id)
        if track is None:
            return ()
        provenance = self._provenance_lookup(track) if self._provenance_lookup is not None else None
        return self._library_matcher.recommend(track, provenance=provenance)

    def assignment_albums(self, library_id: UUID) -> tuple[AlbumChoice, ...]:
        """All albums that already have tracks in this library (chooser catalog)."""
        if self._albums is None:
            return ()
        rows = self._albums.list_for_library(library_id, limit=10_000)
        return tuple(
            AlbumChoice(
                album_id=row.album_id,
                artist_name=row.artist_name or "",
                album_title=row.title,
                year=row.year,
            )
            for row in rows
        )

    def assignment_slots(self, library_id: UUID, album_id: UUID) -> tuple[AlbumSlotChoice, ...]:
        """Distinct track slots already present on a same-library album."""
        self._require_same_library_album(library_id, album_id)
        seen: set[tuple[object, ...]] = set()
        slots: list[AlbumSlotChoice] = []
        for track in self._tracks.list_by_album(library_id, album_id, limit=500):
            title = (track.title or track.file_name or "").strip()
            if not title:
                continue
            key = (track.disc_number, track.track_number, title.casefold())
            if key in seen:
                continue
            seen.add(key)
            slots.append(
                AlbumSlotChoice(
                    title=title,
                    track_number=track.track_number,
                    disc_number=track.disc_number,
                    artist_id=track.artist_id,
                )
            )
        return tuple(slots)

    def assign_album_slot(
        self,
        item_id: UUID,
        *,
        album_id: UUID,
        title: str,
        track_number: int | None = None,
        disc_number: int = 1,
        artist_id: UUID | None = None,
        resolved_by: str = "user",
        now: datetime | None = None,
    ) -> None:
        """Assign a same-library album slot, write tags, clear identity blockers.

        A better LIBRARY copy does not block identity — after tagging, the
        promote path archives the worse Incoming via the duplicate pipeline.
        """
        item = self._require_pending(item_id)
        if item.track_id is None:
            raise ReviewError(f"Review item {item_id} has no track to assign")
        track = self._tracks.get_by_id(item.track_id)
        if track is None:
            raise ReviewError(f"Track {item.track_id} not found for review {item_id}")
        if self._albums is None:
            raise ReviewError("Album repository is not configured")
        album = self._albums.get(album_id)
        if album is None:
            raise ReviewError(f"Album {album_id} not found")
        self._require_same_library_album(item.library_id, album_id)

        edits: dict[str, Any] = {
            "album_id": album_id,
            "title": title.strip(),
            "disc_number": disc_number,
        }
        if track_number is not None:
            edits["track_number"] = track_number
        if artist_id is not None:
            edits["artist_id"] = artist_id
        elif album.album_artist_id is not None:
            edits["artist_id"] = album.album_artist_id
        self.approve_with_edits(item_id, edits, resolved_by=resolved_by, now=now)

    def resolve_obsolete_identity_items(
        self,
        track_id: UUID,
        *,
        resolved_by: str = "system",
        now: datetime | None = None,
        keep_types: frozenset[ReviewType] | None = None,
    ) -> int:
        """Approve obsolete identity/artwork blockers; leave unrelated Review items."""
        resolved_at = _resolve_now(now)
        retain = keep_types or frozenset()
        cleared = 0
        for pending in self._reviews.list_pending_for_track(track_id):
            if pending.review_type in retain:
                continue
            if pending.review_type not in _OBSOLETE_IDENTITY_TYPES:
                continue
            self._reviews.resolve(
                pending.id,
                ReviewStatus.APPROVED,
                resolved_by=resolved_by,
                resolved_at=resolved_at,
                description=(pending.description or "") + "\nResolved after confirmed identity.",
            )
            cleared += 1
        return cleared

    def dismiss_artwork_blockers(
        self, track_id: UUID, *, resolved_by: str = "system", now: datetime | None = None
    ) -> int:
        """Resolve legacy per-track artwork_missing / low_res so promotion is not blocked."""
        resolved_at = _resolve_now(now)
        cleared = 0
        for pending in self._reviews.list_pending_for_track(track_id):
            if pending.review_type not in (ReviewType.ARTWORK_MISSING, ReviewType.ARTWORK_LOW_RES):
                continue
            self._reviews.resolve(
                pending.id,
                ReviewStatus.APPROVED,
                resolved_by=resolved_by,
                resolved_at=resolved_at,
                description=(pending.description or "") + "\nCleared after album assignment.",
            )
            cleared += 1
        return cleared

    def get_pending(self, library_id: UUID) -> Sequence[ReviewItem]:
        """Return pending items for a library (deferred items are excluded)."""
        return self._reviews.list_by_status(ReviewStatus.PENDING, library_id=library_id)

    def count_pending(self, library_id: UUID) -> int:
        """Cheap pending count for GUI badges / status bar."""
        return self._reviews.count_pending(library_id)

    def get_by_type(self, library_id: UUID, review_type: ReviewType) -> Sequence[ReviewItem]:
        return self._reviews.list_by_type(review_type, library_id=library_id)

    def approve(
        self, item_id: UUID, *, resolved_by: str = "user", now: datetime | None = None
    ) -> None:
        """Accept the item; clear ``needs_review`` / promote only when no
        other pending items remain for the track."""
        item = self._require_pending(item_id)
        resolved_at = _resolve_now(now)
        if item.track_id is not None:
            track = self._tracks.get_by_id(item.track_id)
            if track is not None and track.album_id is not None:
                self.dismiss_artwork_blockers(
                    item.track_id, resolved_by=resolved_by, now=resolved_at
                )
                self._write_tags_for_track(track, require_success=True)
        self._reviews.resolve(
            item_id, ReviewStatus.APPROVED, resolved_by=resolved_by, resolved_at=resolved_at
        )
        self._maybe_clear_needs_review(item.track_id, resolved_at)
        self._run_post_approve(item, resolved_at)

    def reject(
        self,
        item_id: UUID,
        reason: str | None = None,
        *,
        resolved_by: str = "user",
        now: datetime | None = None,
    ) -> None:
        """Reject the item. Leaves ``tracks.needs_review`` set so it stays visible."""
        item = self._require_pending(item_id)
        description = item.description
        if reason:
            description = f"{description}\nReject reason: {reason}" if description else reason
        self._reviews.resolve(
            item_id,
            ReviewStatus.REJECTED,
            resolved_by=resolved_by,
            resolved_at=_resolve_now(now),
            description=description,
        )

    def defer(
        self, item_id: UUID, *, resolved_by: str = "user", now: datetime | None = None
    ) -> None:
        """Park the item outside the pending list. Leaves ``needs_review`` set."""
        self._require_pending(item_id)
        self._reviews.resolve(
            item_id,
            ReviewStatus.DEFERRED,
            resolved_by=resolved_by,
            resolved_at=_resolve_now(now),
        )

    def approve_with_edits(
        self,
        item_id: UUID,
        edits: dict[str, Any],
        *,
        resolved_by: str = "user",
        now: datetime | None = None,
    ) -> None:
        """Apply user field edits to the track, then approve."""
        unknown = set(edits) - _EDITABLE_TRACK_FIELDS
        if unknown:
            raise ReviewError(f"Unsupported review edits: {sorted(unknown)}")
        item = self._require_pending(item_id)
        if item.track_id is None:
            raise ReviewError(f"Review item {item_id} has no track to edit")
        track = self._tracks.get_by_id(item.track_id)
        if track is None:
            raise ReviewError(f"Track {item.track_id} not found for review {item_id}")

        if "album_id" in edits:
            album_id = edits["album_id"]
            if not isinstance(album_id, UUID):
                raise ReviewError("album_id must be a UUID")
            self._require_same_library_album(item.library_id, album_id)
            if "artist_id" in edits and self._albums is not None:
                album = self._albums.get(album_id)
                artist_id = edits["artist_id"]
                if (
                    album is not None
                    and not album.is_compilation
                    and album.album_artist_id is not None
                    and isinstance(artist_id, UUID)
                    and artist_id != album.album_artist_id
                ):
                    raise ReviewError("artist_id must match the album artist for this release")
            # Compilations may use a per-track artist consistent with a slot.

        resolved_at = _resolve_now(now)
        updates: dict[str, object] = {
            "updated_at": resolved_at,
        }
        for key, value in edits.items():
            updates[key] = value
        remaining_after = [
            r for r in self._reviews.list_pending_for_track(item.track_id) if r.id != item_id
        ]
        if "album_id" in edits:
            self.dismiss_artwork_blockers(item.track_id, resolved_by=resolved_by, now=resolved_at)
            remaining_after = [
                r for r in self._reviews.list_pending_for_track(item.track_id) if r.id != item_id
            ]
        if not remaining_after:
            updates["needs_review"] = False
        updated = replace(track, **updates)  # type: ignore[arg-type]
        # Fail closed: tag write must succeed before identity is approved.
        self._write_tags_for_track(updated, require_success=True)
        # Refresh size/mtime so the next scan does not treat the file as stale identity.
        try:
            from pathlib import Path

            stat = Path(updated.file_path).stat()
            updated = replace(
                updated,
                file_size=int(stat.st_size),
                file_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                updated_at=resolved_at,
            )
        except OSError:
            pass
        self._tracks.upsert(updated)
        self._reviews.resolve(
            item_id, ReviewStatus.APPROVED, resolved_by=resolved_by, resolved_at=resolved_at
        )
        album_changed = "album_id" in edits and edits["album_id"] != track.album_id
        if "album_id" in edits and self._job_queue is not None:
            self._job_queue.enqueue(
                JobType.FETCH_ARTWORK,
                item.library_id,
                {"track_id": str(item.track_id)},
                now=resolved_at,
            )
            self._job_queue.enqueue(
                JobType.HASH_FILE,
                item.library_id,
                {"track_id": str(item.track_id)},
                now=resolved_at,
            )
            self._job_queue.enqueue(
                JobType.DETECT_DUPLICATES,
                item.library_id,
                {"track_id": str(item.track_id)},
                now=resolved_at,
            )
        # Already-LIBRARY Assign must physically reorganize to the new album path.
        if album_changed and track.zone is LibraryZone.LIBRARY and self._job_queue is not None:
            self._job_queue.enqueue(
                JobType.ORGANIZE_FILE,
                item.library_id,
                {
                    "track_id": str(item.track_id),
                    "target_zone": LibraryZone.LIBRARY.value,
                    "reorganize": True,
                },
                now=resolved_at,
            )
        self._run_post_approve(item, resolved_at)

    def _require_same_library_album(self, library_id: UUID, album_id: UUID) -> None:
        if self._albums is None:
            raise ReviewError("Album repository is not configured")
        album = self._albums.get(album_id)
        if album is None:
            raise ReviewError(f"Album {album_id} not found")
        in_library = self._tracks.list_by_album(library_id, album_id, limit=1)
        if not in_library:
            raise ReviewError("Album is not in this library — pick a same-library album")

    def _write_tags_for_track(self, track: Track, *, require_success: bool = False) -> None:
        path = track.file_path
        if not path:
            if require_success:
                raise ReviewError("Cannot write tags: track has no file path")
            return
        artist_name = None
        album_title = None
        if track.artist_id is not None and self._artists is not None:
            artist = self._artists.get(track.artist_id)
            artist_name = artist.name if artist is not None else None
        if track.album_id is not None and self._albums is not None:
            album = self._albums.get(track.album_id)
            album_title = album.title if album is not None else None
        result = self._tag_writer(
            str(path),
            TagWriteRequest(
                title=track.title,
                artist=artist_name,
                album=album_title,
                track_number=track.track_number,
                disc_number=track.disc_number,
                year=track.year,
            ),
        )
        if require_success and not result.wrote:
            raise ReviewError(f"Tag write failed: {result.error or 'unknown error'}")

    def _run_post_approve(self, item: ReviewItem, now: datetime) -> None:
        """Enqueue the zone moves this approval implies (no-op without a job queue)."""
        if self._job_queue is None:
            return
        if item.review_type is ReviewType.RULE_ACTION:
            self._execute_parked_moves(item, now)
            return
        if item.review_type is ReviewType.POSSIBLE_DUPLICATE:
            self._resolve_duplicate_group(item, now)
            return
        self._promote_to_library(item.track_id, item.library_id, now)

    def _execute_parked_moves(self, item: ReviewItem, now: datetime) -> None:
        for zone in _parked_move_zones(item.payload or {}):
            self._enqueue_move_if_legal(item.library_id, item.track_id, zone, now)

    def _resolve_duplicate_group(self, item: ReviewItem, now: datetime) -> None:
        """Keep the best copy; archive the other members where legal.

        After archiving losers, promote the best copy to library when it
        has no remaining pending review items.
        """
        if self._duplicates is None or item.duplicate_group_id is None:
            return
        group_id = item.duplicate_group_id
        self._duplicates.set_status(
            group_id, GroupStatus.RESOLVED, resolution=GroupResolution.KEPT_BEST
        )
        best_track_id: UUID | None = None
        for member in self._duplicates.get_members(group_id):
            if member.is_best:
                best_track_id = member.track_id
                continue
            self._enqueue_move_if_legal(item.library_id, member.track_id, LibraryZone.ARCHIVE, now)
        if best_track_id is not None:
            self._promote_to_library(best_track_id, item.library_id, now)

    def _promote_to_library(self, track_id: UUID | None, library_id: UUID, now: datetime) -> None:
        """Move Incoming or Staging → Library when the review backlog is clear.

        When a better active LIBRARY copy already occupies the same slot,
        archive this track instead (identity already applied; no overwrite).
        """
        if track_id is None:
            return
        if self._reviews.list_pending_for_track(track_id):
            return
        track = self._tracks.get_by_id(track_id)
        if track is None:
            return
        if track.zone not in (LibraryZone.INCOMING, LibraryZone.STAGING):
            return
        better = self._better_library_slot_copy(track)
        if better is not None:
            self._enqueue_move_if_legal(library_id, track_id, LibraryZone.ARCHIVE, now)
            if self._job_queue is not None:
                self._job_queue.enqueue(
                    JobType.DETECT_DUPLICATES,
                    library_id,
                    {"track_id": str(track_id)},
                    now=now,
                )
            # Better copy is already in LIBRARY — scoped upgrade may run now.
            if self._quality_upgrader is not None:
                self._quality_upgrader(better.id)
            return
        self._enqueue_move_if_legal(library_id, track_id, LibraryZone.LIBRARY, now)
        # Quality upgrade runs in OrganizerWorker after the file lands in LIBRARY.

    def _better_library_slot_copy(self, track: Track) -> Track | None:
        """Return an active LIBRARY file that outranks ``track`` on the same slot.

        Requires a physical healthy same-library same-album same
        recording/version/disc copy — never archive Incoming solely because a
        missing, corrupt, or wrong-duration DB row shares a title.
        """
        if track.album_id is None:
            return None
        from pathlib import Path

        title = track.title or track.file_name
        best: Track | None = None
        for existing in self._tracks.list_by_album(track.library_id, track.album_id, limit=200):
            if existing.id == track.id:
                continue
            if existing.zone is not LibraryZone.LIBRARY:
                continue
            if existing.is_corrupt:
                continue
            if not existing.file_path or not Path(existing.file_path).is_file():
                continue
            if existing.disc_number != track.disc_number:
                continue
            if track.track_number is not None and existing.track_number not in (
                None,
                track.track_number,
            ):
                continue
            existing_title = existing.title or existing.file_name
            if not recordings_compatible(title, existing_title):
                continue
            if (
                track.mb_recording_id
                and existing.mb_recording_id
                and track.mb_recording_id != existing.mb_recording_id
            ):
                continue
            if (
                track.duration_ms is not None
                and existing.duration_ms is not None
                and not _duration_close(track.duration_ms, existing.duration_ms)
            ):
                continue
            if not _existing_better(track, existing):
                continue
            if best is None or _existing_better(best, existing):
                best = existing
        return best

    def _enqueue_move_if_legal(
        self,
        library_id: UUID,
        track_id: UUID | None,
        target: LibraryZone,
        now: datetime,
    ) -> None:
        if self._job_queue is None or track_id is None:
            return
        track = self._tracks.get_by_id(track_id)
        if track is None or track.zone is target:
            return
        if not self._organize.can_transition(track.zone, target):
            return
        self._job_queue.enqueue(
            JobType.ORGANIZE_FILE,
            library_id,
            {"track_id": str(track_id), "target_zone": target.value},
            now=now,
        )

    def _require_pending(self, item_id: UUID) -> ReviewItem:
        item = self._reviews.get(item_id)
        if item is None:
            raise ReviewError(f"Review item {item_id} not found")
        if item.status is not ReviewStatus.PENDING:
            raise ReviewError(f"Review item {item_id} is {item.status.value}, expected pending")
        return item

    def _maybe_clear_needs_review(self, track_id: UUID | None, now: datetime) -> None:
        """Clear the track flag only when no pending review items remain."""
        if track_id is None:
            return
        if self._reviews.list_pending_for_track(track_id):
            return
        self._clear_needs_review(track_id, now)

    def _clear_needs_review(self, track_id: UUID | None, now: datetime) -> None:
        if track_id is None:
            return
        track = self._tracks.get_by_id(track_id)
        if track is None:
            return
        self._tracks.upsert(replace(track, needs_review=False, updated_at=now))


def classify_review_type(result: ArbitrationResult, threshold: float) -> ReviewType:
    """Pick a :class:`ReviewType` from arbitration fields.

    Priority: weak/missing artist → weak/missing album → near-tie provider
    conflict → catch-all ``unknown_artist``.
    """
    artist = result.fields.get("artist")
    if artist is None or artist.confidence < threshold:
        return ReviewType.UNKNOWN_ARTIST
    album = result.fields.get("album")
    if album is None or album.confidence < threshold:
        return ReviewType.UNKNOWN_ALBUM
    if _has_provider_conflict(result, gap=_PROVIDER_CONFLICT_GAP):
        return ReviewType.METADATA_CONFLICT
    return ReviewType.UNKNOWN_ARTIST


def _display_title(result: ArbitrationResult, review_type: ReviewType) -> str:
    """Human-readable track label for the Review table Title column."""
    artist = _field_str(result, "artist")
    title = _field_str(result, "title")
    if artist and title:
        return f"{artist} — {title}"
    if title:
        return title
    if artist:
        return artist
    return _TITLE_BY_TYPE.get(review_type, "Needs review")


def _field_str(result: ArbitrationResult, name: str) -> str | None:
    item = result.fields.get(name)
    if item is None or not isinstance(item.value, str):
        return None
    value = item.value.strip()
    return value or None


def _has_provider_conflict(result: ArbitrationResult, *, gap: float) -> bool:
    by_field: dict[str, list[tuple[object, float]]] = defaultdict(list)
    for provider in result.provider_results:
        for field in provider.fields:
            if field.value is None or field.value == "":
                continue
            by_field[field.field].append((field.value, field.confidence))
    for candidates in by_field.values():
        if len(candidates) < 2:
            continue
        ranked = sorted(candidates, key=lambda item: item[1], reverse=True)
        top_value, top_confidence = ranked[0]
        for value, confidence in ranked[1:]:
            if top_confidence - confidence <= gap and value != top_value:
                return True
    return False


def _describe(result: ArbitrationResult, review_type: ReviewType) -> str:
    reason = _TITLE_BY_TYPE.get(review_type, "Needs review")
    overall = f"Overall confidence {result.overall_confidence:.2f}"
    if review_type is ReviewType.METADATA_CONFLICT:
        detail = f"{overall}; providers disagree on one or more fields"
    elif review_type is ReviewType.UNKNOWN_ALBUM:
        album = result.fields.get("album")
        if album is None:
            detail = f"{overall}; album missing"
        else:
            detail = f"{overall}; album confidence {album.confidence:.2f}"
    else:
        artist = result.fields.get("artist")
        if artist is None:
            detail = f"{overall}; artist missing"
        else:
            detail = f"{overall}; artist confidence {artist.confidence:.2f}"
    return f"{reason}. {detail}"


def _payload_from_result(result: ArbitrationResult) -> dict[str, Any]:
    return {
        "overall_confidence": result.overall_confidence,
        "fields": {
            name: {
                "value": field.value,
                "confidence": field.confidence,
                "source": field.source,
            }
            for name, field in result.fields.items()
        },
    }


def _recommendation_payload(item: AlbumSlotRecommendation) -> dict[str, Any]:
    return {
        "album_id": str(item.album_id),
        "album_title": item.album_title,
        "artist_id": str(item.artist_id) if item.artist_id else None,
        "artist_name": item.artist_name,
        "disc_number": item.disc_number,
        "track_number": item.track_number,
        "slot_title": item.slot_title,
        "score": item.score,
        "reasons": list(item.reasons),
        "existing_track_id": str(item.existing_track_id) if item.existing_track_id else None,
        "existing_is_better": item.existing_is_better,
        "version_kind": item.version_kind,
        "version_conflict": item.version_conflict,
        "corroboration_count": item.corroboration_count,
        "duration_ok": item.duration_ok,
        "song_corroboration": item.song_corroboration,
        "release_mismatch": item.release_mismatch,
        "exact_release": item.exact_release,
    }


def _existing_better(incoming: Track, existing: Track) -> bool:
    if existing.zone is not LibraryZone.LIBRARY:
        return False
    if existing.is_lossless and not incoming.is_lossless:
        return True
    if incoming.is_lossless and not existing.is_lossless:
        return False
    return (existing.quality_score or 0) > (incoming.quality_score or 0) or (
        (existing.bitrate or 0) > (incoming.bitrate or 0)
    )


def _parked_move_zones(payload: dict[str, Any]) -> list[LibraryZone]:
    """Extract ``move_to_zone`` targets from a `rule_action` item payload.

    Handles both payload shapes the rules engine produces: a single
    parked action (``{"action_type": "move_to_zone", "zone": ...}``) and
    a `requires_approval` rule's full action list
    (``{"actions": [{"action_type": ..., "parameters": {...}}, ...]}``).
    Unknown zone strings are skipped.
    """
    raw_zones: list[object] = []
    if payload.get("action_type") == "move_to_zone":
        raw_zones.append(payload.get("zone"))
    actions = payload.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict) and action.get("action_type") == "move_to_zone":
                parameters = action.get("parameters")
                if isinstance(parameters, dict):
                    raw_zones.append(parameters.get("zone"))
    zones: list[LibraryZone] = []
    for raw in raw_zones:
        if isinstance(raw, str):
            try:
                zones.append(LibraryZone(raw))
            except ValueError:
                continue
    return zones


def _resolve_now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)

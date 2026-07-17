"""RulesEngine — evaluate and manage automation rules.

Wraps the Phase 3 condition AST
(:func:`~musicvault.models.value_objects.rule_condition.parse_conditions`)
with repository loading, default seeding, CRUD, and action application.
``has_lossless_duplicate`` is computed from Phase 9 duplicate groups by
the caller (`RuleWorker`). Since Phase 10, a non-approval
``move_to_zone`` action enqueues a real `organize_file` job;
`requires_approval` rules still park in the review queue, where
approval executes the move.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from musicvault.core.event_bus import EventBus
from musicvault.core.exceptions import RuleError
from musicvault.db.repositories.artist_repo import ArtistRepository
from musicvault.db.repositories.rule_repo import RuleRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.artist import Artist
from musicvault.models.entities.job import JobType
from musicvault.models.entities.review_item import ReviewType
from musicvault.models.entities.rule import Rule
from musicvault.models.entities.track import LibraryZone, Track
from musicvault.models.services.organize_engine import OrganizeEngine
from musicvault.models.value_objects.rule_action import RuleAction
from musicvault.models.value_objects.rule_condition import parse_conditions
from musicvault.services.default_rules import DEFAULT_RULE_SPECS
from musicvault.services.dto.review_dto import ReviewItemCreate
from musicvault.services.dto.rule_dto import RuleContext, RuleCreate, RuleMatch
from musicvault.services.events import RulesMatchedEvent
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.review_queue_service import ReviewQueueService

_SUPPORTED_ACTIONS = frozenset({"flag_review", "set_artist", "set_genre", "move_to_zone"})


class RulesEngine:
    def __init__(
        self,
        rule_repository: RuleRepository,
        track_repository: TrackRepository,
        artist_repository: ArtistRepository,
        review_queue: ReviewQueueService,
        event_bus: EventBus,
        job_queue: JobQueueService | None = None,
    ) -> None:
        self._rules = rule_repository
        self._tracks = track_repository
        self._artists = artist_repository
        self._reviews = review_queue
        self._events = event_bus
        self._job_queue = job_queue
        self._organize = OrganizeEngine()

    def build_context(
        self,
        track: Track,
        *,
        artist_name: str | None = None,
        has_lossless_duplicate: bool = False,
    ) -> RuleContext:
        """Build evaluation context for ``track``.

        When ``artist_name`` is omitted, resolves ``track.artist_id`` via
        :class:`ArtistRepository` (empty string when unset).
        """
        resolved_artist = artist_name
        if resolved_artist is None:
            resolved_artist = ""
            if track.artist_id is not None:
                artist = self._artists.get(track.artist_id)
                if artist is not None:
                    resolved_artist = artist.name
        return RuleContext(
            track_id=track.id,
            library_id=track.library_id,
            zone=track.zone.value,
            filename=track.file_name,
            file_path=track.file_path,
            codec=track.codec,
            bitrate=track.bitrate,
            bit_depth=track.bit_depth,
            sample_rate=track.sample_rate,
            quality_score=track.quality_score,
            title=track.title,
            artist=resolved_artist,
            genre=track.genre,
            year=track.year,
            track_number=track.track_number,
            composer=track.composer,
            duration_ms=track.duration_ms,
            is_lossless=track.is_lossless,
            needs_review=track.needs_review,
            overall_confidence=track.overall_confidence,
            has_lossless_duplicate=has_lossless_duplicate,
        )

    def evaluate(self, track: Track, context: RuleContext) -> list[RuleMatch]:
        """Return matches for enabled rules against ``context`` (priority order)."""
        mapping = context.as_mapping()
        matches: list[RuleMatch] = []
        for rule in self._rules.list_enabled(track.library_id):
            try:
                node = parse_conditions(rule.conditions)
            except ValueError as exc:
                raise RuleError(f"Rule {rule.id} has invalid conditions: {exc}") from exc
            if node.evaluate(mapping):
                matches.append(
                    RuleMatch(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        actions=_parse_actions(rule.actions),
                        requires_approval=rule.requires_approval,
                    )
                )
        return matches

    def evaluate_batch(
        self, track_ids: Sequence[UUID], *, has_lossless_duplicate: bool = False
    ) -> dict[UUID, list[RuleMatch]]:
        """Evaluate each track id; missing tracks are omitted from the result."""
        results: dict[UUID, list[RuleMatch]] = {}
        for track_id in track_ids:
            track = self._tracks.get_by_id(track_id)
            if track is None:
                continue
            context = self.build_context(track, has_lossless_duplicate=has_lossless_duplicate)
            results[track_id] = self.evaluate(track, context)
        return results

    def apply_matches(
        self,
        track: Track,
        matches: Sequence[RuleMatch],
        *,
        now: datetime | None = None,
    ) -> Track:
        """Execute matched rule actions (or park them as review items).

        Returns the (possibly updated) track after ``set_artist`` /
        ``set_genre`` mutations.
        """
        resolved_at = _resolve_now(now)
        current = track
        for match in matches:
            if match.requires_approval:
                self._flag_approval_required(current, match, now=resolved_at)
                continue
            for action in match.actions:
                current = self._apply_action(current, match, action, now=resolved_at)
        if matches:
            self._events.publish(
                RulesMatchedEvent(
                    library_id=track.library_id,
                    track_id=track.id,
                    rule_ids=tuple(match.rule_id for match in matches),
                )
            )
        return current

    def ensure_defaults(self, library_id: UUID, *, now: datetime | None = None) -> int:
        """Seed shipped default rules for ``library_id`` if missing by name.

        Returns the number of rules newly created.
        """
        created_at = _resolve_now(now)
        created = 0
        for spec in DEFAULT_RULE_SPECS:
            name = str(spec["name"])
            if self._rules.find_by_name(library_id, name) is not None:
                continue
            self._rules.create(
                Rule(
                    id=generate_uuid7(),
                    library_id=library_id,
                    name=name,
                    conditions=dict(spec["conditions"]),
                    actions=list(spec["actions"]),
                    created_at=created_at,
                    updated_at=created_at,
                    enabled=True,
                    priority=int(spec["priority"]),
                    requires_approval=bool(spec["requires_approval"]),
                )
            )
            created += 1
        return created

    def create_rule(self, spec: RuleCreate, *, now: datetime | None = None) -> UUID:
        created_at = _resolve_now(now)
        _validate_conditions(spec.conditions)
        _validate_action_dicts(spec.actions)
        rule_id = generate_uuid7()
        self._rules.create(
            Rule(
                id=rule_id,
                library_id=spec.library_id,
                name=spec.name,
                conditions=spec.conditions,
                actions=spec.actions,
                created_at=created_at,
                updated_at=created_at,
                enabled=spec.enabled,
                priority=spec.priority,
                requires_approval=spec.requires_approval,
            )
        )
        return rule_id

    def update_rule(self, rule: Rule, *, now: datetime | None = None) -> None:
        if self._rules.get(rule.id) is None:
            raise RuleError(f"Rule {rule.id} not found")
        _validate_conditions(rule.conditions)
        _validate_action_dicts(rule.actions)
        self._rules.update(replace(rule, updated_at=_resolve_now(now)))

    def delete_rule(self, rule_id: UUID) -> None:
        if self._rules.get(rule_id) is None:
            raise RuleError(f"Rule {rule_id} not found")
        self._rules.delete(rule_id)

    def list_rules(self, library_id: UUID) -> Sequence[Rule]:
        return self._rules.list_by_library(library_id)

    def set_enabled(self, rule_id: UUID, enabled: bool, *, now: datetime | None = None) -> None:
        rule = self._rules.get(rule_id)
        if rule is None:
            raise RuleError(f"Rule {rule_id} not found")
        self._rules.update(replace(rule, enabled=enabled, updated_at=_resolve_now(now)))

    def _apply_action(
        self,
        track: Track,
        match: RuleMatch,
        action: RuleAction,
        *,
        now: datetime,
    ) -> Track:
        if action.action_type == "flag_review":
            self._flag_review(track, match, action, now=now)
            return track
        if action.action_type == "set_artist":
            return self._set_artist(track, action, now=now)
        if action.action_type == "set_genre":
            genre = action.parameters.get("genre")
            if not isinstance(genre, str) or not genre:
                raise RuleError("set_genre requires a non-empty genre parameter")
            updated = replace(track, genre=genre, updated_at=now)
            self._tracks.upsert(updated)
            return updated
        if action.action_type == "move_to_zone":
            self._move_to_zone(track, match, action, now=now)
            return track
        raise RuleError(f"Unsupported rule action: {action.action_type!r}")

    def _move_to_zone(
        self, track: Track, match: RuleMatch, action: RuleAction, *, now: datetime
    ) -> None:
        """Enqueue a real zone move (Phase 10), or park a review item when
        no job queue is wired or the transition is illegal from the
        track's current zone."""
        zone = action.parameters.get("zone")
        target: LibraryZone | None = None
        if isinstance(zone, str):
            try:
                target = LibraryZone(zone)
            except ValueError:
                target = None
        if target is None:
            raise RuleError(f"move_to_zone requires a valid zone parameter, got {zone!r}")
        if (
            self._job_queue is None
            or track.zone is target
            or not self._organize.can_transition(track.zone, target)
        ):
            self._flag_move_intent(track, match, action, now=now)
            return
        self._job_queue.enqueue(
            JobType.ORGANIZE_FILE,
            track.library_id,
            {"track_id": str(track.id), "target_zone": target.value},
            now=now,
        )

    def _flag_approval_required(self, track: Track, match: RuleMatch, *, now: datetime) -> None:
        self._reviews.create_item(
            ReviewItemCreate(
                library_id=track.library_id,
                review_type=ReviewType.RULE_ACTION,
                title=f"Rule requires approval: {match.rule_name}",
                track_id=track.id,
                description=f"Matched rule '{match.rule_name}' needs human approval",
                payload={
                    "rule_id": str(match.rule_id),
                    "rule_name": match.rule_name,
                    "actions": [
                        {"action_type": a.action_type, "parameters": a.parameters}
                        for a in match.actions
                    ],
                },
            ),
            now=now,
        )

    def _flag_review(
        self, track: Track, match: RuleMatch, action: RuleAction, *, now: datetime
    ) -> None:
        reason = str(action.parameters.get("reason") or f"Matched rule '{match.rule_name}'")
        review_type = _review_type(action.parameters.get("review_type"))
        self._reviews.create_item(
            ReviewItemCreate(
                library_id=track.library_id,
                review_type=review_type,
                title=f"Rule: {match.rule_name}",
                track_id=track.id,
                description=reason,
                payload={
                    "rule_id": str(match.rule_id),
                    "rule_name": match.rule_name,
                    "reason": reason,
                },
            ),
            now=now,
        )

    def _flag_move_intent(
        self, track: Track, match: RuleMatch, action: RuleAction, *, now: datetime
    ) -> None:
        zone = action.parameters.get("zone")
        self._reviews.create_item(
            ReviewItemCreate(
                library_id=track.library_id,
                review_type=ReviewType.RULE_ACTION,
                title=f"Rule wants zone '{zone}': {match.rule_name}",
                track_id=track.id,
                description=(
                    f"Rule '{match.rule_name}' requested move_to_zone={zone!r} "
                    "but it could not be executed automatically"
                ),
                payload={
                    "rule_id": str(match.rule_id),
                    "action_type": "move_to_zone",
                    "zone": zone,
                },
            ),
            now=now,
        )

    def _set_artist(self, track: Track, action: RuleAction, *, now: datetime) -> Track:
        name = action.parameters.get("artist")
        if not isinstance(name, str) or not name:
            raise RuleError("set_artist requires a non-empty artist parameter")
        existing = self._artists.list_by_name(name)
        if existing:
            artist = existing[0]
        else:
            artist = Artist(
                id=generate_uuid7(),
                name=name,
                sort_name=name,
                created_at=now,
                updated_at=now,
            )
            self._artists.create(artist)
        updated = replace(track, artist_id=artist.id, updated_at=now)
        self._tracks.upsert(updated)
        return updated


def _parse_actions(raw: list[dict[str, Any]]) -> list[RuleAction]:
    actions: list[RuleAction] = []
    for item in raw:
        action_type = item.get("action_type")
        if not isinstance(action_type, str) or not action_type:
            raise RuleError(f"Malformed rule action (missing action_type): {item!r}")
        parameters = item.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise RuleError(f"Malformed rule action parameters: {item!r}")
        actions.append(RuleAction(action_type=action_type, parameters=parameters))
    return actions


def _validate_conditions(conditions: dict[str, Any]) -> None:
    try:
        parse_conditions(conditions)
    except ValueError as exc:
        raise RuleError(f"Invalid rule conditions: {exc}") from exc


def _validate_action_dicts(actions: list[dict[str, Any]]) -> None:
    parsed = _parse_actions(actions)
    unknown = {a.action_type for a in parsed} - _SUPPORTED_ACTIONS
    if unknown:
        raise RuleError(f"Unsupported rule action types: {sorted(unknown)}")


def _review_type(raw: object) -> ReviewType:
    if isinstance(raw, str):
        try:
            return ReviewType(raw)
        except ValueError:
            return ReviewType.RULE_ACTION
    return ReviewType.RULE_ACTION


def _resolve_now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)

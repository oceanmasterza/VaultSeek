"""Unit tests for RulesEngine."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine

from musicvault.core.event_bus import EventBus
from musicvault.core.exceptions import RuleError
from musicvault.db.repositories.artist_repo import ArtistRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.rule_repo import RuleRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.models.entities.job import JobStatus, JobType
from musicvault.models.entities.review_item import ReviewStatus, ReviewType
from musicvault.models.entities.track import LibraryZone, Track
from musicvault.services.dto.rule_dto import RuleCreate
from musicvault.services.events import RulesMatchedEvent
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.review_queue_service import ReviewQueueService
from musicvault.services.rules_engine import RulesEngine

_NOW = datetime(2026, 7, 16, tzinfo=UTC)


@pytest.fixture
def artist_repo(engine: Engine) -> ArtistRepository:
    return ArtistRepository(engine)


@pytest.fixture
def rules_engine(
    review_repo: ReviewRepository,
    rule_repo: RuleRepository,
    track_repo: TrackRepository,
    artist_repo: ArtistRepository,
    event_bus: EventBus,
) -> RulesEngine:
    review_queue = ReviewQueueService(review_repo, track_repo, event_bus)
    return RulesEngine(rule_repo, track_repo, artist_repo, review_queue, event_bus)


def _make_track(library_id: UUID, track_id: UUID, **overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": track_id,
        "library_id": library_id,
        "zone": LibraryZone.INCOMING,
        "file_path": "C:/incoming/track.flac",
        "file_name": "track.flac",
        "file_size": 1024,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def test_ensure_defaults_seeds_three_rules_idempotently(
    rules_engine: RulesEngine, library_id: UUID
) -> None:
    assert rules_engine.ensure_defaults(library_id, now=_NOW) == 3
    assert rules_engine.ensure_defaults(library_id, now=_NOW) == 0
    names = {rule.name for rule in rules_engine.list_rules(library_id)}
    assert "Archive MP3 when FLAC exists" in names
    assert "Detect Various Artists" in names
    assert "Flag low bitrate" in names


def test_evaluate_and_apply_flags_low_bitrate(
    rules_engine: RulesEngine,
    track_repo: TrackRepository,
    review_repo: ReviewRepository,
    event_bus: EventBus,
    library_id: UUID,
    track_id: UUID,
) -> None:
    rules_engine.ensure_defaults(library_id, now=_NOW)
    track = _make_track(library_id, track_id, codec="mp3", bitrate=128, file_name="song.mp3")
    track_repo.upsert(track)
    received: list[RulesMatchedEvent] = []
    event_bus.subscribe(RulesMatchedEvent, received.append)

    context = rules_engine.build_context(track)
    matches = rules_engine.evaluate(track, context)
    assert any(match.rule_name == "Flag low bitrate" for match in matches)

    rules_engine.apply_matches(track, matches, now=_NOW)
    pending = review_repo.list_by_status(ReviewStatus.PENDING, library_id=library_id)
    assert any(item.review_type is ReviewType.LOW_QUALITY for item in pending)
    assert received and track_id == received[0].track_id


def test_detect_va_sets_artist_and_flags_review(
    rules_engine: RulesEngine,
    track_repo: TrackRepository,
    artist_repo: ArtistRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    rules_engine.ensure_defaults(library_id, now=_NOW)
    track = _make_track(
        library_id,
        track_id,
        file_name="VA - Summer Hits.flac",
        file_path="C:/incoming/VA - Summer Hits.flac",
        bitrate=320,
    )
    track_repo.upsert(track)

    context = rules_engine.build_context(track)
    matches = rules_engine.evaluate(track, context)
    va_matches = [m for m in matches if m.rule_name == "Detect Various Artists"]
    assert len(va_matches) == 1

    updated = rules_engine.apply_matches(track, va_matches, now=_NOW)
    assert updated.artist_id is not None
    artist = artist_repo.get(updated.artist_id)
    assert artist is not None
    assert artist.name == "Various Artists"


def test_archive_mp3_does_not_match_without_lossless_duplicate(
    rules_engine: RulesEngine,
    track_repo: TrackRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    rules_engine.ensure_defaults(library_id, now=_NOW)
    track = _make_track(library_id, track_id, codec="mp3", bitrate=320, file_name="x.mp3")
    track_repo.upsert(track)

    matches = rules_engine.evaluate(track, rules_engine.build_context(track))
    assert all(match.rule_name != "Archive MP3 when FLAC exists" for match in matches)

    with_dup = rules_engine.build_context(track, has_lossless_duplicate=True)
    matches_dup = rules_engine.evaluate(track, with_dup)
    assert any(m.rule_name == "Archive MP3 when FLAC exists" for m in matches_dup)


def test_create_update_delete_rule_crud(rules_engine: RulesEngine, library_id: UUID) -> None:
    rule_id = rules_engine.create_rule(
        RuleCreate(
            library_id=library_id,
            name="Custom genre flag",
            conditions={"field": "genre", "operator": "eq", "value": "Spoken"},
            actions=[
                {
                    "action_type": "flag_review",
                    "parameters": {"reason": "spoken word"},
                }
            ],
            priority=50,
        ),
        now=_NOW,
    )
    assert any(r.id == rule_id for r in rules_engine.list_rules(library_id))
    rules_engine.set_enabled(rule_id, False, now=_NOW)
    rules_engine.delete_rule(rule_id)
    assert all(r.id != rule_id for r in rules_engine.list_rules(library_id))


def test_create_rule_rejects_unknown_action(rules_engine: RulesEngine, library_id: UUID) -> None:
    with pytest.raises(RuleError, match="Unsupported"):
        rules_engine.create_rule(
            RuleCreate(
                library_id=library_id,
                name="Bad",
                conditions={"field": "codec", "operator": "eq", "value": "mp3"},
                actions=[{"action_type": "explode", "parameters": {}}],
            ),
            now=_NOW,
        )


# ---------------------------------------------------------------------------
# Phase 10: move_to_zone actions become real organize_file jobs
# ---------------------------------------------------------------------------


@pytest.fixture
def wired_rules_engine(
    review_repo: ReviewRepository,
    rule_repo: RuleRepository,
    track_repo: TrackRepository,
    artist_repo: ArtistRepository,
    event_bus: EventBus,
    job_queue: JobQueueService,
) -> RulesEngine:
    review_queue = ReviewQueueService(review_repo, track_repo, event_bus)
    return RulesEngine(rule_repo, track_repo, artist_repo, review_queue, event_bus, job_queue)


def _move_rule(rules_engine: RulesEngine, library_id: UUID, zone: str) -> None:
    rules_engine.create_rule(
        RuleCreate(
            library_id=library_id,
            name=f"Move to {zone}",
            conditions={"field": "codec", "operator": "eq", "value": "mp3"},
            actions=[{"action_type": "move_to_zone", "parameters": {"zone": zone}}],
        ),
        now=_NOW,
    )


def test_non_approval_move_to_zone_enqueues_an_organize_job(
    wired_rules_engine: RulesEngine,
    track_repo: TrackRepository,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    _move_rule(wired_rules_engine, library_id, "archive")
    track = _make_track(library_id, track_id, codec="mp3", file_name="x.mp3")
    track_repo.upsert(track)

    matches = wired_rules_engine.evaluate(track, wired_rules_engine.build_context(track))
    wired_rules_engine.apply_matches(track, matches, now=_NOW)

    organize = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
        if job.job_type is JobType.ORGANIZE_FILE
    ]
    assert len(organize) == 1
    assert organize[0].payload == {"track_id": str(track_id), "target_zone": "archive"}


def test_illegal_move_to_zone_parks_a_review_item_instead(
    wired_rules_engine: RulesEngine,
    track_repo: TrackRepository,
    review_repo: ReviewRepository,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    _move_rule(wired_rules_engine, library_id, "library")  # incoming -> library is illegal
    track = _make_track(library_id, track_id, codec="mp3", file_name="x.mp3")
    track_repo.upsert(track)

    matches = wired_rules_engine.evaluate(track, wired_rules_engine.build_context(track))
    wired_rules_engine.apply_matches(track, matches, now=_NOW)

    organize = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
        if job.job_type is JobType.ORGANIZE_FILE
    ]
    assert organize == []
    pending = review_repo.list_by_status(ReviewStatus.PENDING, library_id=library_id)
    assert any(item.review_type is ReviewType.RULE_ACTION for item in pending)


def test_unwired_engine_still_parks_move_intent(
    rules_engine: RulesEngine,
    track_repo: TrackRepository,
    review_repo: ReviewRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    _move_rule(rules_engine, library_id, "archive")
    track = _make_track(library_id, track_id, codec="mp3", file_name="x.mp3")
    track_repo.upsert(track)

    matches = rules_engine.evaluate(track, rules_engine.build_context(track))
    rules_engine.apply_matches(track, matches, now=_NOW)

    pending = review_repo.list_by_status(ReviewStatus.PENDING, library_id=library_id)
    assert any("Rule wants zone 'archive'" in item.title for item in pending)


def test_move_to_zone_with_invalid_zone_raises(
    wired_rules_engine: RulesEngine,
    track_repo: TrackRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    _move_rule(wired_rules_engine, library_id, "vault-of-secrets")
    track = _make_track(library_id, track_id, codec="mp3", file_name="x.mp3")
    track_repo.upsert(track)

    matches = wired_rules_engine.evaluate(track, wired_rules_engine.build_context(track))
    with pytest.raises(RuleError, match="valid zone"):
        wired_rules_engine.apply_matches(track, matches, now=_NOW)

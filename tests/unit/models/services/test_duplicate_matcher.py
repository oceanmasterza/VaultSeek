"""Unit tests for vaultseek.models.services.duplicate_matcher."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.duplicate_group import GroupStatus, MatchType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.services.duplicate_matcher import DuplicateMatcher
from vaultseek.models.services.quality_scorer import DEFAULT_WEIGHTS, QualityScorer

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


def _track(library_id: UUID, **overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": library_id,
        "zone": LibraryZone.INCOMING,
        "file_path": f"C:/incoming/{generate_uuid7()}.mp3",
        "file_name": "track.mp3",
        "file_size": 1024,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
        "codec": "mp3",
        "bitrate": 320,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def matcher() -> DuplicateMatcher:
    return DuplicateMatcher(QualityScorer(DEFAULT_WEIGHTS))


def test_build_group_picks_the_lossless_track_as_best(matcher: DuplicateMatcher) -> None:
    library_id = generate_uuid7()
    mp3 = _track(library_id, codec="mp3", bitrate=320)
    flac = _track(library_id, codec="flac", is_lossless=True, bit_depth=16)

    group, members = matcher.build_group(
        generate_uuid7(), library_id, [mp3, flac], MatchType.FINGERPRINT, detected_at=_NOW
    )

    assert group.best_track_id == flac.id
    assert group.track_count == 2
    assert group.status is GroupStatus.OPEN
    assert group.match_confidence == 0.95
    best = [m for m in members if m.is_best]
    assert len(best) == 1
    assert best[0].track_id == flac.id
    assert best[0].quality_score == 95


def test_build_group_records_quality_score_and_zone_per_member(
    matcher: DuplicateMatcher,
) -> None:
    library_id = generate_uuid7()
    low = _track(library_id, codec="mp3", bitrate=128, zone=LibraryZone.LIBRARY)
    high = _track(library_id, codec="flac", is_lossless=True, bit_depth=24)

    _, members = matcher.build_group(
        generate_uuid7(), library_id, [low, high], MatchType.HASH, detected_at=_NOW
    )

    by_track = {m.track_id: m for m in members}
    assert by_track[low.id].quality_score == 35
    assert by_track[low.id].zone == "library"
    assert by_track[high.id].quality_score == 100
    assert by_track[high.id].zone == "incoming"


def test_build_group_match_confidence_per_tier(matcher: DuplicateMatcher) -> None:
    library_id = generate_uuid7()
    tracks = [_track(library_id), _track(library_id)]

    confidences = {
        tier: matcher.build_group(generate_uuid7(), library_id, tracks, tier, detected_at=_NOW)[
            0
        ].match_confidence
        for tier in (MatchType.HASH, MatchType.FINGERPRINT, MatchType.MBID)
    }

    assert confidences == {
        MatchType.HASH: 1.0,
        MatchType.FINGERPRINT: 0.95,
        MatchType.MBID: 0.90,
    }


def test_build_group_rejects_fewer_than_two_tracks(matcher: DuplicateMatcher) -> None:
    library_id = generate_uuid7()
    with pytest.raises(ValueError, match="at least two"):
        matcher.build_group(
            generate_uuid7(), library_id, [_track(library_id)], MatchType.HASH, detected_at=_NOW
        )

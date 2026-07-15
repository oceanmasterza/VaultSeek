"""Unit tests for musicvault.models.entities.track."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.track import LibraryZone, Track

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_track(**overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": generate_uuid7(),
        "zone": LibraryZone.INCOMING,
        "file_path": "C:/incoming/song.flac",
        "file_name": "song.flac",
        "file_size": 1024,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def test_track_applies_documented_defaults() -> None:
    track = _make_track()

    assert track.album_id is None
    assert track.artist_id is None
    assert track.title is None
    assert track.disc_number == 1
    assert track.is_lossless is False
    assert track.has_embedded_art is False
    assert track.is_corrupt is False
    assert track.needs_review is False


def test_track_is_immutable() -> None:
    track = _make_track()

    with pytest.raises(dataclasses.FrozenInstanceError):
        track.title = "New Title"  # type: ignore[misc]


def test_library_zone_covers_every_documented_zone() -> None:
    expected = {"incoming", "staging", "library", "archive"}

    assert {member.value for member in LibraryZone} == expected


def test_track_accepts_full_audio_metadata() -> None:
    track = _make_track(
        title="Indicator",
        codec="flac",
        bitrate=1000,
        bit_depth=24,
        sample_rate=96000,
        channels=2,
        is_lossless=True,
        quality_score=100,
    )

    assert track.title == "Indicator"
    assert track.codec == "flac"
    assert track.is_lossless is True
    assert track.quality_score == 100

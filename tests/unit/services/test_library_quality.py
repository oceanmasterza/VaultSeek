"""Unit tests for library quality preference checks."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from vaultseek.core.config import AcquisitionConfig
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.library_quality import (
    AlbumHealth,
    album_status_from_tracks,
    track_meets_quality_prefs,
)


def _track(**overrides: object) -> Track:
    now = datetime.now(UTC)
    base: dict[str, object] = {
        "id": uuid4(),
        "library_id": uuid4(),
        "zone": LibraryZone.LIBRARY,
        "file_path": "C:/music/a.flac",
        "file_name": "a.flac",
        "file_size": 1,
        "file_modified": now,
        "created_at": now,
        "updated_at": now,
        "title": "Song",
        "codec": "FLAC",
        "is_lossless": True,
        "bitrate": None,
    }
    base.update(overrides)
    return Track(**base)  # type: ignore[arg-type]


def test_lossless_meets_prefer_lossless() -> None:
    prefs = AcquisitionConfig(prefer_lossless=True, min_bitrate_kbps=192)
    assert track_meets_quality_prefs(_track(), prefs)


def test_low_bitrate_mp3_fails_min() -> None:
    prefs = AcquisitionConfig(prefer_lossless=False, min_bitrate_kbps=192)
    track = _track(
        codec="MP3",
        is_lossless=False,
        bitrate=128,
        file_path="C:/music/a.mp3",
        file_name="a.mp3",
    )
    assert not track_meets_quality_prefs(track, prefs)


def test_album_status_quality_gap() -> None:
    prefs = AcquisitionConfig(prefer_lossless=False, min_bitrate_kbps=192)
    low = _track(
        codec="MP3",
        is_lossless=False,
        bitrate=128,
        file_path="C:/music/a.mp3",
        file_name="a.mp3",
    )
    status = album_status_from_tracks(uuid4(), [low], prefs=prefs, expected_count=1)
    assert status.health is AlbumHealth.COMPLETE_QUALITY_GAP

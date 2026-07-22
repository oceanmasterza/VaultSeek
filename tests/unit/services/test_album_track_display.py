"""Tests for album track display / missing-file health."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from vaultseek.core.config import AcquisitionConfig
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.album_track_display import (
    album_status_for_display,
    build_album_track_rows,
    effective_track_health,
)
from vaultseek.services.library_quality import AlbumHealth, TrackHealth


def _track(*, title: str, path: str, number: int | None = 1) -> Track:
    now = datetime.now(UTC)
    return Track(
        id=uuid4(),
        library_id=uuid4(),
        file_path=path,
        file_name=Path(path).name,
        file_size=1,
        file_modified=now,
        zone=LibraryZone.LIBRARY,
        created_at=now,
        updated_at=now,
        title=title,
        track_number=number,
        bitrate=320,
        codec="mp3",
        is_lossless=False,
    )


def test_missing_file_is_orange_missing_health(tmp_path: Path) -> None:
    prefs = AcquisitionConfig(prefer_lossless=False, min_bitrate_kbps=128)
    missing = _track(title="Gone", path=str(tmp_path / "nope.mp3"))
    assert effective_track_health(missing, prefs) is TrackHealth.MISSING


def test_album_with_missing_files_is_incomplete(tmp_path: Path) -> None:
    prefs = AcquisitionConfig(prefer_lossless=False, min_bitrate_kbps=128)
    present = [
        _track(title="A", path=str(tmp_path / "a.mp3"), number=1),
        _track(title="B", path=str(tmp_path / "b.mp3"), number=2),
    ]
    status = album_status_for_display(uuid4(), present, prefs=prefs, expected_count=2)
    assert status.health is AlbumHealth.INCOMPLETE
    assert status.missing_count == 2


def test_build_rows_includes_missing_placeholders() -> None:
    from vaultseek.models.entities.album import Album

    prefs = AcquisitionConfig(prefer_lossless=False, min_bitrate_kbps=128)
    now = datetime.now(UTC)
    album = Album(
        id=uuid4(),
        title="Celestial Drift",
        sort_title="Celestial Drift",
        created_at=now,
        updated_at=now,
        track_count=2,
    )
    rows = build_album_track_rows(album=album, present=[], prefs=prefs, musicbrainz=None)
    assert len(rows) == 2
    assert all(row.health is TrackHealth.MISSING for row in rows)

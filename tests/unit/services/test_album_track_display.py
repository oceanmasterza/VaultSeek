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


def test_duplicate_files_of_one_track_collapse_but_discs_do_not(tmp_path: Path) -> None:
    from dataclasses import replace

    prefs = AcquisitionConfig(prefer_lossless=False, min_bitrate_kbps=128)
    library_path = tmp_path / "01.flac"
    archive_path = tmp_path / "01.mp3"
    disc_two = tmp_path / "disc2.flac"
    for path in (library_path, archive_path, disc_two):
        path.write_bytes(b"audio")
    library = replace(
        _track(title="Grind", path=str(library_path), number=1),
        zone=LibraryZone.LIBRARY,
        is_lossless=True,
        bitrate=900000,
    )
    archive = replace(
        _track(title="Grind", path=str(archive_path), number=1),
        zone=LibraryZone.ARCHIVE,
        bitrate=320000,
    )
    second_disc = replace(
        _track(title="Grind", path=str(disc_two), number=1),
        disc_number=2,
        zone=LibraryZone.LIBRARY,
        is_lossless=True,
    )

    rows = build_album_track_rows(
        album=None, present=[archive, library, second_disc], prefs=prefs, musicbrainz=None
    )

    assert len(rows) == 2
    assert rows[0].file_path == str(library_path)
    assert rows[1].track_number == 1
    assert rows[1].file_path == str(disc_two)
    status = album_status_for_display(library.id, [archive, library, second_disc], prefs=prefs)
    assert status.present_count == 2


def test_track_zero_and_conflicting_titles_do_not_vanish(tmp_path: Path) -> None:
    from dataclasses import replace

    from vaultseek.services.album_track_display import representative_tracks

    prefs = AcquisitionConfig(prefer_lossless=False, min_bitrate_kbps=128)
    paths = [tmp_path / name for name in ("a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3")]
    for path in paths:
        path.write_bytes(b"audio")
    zero_a = replace(_track(title="Extra A", path=str(paths[0]), number=0))
    zero_b = replace(_track(title="Extra B", path=str(paths[1]), number=0))
    zero_c = replace(_track(title="Extra C", path=str(paths[2]), number=None))
    song_a = replace(_track(title="Song A", path=str(paths[3]), number=1))
    song_b = replace(_track(title="Song B", path=str(paths[4]), number=1))

    reps = representative_tracks([zero_a, zero_b, zero_c, song_a, song_b])
    assert len(reps) == 5
    rows = build_album_track_rows(
        album=None,
        present=[zero_a, zero_b, zero_c, song_a, song_b],
        prefs=prefs,
        musicbrainz=None,
    )
    assert len(rows) == 5
    titles = {row.title for row in rows}
    assert titles == {"Extra A", "Extra B", "Extra C", "Song A", "Song B"}

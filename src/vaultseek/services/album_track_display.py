"""Build album track lists that include missing official tracks for UI display."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from vaultseek.core.config import AcquisitionConfig
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.track import Track
from vaultseek.plugins.builtin.musicbrainz.provider import MusicBrainzProvider, ReleaseTracklist
from vaultseek.services.library_quality import (
    AlbumHealth,
    AlbumStatus,
    TrackHealth,
    track_health,
    track_meets_quality_prefs,
)


@dataclass(frozen=True, slots=True)
class AlbumTrackDisplayRow:
    """One row in the Albums track pane (present or missing placeholder)."""

    title: str
    track_number: int | None
    health: TrackHealth
    zone: str
    file_label: str
    confidence: str
    file_path: str | None
    track: Track | None


def present_track_is_missing_file(track: Track) -> bool:
    path = (track.file_path or "").strip()
    if not path:
        return True
    try:
        return not Path(path).is_file()
    except OSError:
        return True


def effective_track_health(track: Track | None, prefs: AcquisitionConfig) -> TrackHealth:
    if track is None or present_track_is_missing_file(track):
        return TrackHealth.MISSING
    return track_health(track, prefs)


def album_status_for_display(
    album_id: UUID,
    present: list[Track],
    *,
    prefs: AcquisitionConfig,
    expected_count: int | None = None,
    official_tracklist: ReleaseTracklist | None = None,
) -> AlbumStatus:
    """Status using on-disk presence + official/expected track counts."""
    missing_files = sum(1 for track in present if present_track_is_missing_file(track))
    present_ok = [track for track in present if not present_track_is_missing_file(track)]
    quality_gaps = sum(
        1 for track in present_ok if not track_meets_quality_prefs(track, prefs)
    )

    expected = expected_count
    if official_tracklist is not None:
        expected = official_tracklist.track_count

    if expected is not None:
        missing_total = max(0, int(expected) - len(present_ok))
    else:
        missing_total = missing_files

    if missing_total > 0:
        health = AlbumHealth.INCOMPLETE
    elif quality_gaps > 0:
        health = AlbumHealth.COMPLETE_QUALITY_GAP
    elif present_ok:
        health = AlbumHealth.COMPLETE_OK
    else:
        health = AlbumHealth.UNKNOWN

    return AlbumStatus(
        album_id=album_id,
        health=health,
        present_count=len(present_ok),
        expected_count=expected,
        quality_gap_count=quality_gaps,
        missing_count=missing_total,
    )


def build_album_track_rows(
    *,
    album: Album | None,
    present: list[Track],
    prefs: AcquisitionConfig,
    musicbrainz: MusicBrainzProvider | None = None,
) -> list[AlbumTrackDisplayRow]:
    """Return present + missing placeholder rows for the album track table."""
    tracklist = _official_tracklist(album, musicbrainz)
    by_number: dict[int, Track] = {}
    by_title: dict[str, Track] = {}
    for track in present:
        if track.track_number is not None:
            by_number[int(track.track_number)] = track
        if track.title:
            by_title[track.title.casefold().strip()] = track

    rows: list[AlbumTrackDisplayRow] = []
    used: set[UUID] = set()

    if tracklist is not None and tracklist.tracks:
        for official in tracklist.tracks:
            track = None
            if official.number is not None:
                track = by_number.get(int(official.number))
            if track is None and official.title:
                track = by_title.get(official.title.casefold().strip())
            if track is not None:
                used.add(track.id)
            rows.append(
                _row_from_track_or_missing(official.title, official.number, track, prefs)
            )
        # Orphan library tracks not on the official list
        for track in present:
            if track.id not in used:
                rows.append(_row_from_track_or_missing(track.title or "(untitled)", track.track_number, track, prefs))
        return rows

    expected = int(album.track_count) if album is not None and album.track_count > 0 else None
    ordered = sorted(
        present,
        key=lambda t: (t.track_number is None, t.track_number or 0, t.title or ""),
    )
    for track in ordered:
        rows.append(
            _row_from_track_or_missing(
                track.title or "(untitled)", track.track_number, track, prefs
            )
        )

    if expected is not None and expected > len(present):
        present_numbers = {t.track_number for t in present if t.track_number is not None}
        if present_numbers:
            for number in range(1, expected + 1):
                if number in present_numbers:
                    continue
                rows.append(
                    _row_from_track_or_missing(f"Missing track {number}", number, None, prefs)
                )
        else:
            for index in range(1, expected - len(present) + 1):
                rows.append(
                    _row_from_track_or_missing(f"Missing track {index}", None, None, prefs)
                )
    return rows


def _official_tracklist(
    album: Album | None,
    musicbrainz: MusicBrainzProvider | None,
) -> ReleaseTracklist | None:
    if album is None or not album.mbid or musicbrainz is None:
        return None
    try:
        return musicbrainz.lookup_release_tracklist(album.mbid)
    except Exception:
        return None


def _row_from_track_or_missing(
    title: str,
    track_number: int | None,
    track: Track | None,
    prefs: AcquisitionConfig,
) -> AlbumTrackDisplayRow:
    health = effective_track_health(track, prefs)
    if track is None or health is TrackHealth.MISSING:
        return AlbumTrackDisplayRow(
            title=title or "Missing track",
            track_number=track_number,
            health=TrackHealth.MISSING,
            zone="—",
            file_label="(missing)",
            confidence="—",
            file_path=None,
            track=None if track is None or present_track_is_missing_file(track) else track,
        )
    conf = (
        f"{track.overall_confidence:.0%}"
        if track.overall_confidence is not None
        else "—"
    )
    return AlbumTrackDisplayRow(
        title=track.title or title or "(untitled)",
        track_number=track.track_number if track.track_number is not None else track_number,
        health=health,
        zone=track.zone.value,
        file_label=track.file_name or track.file_path or "—",
        confidence=conf,
        file_path=track.file_path,
        track=track,
    )

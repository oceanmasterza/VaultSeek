"""Library quality helpers — preferred codec/bitrate checks and album status."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from vaultseek.core.config import AcquisitionConfig
from vaultseek.models.entities.track import Track


class AlbumHealth(str, Enum):
    """Traffic-light status for an album against quality + completeness prefs."""

    COMPLETE_OK = "complete_ok"
    COMPLETE_QUALITY_GAP = "complete_quality_gap"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


class TrackHealth(str, Enum):
    """Per-track display status."""

    OK = "ok"
    QUALITY_GAP = "quality_gap"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class AlbumStatus:
    album_id: UUID
    health: AlbumHealth
    present_count: int
    expected_count: int | None
    quality_gap_count: int
    missing_count: int


def track_meets_quality_prefs(
    track: Track,
    prefs: AcquisitionConfig,
    *,
    scorer: object | None = None,
) -> bool:
    """Return True when ``track`` satisfies configured quality targets."""
    del scorer  # reserved for future score-floor tuning
    preferred = (prefs.preferred_codec or "").strip()

    if track.is_lossless:
        return True

    if preferred and preferred.casefold() in {"flac", "alac", "wav", "aiff"}:
        return False

    if preferred and (track.codec or "").casefold() != preferred.casefold():
        # Prefer-lossless collections still accept matching lossy at min bitrate.
        if not prefs.prefer_lossless:
            return False

    if prefs.min_bitrate_kbps > 0:
        if not track.bitrate or int(track.bitrate) < int(prefs.min_bitrate_kbps):
            return False
    elif prefs.prefer_lossless:
        # No bitrate floor configured — lossy never satisfies prefer_lossless.
        return False
    return True


def track_health(
    track: Track | None,
    prefs: AcquisitionConfig,
    *,
    missing: bool = False,
) -> TrackHealth:
    if missing or track is None:
        return TrackHealth.MISSING
    if track_meets_quality_prefs(track, prefs):
        return TrackHealth.OK
    return TrackHealth.QUALITY_GAP


def album_status_from_tracks(
    album_id: UUID,
    present: list[Track],
    *,
    prefs: AcquisitionConfig,
    expected_count: int | None = None,
    missing_count: int = 0,
) -> AlbumStatus:
    quality_gaps = sum(
        1 for track in present if not track_meets_quality_prefs(track, prefs)
    )
    if missing_count > 0 or (
        expected_count is not None and len(present) < expected_count
    ):
        health = AlbumHealth.INCOMPLETE
    elif quality_gaps > 0:
        health = AlbumHealth.COMPLETE_QUALITY_GAP
    elif present:
        health = AlbumHealth.COMPLETE_OK
    else:
        health = AlbumHealth.UNKNOWN
    return AlbumStatus(
        album_id=album_id,
        health=health,
        present_count=len(present),
        expected_count=expected_count,
        quality_gap_count=quality_gaps,
        missing_count=missing_count
        if missing_count
        else max(0, (expected_count or 0) - len(present)),
    )

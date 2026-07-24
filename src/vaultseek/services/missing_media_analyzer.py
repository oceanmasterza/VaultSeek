"""MissingMediaAnalyzer — compare library holdings to official release tracklists."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from uuid import UUID

from loguru import logger

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)
from vaultseek.models.entities.track import Track
from vaultseek.plugins.builtin.musicbrainz.provider import MusicBrainzProvider, ReleaseTracklist
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.missing_media_cache import record_scan


class MediaGapKind(str, Enum):
    """Kind of missing media detected against MusicBrainz."""

    MISSING_TRACK = "missing_track"
    INCOMPLETE_ALBUM = "incomplete_album"


@dataclass(frozen=True, slots=True)
class MediaGap:
    """One gap between the library and an official MusicBrainz release."""

    kind: MediaGapKind
    library_id: UUID
    album_id: UUID
    album_title: str
    release_mbid: str
    track_number: int | None = None
    track_title: str | None = None
    recording_mbid: str | None = None
    official_track_count: int | None = None
    library_track_count: int | None = None


class MissingMediaAnalyzer:
    """Skeleton analyzer — finds missing tracks by MB release tracklist.

    Does not create AcquisitionJobs or touch the UI yet.
    """

    def __init__(
        self,
        album_repo: AlbumRepository,
        track_repo: TrackRepository,
        musicbrainz: MusicBrainzProvider,
        artist_repo: ArtistRepository | None = None,
    ) -> None:
        self._albums = album_repo
        self._tracks = track_repo
        self._musicbrainz = musicbrainz
        self._artists = artist_repo

    def create_jobs_for_library(
        self,
        acquisition_engine: AcquisitionEngine,
        library_id: UUID,
        *,
        auto_queue: bool = False,
        preferred_codec: str | None = None,
    ) -> list[AcquisitionJob]:
        """Analyze gaps and create one MISSING_TRACK job per missing track."""
        mb_gaps = self.analyze_library(library_id)
        file_gaps = self.analyze_missing_library_files(library_id, log=False)
        track_gaps = _dedupe_track_gaps(
            [gap for gap in mb_gaps if gap.kind is MediaGapKind.MISSING_TRACK]
            + file_gaps
        )
        if not track_gaps:
            logger.info("Missing-media scan: no missing tracks found")
            return []

        open_keys = {
            _job_track_key(job)
            for job in acquisition_engine.list_jobs(library_id=library_id)
            if job.state not in _TERMINAL_JOB_STATES
        }

        jobs: list[AcquisitionJob] = []
        skipped = 0
        by_album: Counter[str] = Counter()
        for gap in track_gaps:
            artist_name = _artist_name_for_album(self._albums, self._artists, gap.album_id)
            key = (
                (artist_name or "").casefold(),
                (gap.album_title or "").casefold(),
                (gap.track_title or "").casefold(),
            )
            if key in open_keys:
                skipped += 1
                continue
            job = acquisition_engine.create_job(
                library_id=library_id,
                job_type=AcquisitionJobType.MISSING_TRACK,
                artist=artist_name,
                album=gap.album_title,
                title=gap.track_title,
                mb_release_id=gap.release_mbid,
                preferred_codec=preferred_codec,
            )
            if auto_queue:
                job = acquisition_engine.queue(job.id)
            jobs.append(job)
            open_keys.add(key)
            by_album[gap.album_title] += 1

        if not jobs:
            logger.info(
                "Missing-media scan: {} gap(s) already have open acquisition job(s)",
                skipped,
            )
            return []

        album_parts = [
            f"{count} from {title}" for title, count in sorted(by_album.items(), key=lambda item: (-item[1], item[0]))
        ]
        summary = ", ".join(album_parts[:5])
        if len(album_parts) > 5:
            summary += f" (+{len(album_parts) - 5} more albums)"
        queue_note = " (queued for auto-acquire)" if auto_queue else ""
        skip_note = f" (skipped {skipped} already queued)" if skipped else ""
        logger.info(
            "Missing-media scan: created {} job(s) — {}{}{}",
            len(jobs),
            summary,
            queue_note,
            skip_note,
        )
        return jobs

    def analyze_album(
        self, library_id: UUID, album_id: UUID, *, log: bool = True
    ) -> list[MediaGap]:
        """Compare one library album against its MusicBrainz release tracklist."""
        album = self._albums.get(album_id)
        if album is None or not album.mbid:
            return []

        tracklist = self._musicbrainz.lookup_release_tracklist(album.mbid)
        if tracklist is None:
            return []

        library_tracks = self._tracks.list_by_album(library_id, album_id)
        # Only count tracks whose files still exist — Incoming ghosts (DB row
        # left after a failed/partial organize) must not hide official gaps.
        owned_numbers = {
            track.track_number
            for track in library_tracks
            if track.track_number is not None and Path(track.file_path).is_file()
        }
        owned_count = sum(1 for track in library_tracks if Path(track.file_path).is_file())
        gaps = _gaps_for_album(
            library_id=library_id,
            album_id=album_id,
            album_title=album.title,
            release_mbid=album.mbid,
            tracklist=tracklist,
            library_track_numbers=owned_numbers,
            library_track_count=owned_count,
        )
        _log_album_gap_summary(album.title, tracklist.track_count, gaps, log=log)
        return gaps

    def analyze_library(self, library_id: UUID, *, log: bool = True) -> list[MediaGap]:
        """Scan albums linked to ``library_id`` and return all detected gaps."""
        gaps: list[MediaGap] = []
        albums_scanned = 0
        complete_albums = 0
        skipped_no_mbid = 0
        for row in self._albums.list_for_library(library_id):
            if not row.mbid:
                skipped_no_mbid += 1
                continue
            albums_scanned += 1
            album_gaps = self.analyze_album(library_id, row.album_id, log=log)
            if not any(gap.kind is MediaGapKind.MISSING_TRACK for gap in album_gaps):
                complete_albums += 1
            gaps.extend(album_gaps)

        file_gaps = self.analyze_missing_library_files(library_id, log=log)
        gaps.extend(file_gaps)

        track_gaps = _dedupe_track_gaps(
            [gap for gap in gaps if gap.kind is MediaGapKind.MISSING_TRACK]
        )
        # Keep incomplete-album annotations (not deduped with tracks).
        other = [gap for gap in gaps if gap.kind is not MediaGapKind.MISSING_TRACK]
        gaps = other + track_gaps

        incomplete_albums = albums_scanned - complete_albums
        if skipped_no_mbid and log:
            logger.info(
                "Missing-media scan skipped {} album(s) without MusicBrainz id "
                "(identify metadata first, or rely on missing-file detection)",
                skipped_no_mbid,
            )
        if albums_scanned == 0 and not file_gaps:
            if log and skipped_no_mbid == 0:
                logger.info("Missing-media scan: no MusicBrainz-linked albums in library")
        elif not track_gaps:
            if log:
                logger.info(
                    "Missing-media scan complete: {} album(s) checked — all have expected tracks",
                    albums_scanned,
                )
        else:
            if log:
                logger.info(
                    "Missing-media scan complete: {} missing track(s) across {} album(s) "
                    "({} album(s) complete)",
                    len(track_gaps),
                    incomplete_albums,
                    complete_albums,
                )
        record_scan(
            library_id,
            missing_tracks=len(track_gaps),
            incomplete_albums=incomplete_albums,
            albums_scanned=albums_scanned,
            complete_albums=complete_albums,
        )
        return gaps

    def analyze_missing_library_files(
        self, library_id: UUID, *, log: bool = True
    ) -> list[MediaGap]:
        """Tracks whose files are absent on disk (any zone — Library or Incoming).

        Incoming rows left behind after a partial organize are a common case:
        the DB still has the track number, so release-gap analysis alone would
        miss them unless we also scan for dead paths.
        """
        gaps: list[MediaGap] = []
        offset = 0
        while True:
            # zone=None → all zones (Incoming ghosts + Library missing files).
            batch = self._tracks.get_by_library(
                library_id, None, offset=offset, limit=500
            )
            if not batch:
                break
            for track in batch:
                if Path(track.file_path).is_file():
                    continue
                if track.album_id is None:
                    continue
                album = self._albums.get(track.album_id)
                if album is None:
                    continue
                gaps.append(
                    MediaGap(
                        kind=MediaGapKind.MISSING_TRACK,
                        library_id=library_id,
                        album_id=track.album_id,
                        album_title=album.title,
                        release_mbid=album.mbid or "",
                        track_number=track.track_number,
                        track_title=track.title,
                        recording_mbid=track.mb_recording_id,
                    )
                )
            offset += len(batch)
        if gaps and log:
            logger.warning(
                "{} track(s) are missing on disk — queue re-acquisition from "
                "Find music → Find missing songs (or Acquisition → Scan for missing)",
                len(gaps),
            )
        return gaps


def _log_album_gap_summary(
    album_title: str, official_count: int, gaps: list[MediaGap], *, log: bool = True
) -> None:
    if not log:
        return
    track_gaps = [gap for gap in gaps if gap.kind is MediaGapKind.MISSING_TRACK]
    if not track_gaps:
        logger.info(
            "Album has all tracks expected: {} ({}/{})",
            album_title,
            official_count,
            official_count,
        )
        return

    titles = [
        gap.track_title or (f"#{gap.track_number}" if gap.track_number is not None else "unknown")
        for gap in track_gaps
    ]
    preview = ", ".join(titles[:4])
    if len(titles) > 4:
        preview += f" (+{len(titles) - 4} more)"
    owned = official_count - len(track_gaps)
    logger.info(
        "{} track(s) missing from {} ({}/{} owned) — {}",
        len(track_gaps),
        album_title,
        owned,
        official_count,
        preview,
    )


def _gaps_for_album(
    *,
    library_id: UUID,
    album_id: UUID,
    album_title: str,
    release_mbid: str,
    tracklist: ReleaseTracklist,
    library_track_numbers: set[int],
    library_track_count: int,
) -> list[MediaGap]:
    gaps: list[MediaGap] = []
    for official in tracklist.tracks:
        if official.number in library_track_numbers:
            continue
        gaps.append(
            MediaGap(
                kind=MediaGapKind.MISSING_TRACK,
                library_id=library_id,
                album_id=album_id,
                album_title=album_title,
                release_mbid=release_mbid,
                track_number=official.number,
                track_title=official.title,
                recording_mbid=official.recording_mbid,
            )
        )

    if gaps and library_track_count < tracklist.track_count:
        gaps.append(
            MediaGap(
                kind=MediaGapKind.INCOMPLETE_ALBUM,
                library_id=library_id,
                album_id=album_id,
                album_title=album_title,
                release_mbid=release_mbid,
                official_track_count=tracklist.track_count,
                library_track_count=library_track_count,
            )
        )
    return gaps


_TERMINAL_JOB_STATES = frozenset(
    {AcquisitionJobState.COMPLETED, AcquisitionJobState.CANCELLED}
)


def _job_track_key(job: AcquisitionJob) -> tuple[str, str, str]:
    return (
        (job.artist or "").casefold(),
        (job.album or "").casefold(),
        (job.title or "").casefold(),
    )


def _dedupe_track_gaps(gaps: list[MediaGap]) -> list[MediaGap]:
    seen: set[tuple[UUID, int | None, str | None]] = set()
    unique: list[MediaGap] = []
    for gap in gaps:
        key = (gap.album_id, gap.track_number, gap.track_title)
        if key in seen:
            continue
        seen.add(key)
        unique.append(gap)
    return unique


def _artist_name_for_album(
    album_repo: AlbumRepository,
    artist_repo: ArtistRepository | None,
    album_id: UUID,
) -> str | None:
    album = album_repo.get(album_id)
    if album is None or album.album_artist_id is None or artist_repo is None:
        return None
    artist = artist_repo.get(album.album_artist_id)
    return artist.name if artist is not None else None

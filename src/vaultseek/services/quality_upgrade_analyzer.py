"""QualityUpgradeAnalyzer — find library tracks below preferred quality."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from loguru import logger

from vaultseek.core.config import AcquisitionConfig
from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)
from vaultseek.models.entities.track import LibraryZone
from vaultseek.models.services.quality_scorer import DEFAULT_WEIGHTS, QualityScorer
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.library_quality import track_meets_quality_prefs

# Only completed/cancelled exclude a track from new QUALITY_UPGRADE jobs.
# NO_RESULTS / DOWNLOAD_FAILED / VERIFICATION_FAILED / IMPORT_FAILED remain
# open for automation retry — creating a duplicate job would race that path.
_TERMINAL_JOB_STATES = frozenset(
    {
        AcquisitionJobState.COMPLETED,
        AcquisitionJobState.CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class QualityGap:
    """One track that exists but is below the configured quality target."""

    library_id: UUID
    track_id: UUID
    album_id: UUID | None
    artist: str | None
    album: str | None
    title: str | None
    codec: str | None
    bitrate: int | None
    mb_release_id: str | None = None


class QualityUpgradeAnalyzer:
    """Create QUALITY_UPGRADE acquisition jobs for under-quality library tracks."""

    def __init__(
        self,
        track_repo: TrackRepository,
        album_repo: AlbumRepository | None = None,
        artist_repo: ArtistRepository | None = None,
        *,
        quality_scorer: QualityScorer | None = None,
    ) -> None:
        self._tracks = track_repo
        self._albums = album_repo
        self._artists = artist_repo
        self._scorer = quality_scorer or QualityScorer(DEFAULT_WEIGHTS)

    def create_jobs_for_library(
        self,
        acquisition_engine: AcquisitionEngine,
        library_id: UUID,
        prefs: AcquisitionConfig,
        *,
        auto_queue: bool = False,
    ) -> list[AcquisitionJob]:
        gaps = self.analyze_library(library_id, prefs)
        if not gaps:
            logger.info("Quality-upgrade scan: no under-quality tracks found")
            return []

        preferred_codec = (prefs.preferred_codec or "").strip() or None
        if prefs.prefer_lossless and not preferred_codec:
            preferred_codec = "FLAC"

        open_keys, open_track_ids = self._open_upgrade_indexes(acquisition_engine, library_id)

        jobs: list[AcquisitionJob] = []
        skipped = 0
        by_album: Counter[str] = Counter()
        for gap in gaps:
            key = (
                (gap.artist or "").casefold(),
                (gap.album or "").casefold(),
                (gap.title or "").casefold(),
            )
            if key in open_keys or str(gap.track_id) in open_track_ids:
                skipped += 1
                continue
            job = self._create_upgrade_job(
                acquisition_engine,
                gap,
                preferred_codec=preferred_codec,
                auto_queue=auto_queue,
            )
            jobs.append(job)
            open_keys.add(key)
            open_track_ids.add(str(gap.track_id))
            by_album[gap.album or "(unknown album)"] += 1

        if not jobs:
            logger.info(
                "Quality-upgrade scan: {} gap(s) already have open acquisition job(s)",
                skipped,
            )
            return []

        album_parts = [
            f"{count} from {title}"
            for title, count in sorted(by_album.items(), key=lambda item: (-item[1], item[0]))
        ]
        summary = ", ".join(album_parts[:5])
        if len(album_parts) > 5:
            summary += f" (+{len(album_parts) - 5} more albums)"
        queue_note = " (queued for auto-acquire)" if auto_queue else ""
        skip_note = f" (skipped {skipped} already queued)" if skipped else ""
        logger.info(
            "Quality-upgrade scan: created {} job(s) — {}{}{}",
            len(jobs),
            summary,
            queue_note,
            skip_note,
        )
        return jobs

    def create_job_for_track(
        self,
        acquisition_engine: AcquisitionEngine,
        track_id: UUID,
        prefs: AcquisitionConfig,
        *,
        auto_queue: bool = False,
    ) -> AcquisitionJob | None:
        """Create one QUALITY_UPGRADE for a single LIBRARY track when under prefs.

        Library-health ``track_meets_quality_prefs`` is the minimum-acceptable
        bar (e.g. 320 kbps MP3 can still be "OK" on Albums). Scoped post-identify
        upgrades honor the *preferred* target: with ``prefer_lossless``, any
        lossy LIBRARY copy is an upgrade opportunity even when min bitrate is
        already satisfied.
        """
        track = self._tracks.get_by_id(track_id)
        if track is None or track.zone is not LibraryZone.LIBRARY:
            return None
        wants_preferred_lossless = bool(prefs.prefer_lossless) and not track.is_lossless
        if not wants_preferred_lossless and track_meets_quality_prefs(
            track, prefs, scorer=self._scorer
        ):
            return None
        open_keys, open_track_ids = self._open_upgrade_indexes(acquisition_engine, track.library_id)
        if str(track.id) in open_track_ids:
            return None
        gap = self._gap_from_track(track)
        key = (
            (gap.artist or "").casefold(),
            (gap.album or "").casefold(),
            (gap.title or "").casefold(),
        )
        if key in open_keys:
            return None
        preferred_codec = (prefs.preferred_codec or "").strip() or None
        if prefs.prefer_lossless and not preferred_codec:
            preferred_codec = "FLAC"
        return self._create_upgrade_job(
            acquisition_engine,
            gap,
            preferred_codec=preferred_codec,
            auto_queue=auto_queue,
        )

    def analyze_library(self, library_id: UUID, prefs: AcquisitionConfig) -> list[QualityGap]:
        gaps: list[QualityGap] = []
        tracks = self._tracks.get_by_library(library_id, zone=LibraryZone.LIBRARY, limit=100_000)
        for track in tracks:
            if track_meets_quality_prefs(track, prefs, scorer=self._scorer):
                continue
            gaps.append(self._gap_from_track(track))
        return gaps

    def _gap_from_track(self, track: object) -> QualityGap:
        from vaultseek.models.entities.track import Track

        assert isinstance(track, Track)
        artist = None
        album_title = None
        mb_release_id = None
        if track.artist_id is not None and self._artists is not None:
            artist_row = self._artists.get(track.artist_id)
            if artist_row is not None:
                artist = artist_row.name
        if track.album_id is not None and self._albums is not None:
            album_row = self._albums.get(track.album_id)
            if album_row is not None:
                album_title = album_row.title
                mb_release_id = album_row.mbid
        return QualityGap(
            library_id=track.library_id,
            track_id=track.id,
            album_id=track.album_id,
            artist=artist,
            album=album_title,
            title=track.title,
            codec=track.codec,
            bitrate=track.bitrate,
            mb_release_id=mb_release_id,
        )

    def _create_upgrade_job(
        self,
        acquisition_engine: AcquisitionEngine,
        gap: QualityGap,
        *,
        preferred_codec: str | None,
        auto_queue: bool,
    ) -> AcquisitionJob:
        job = acquisition_engine.create_job(
            library_id=gap.library_id,
            job_type=AcquisitionJobType.QUALITY_UPGRADE,
            artist=gap.artist,
            album=gap.album,
            title=gap.title,
            mb_release_id=gap.mb_release_id,
            preferred_codec=preferred_codec,
        )
        job = acquisition_engine.update_extra(
            job.id,
            {
                "source_track_id": str(gap.track_id),
                "source_album_id": str(gap.album_id) if gap.album_id else None,
            },
        )
        if auto_queue:
            job = acquisition_engine.queue(job.id)
        return job

    def _open_upgrade_indexes(
        self, acquisition_engine: AcquisitionEngine, library_id: UUID
    ) -> tuple[set[tuple[str, str, str]], set[str]]:
        open_keys: set[tuple[str, str, str]] = set()
        open_track_ids: set[str] = set()
        for job in acquisition_engine.list_jobs(library_id=library_id):
            if job.job_type is not AcquisitionJobType.QUALITY_UPGRADE:
                continue
            if job.state in _TERMINAL_JOB_STATES:
                continue
            open_keys.add(_job_track_key(job))
            source = job.extra.get("source_track_id") if job.extra else None
            if source:
                open_track_ids.add(str(source))
        return open_keys, open_track_ids


def _job_track_key(job: AcquisitionJob) -> tuple[str, str, str]:
    return (
        (job.artist or "").casefold(),
        (job.album or "").casefold(),
        (job.title or "").casefold(),
    )

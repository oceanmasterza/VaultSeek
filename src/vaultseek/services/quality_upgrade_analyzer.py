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
from vaultseek.models.entities.acquisition_job import AcquisitionJob, AcquisitionJobType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.services.quality_scorer import DEFAULT_WEIGHTS, QualityScorer
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.library_quality import track_meets_quality_prefs


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

        jobs: list[AcquisitionJob] = []
        by_album: Counter[str] = Counter()
        for gap in gaps:
            job = acquisition_engine.create_job(
                library_id=library_id,
                job_type=AcquisitionJobType.QUALITY_UPGRADE,
                artist=gap.artist,
                album=gap.album,
                title=gap.title,
                mb_release_id=gap.mb_release_id,
                preferred_codec=preferred_codec,
            )
            if auto_queue:
                job = acquisition_engine.queue(job.id)
            jobs.append(job)
            by_album[gap.album or "(unknown album)"] += 1

        album_parts = [
            f"{count} from {title}"
            for title, count in sorted(by_album.items(), key=lambda item: (-item[1], item[0]))
        ]
        summary = ", ".join(album_parts[:5])
        if len(album_parts) > 5:
            summary += f" (+{len(album_parts) - 5} more albums)"
        queue_note = " (queued for auto-acquire)" if auto_queue else ""
        logger.info(
            "Quality-upgrade scan: created {} job(s) — {}{}",
            len(jobs),
            summary,
            queue_note,
        )
        return jobs

    def analyze_library(self, library_id: UUID, prefs: AcquisitionConfig) -> list[QualityGap]:
        gaps: list[QualityGap] = []
        tracks = self._tracks.get_by_library(library_id, zone=LibraryZone.LIBRARY, limit=100_000)
        for track in tracks:
            if track_meets_quality_prefs(track, prefs, scorer=self._scorer):
                continue
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
            gaps.append(
                QualityGap(
                    library_id=library_id,
                    track_id=track.id,
                    album_id=track.album_id,
                    artist=artist,
                    album=album_title,
                    title=track.title,
                    codec=track.codec,
                    bitrate=track.bitrate,
                    mb_release_id=mb_release_id,
                )
            )
        return gaps

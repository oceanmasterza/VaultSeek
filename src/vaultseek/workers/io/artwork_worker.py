"""ArtworkWorker — runs `fetch_artwork` jobs through the artwork providers.

I/O-bound (Tier 2 — HTTP + Mutagen + filesystem). Per
docs/architecture/04-service-layer.md the route is *terminal or review*:
nothing is enqueued downstream. Missing / low-resolution covers park
``artwork_missing`` / ``artwork_low_res`` review items only when the
track still needs identity review (or confidence is below threshold);
confident tracks try network + embedded lookup silently.

Selection policy: embedded art is tried first (local). If it meets the
configured minimum resolution, network providers are skipped. Otherwise
Cover Art Archive (and any other network providers) run next. Album mates
reuse an already-fetched album cover without another download.

Storage: image bytes are written once to the application cache
directory (``cache/artwork/<hash[:2]>/<hash>.<ext>``, deduplicated by
SHA-256 through :class:`ArtworkRepository.upsert_image`) and linked to
the track and, when known, its album. ``tracks.has_embedded_art`` is set
whenever the file's own tags contained a usable picture, regardless of
which provider won.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.artwork_repo import ArtworkRepository
from vaultseek.db.repositories.metadata_confidence_repo import MetadataConfidenceRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.artwork import Artwork
from vaultseek.models.entities.job import Job
from vaultseek.models.entities.review_item import ReviewType
from vaultseek.models.entities.track import Track
from vaultseek.models.interfaces.artwork import ArtworkProvider, ArtworkQuery, ArtworkResult
from vaultseek.services.dto.review_dto import ReviewItemCreate
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.review_queue_service import ReviewQueueService

_EXTENSION_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
# Confident tracks: try hard to fetch art, but don't flood Review on miss.
_ARTWORK_REVIEW_THRESHOLD = 0.90


class ArtworkWorker:
    def __init__(
        self,
        track_repo: TrackRepository,
        album_repo: AlbumRepository,
        artwork_repo: ArtworkRepository,
        providers: list[ArtworkProvider],
        review_queue: ReviewQueueService,
        job_queue: JobQueueService,
        *,
        artwork_dir: Path,
        min_width: int = 500,
        min_height: int = 500,
        artist_repo: ArtistRepository | None = None,
        metadata_confidence_repo: MetadataConfidenceRepository | None = None,
    ) -> None:
        self._tracks = track_repo
        self._albums = album_repo
        self._artists = artist_repo
        self._confidence = metadata_confidence_repo
        self._artwork = artwork_repo
        self._providers = sorted(providers, key=lambda p: p.priority)
        self._reviews = review_queue
        self._job_queue = job_queue
        self._artwork_dir = artwork_dir
        self._min_width = min_width
        self._min_height = min_height

    def execute(self, job: Job) -> None:
        track_id = UUID(job.payload["track_id"])
        track = self._tracks.get_by_id(track_id)
        if track is None:
            self._job_queue.mark_failed(job.id, f"Track {track_id} not found")
            return

        now = datetime.now(UTC)

        # Fast path: album (or track) already has cover — link and skip network.
        if self._reuse_existing_cover(track) is not None:
            summary = f"Reused album cover for '{track.file_name}'"
            self._job_queue.mark_completed(
                job.id,
                summary=summary,
                result={"outcome": "saved", "summary": summary, "reused": True},
            )
            return

        query = self._build_query(track)
        chosen, saw_embedded = self._pick_result(query)

        if saw_embedded and not track.has_embedded_art:
            track = replace(track, has_embedded_art=True, updated_at=now)
            self._tracks.upsert(track)

        if chosen is None:
            if _should_park_artwork_review(track):
                self._park_review(
                    job.library_id,
                    track,
                    ReviewType.ARTWORK_MISSING,
                    title=f"No artwork found for '{track.file_name}'",
                    description="No provider returned a cover image for this track.",
                    now=now,
                )
            summary = f"No artwork for '{track.file_name}'"
            self._job_queue.mark_completed(
                job.id,
                summary=summary,
                result={"outcome": "missing", "summary": summary},
            )
            return

        self._store_and_link(track, chosen, now)

        low_res = not self._meets_minimum(chosen)
        if low_res and _should_park_artwork_review(track):
            self._park_review(
                job.library_id,
                track,
                ReviewType.ARTWORK_LOW_RES,
                title=f"Low-resolution artwork for '{track.file_name}'",
                description=(
                    f"Best available cover is {chosen.width}x{chosen.height} px "
                    f"(minimum {self._min_width}x{self._min_height}). "
                    f"Source: {chosen.source}."
                ),
                now=now,
            )
        outcome = "low_res" if low_res else "saved"
        summary = (
            f"{'Low-res cover' if low_res else 'Cover saved'} "
            f"({chosen.source}, {chosen.width}x{chosen.height}) for '{track.file_name}'"
        )
        self._job_queue.mark_completed(
            job.id,
            summary=summary,
            result={
                "outcome": outcome,
                "summary": summary,
                "source": chosen.source,
                "width": chosen.width,
                "height": chosen.height,
            },
        )

    def _reuse_existing_cover(self, track: Track) -> UUID | None:
        """Link an already-fetched album/track cover without network I/O."""
        if self._artwork.has_artwork_for_track(track.id):
            existing = self._artwork.get_primary_for_track(track.id)
            return existing.id if existing is not None else None
        if track.album_id is None:
            return None
        album_art = self._artwork.get_primary_for_album(track.album_id)
        if album_art is None:
            return None
        self._artwork.link_track(track.id, album_art.id)
        return album_art.id

    def _build_query(self, track: Track) -> ArtworkQuery:
        mb_release_id: str | None = None
        mb_release_group_id: str | None = None
        discogs_id: str | None = None
        album_title: str | None = None
        artist_name: str | None = None
        if track.album_id is not None:
            album = self._albums.get(track.album_id)
            if album is not None:
                mb_release_id = album.mbid
                mb_release_group_id = album.release_group_mbid
                discogs_id = album.discogs_id
                album_title = album.title
                if album.album_artist_id is not None and self._artists is not None:
                    album_artist = self._artists.get(album.album_artist_id)
                    if album_artist is not None:
                        artist_name = album_artist.name
        if artist_name is None and track.artist_id is not None and self._artists is not None:
            artist = self._artists.get(track.artist_id)
            if artist is not None:
                artist_name = artist.name
        if self._confidence is not None and (artist_name is None or album_title is None):
            for field in self._confidence.list_for_track(track.id):
                if artist_name is None and field.field == "artist" and field.value:
                    artist_name = str(field.value)
                elif album_title is None and field.field == "album" and field.value:
                    album_title = str(field.value)
        return ArtworkQuery(
            file_path=track.file_path,
            mb_release_id=mb_release_id,
            mb_release_group_id=mb_release_group_id,
            mb_recording_id=track.mb_recording_id,
            discogs_id=discogs_id,
            artist=artist_name,
            album=album_title,
        )

    def _pick_result(self, query: ArtworkQuery) -> tuple[ArtworkResult | None, bool]:
        """Return ``(chosen result, embedded art was seen)``.

        Embedded art is probed first (local, free). If it meets the
        configured minimum resolution we skip network providers entirely.
        Otherwise network providers run in priority order; the first
        result meeting the minimum wins, else the largest candidate.
        """
        candidates: list[ArtworkResult] = []
        saw_embedded = False

        embedded_providers = [p for p in self._providers if p.provider_id == "embedded_art"]
        network_providers = [p for p in self._providers if p.provider_id != "embedded_art"]

        for provider in embedded_providers:
            result = provider.fetch(query)
            if result is None:
                continue
            saw_embedded = True
            candidates.append(result)
            if self._meets_minimum(result):
                return result, saw_embedded

        for provider in network_providers:
            result = provider.fetch(query)
            if result is None:
                continue
            candidates.append(result)
            if self._meets_minimum(result):
                return result, saw_embedded

        if not candidates:
            return None, saw_embedded
        best = max(candidates, key=lambda result: result.width * result.height)
        return best, saw_embedded

    def _meets_minimum(self, result: ArtworkResult) -> bool:
        return result.width >= self._min_width and result.height >= self._min_height

    def _store_and_link(self, track: Track, result: ArtworkResult, now: datetime) -> None:
        content_hash = hashlib.sha256(result.data).hexdigest()
        existing = self._artwork.get_by_content_hash(content_hash)
        if existing is not None:
            artwork_id = existing.id
        else:
            file_path = self._write_image(content_hash, result)
            artwork_id = self._artwork.upsert_image(
                Artwork(
                    id=generate_uuid7(),
                    content_hash_sha256=content_hash,
                    source=result.source,
                    mime_type=result.mime_type,
                    width=result.width,
                    height=result.height,
                    file_size=len(result.data),
                    file_path=str(file_path),
                    created_at=now,
                    source_id=result.source_id,
                )
            )
        self._artwork.link_track(track.id, artwork_id)
        if track.album_id is not None:
            self._artwork.link_album(track.album_id, artwork_id)

    def _write_image(self, content_hash: str, result: ArtworkResult) -> Path:
        extension = _EXTENSION_BY_MIME.get(result.mime_type, ".img")
        path = self._artwork_dir / content_hash[:2] / f"{content_hash}{extension}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(result.data)
        return path

    def _park_review(
        self,
        library_id: UUID,
        track: Track,
        review_type: ReviewType,
        *,
        title: str,
        description: str,
        now: datetime,
    ) -> None:
        self._reviews.create_item(
            ReviewItemCreate(
                library_id=library_id,
                review_type=review_type,
                title=title,
                track_id=track.id,
                album_id=track.album_id,
                description=description,
            ),
            now=now,
        )


def _should_park_artwork_review(track: Track) -> bool:
    """Park artwork issues only when identity itself still needs attention.

    High-confidence tracks keep flowing through the pipeline; a missing
    cover is logged by completing the job without a Review row.
    """
    if track.needs_review:
        return True
    if track.overall_confidence is None:
        return True
    return track.overall_confidence < _ARTWORK_REVIEW_THRESHOLD

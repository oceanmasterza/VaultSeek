"""ArtworkWorker — runs `fetch_artwork` jobs through the artwork providers.

I/O-bound (Tier 2 — HTTP + Mutagen + filesystem). Per
docs/architecture/04-service-layer.md the route is *terminal or review*:
nothing is enqueued downstream, but a missing or low-resolution cover
parks an ``artwork_missing`` / ``artwork_low_res`` review item.

Selection policy (no algorithm is documented — this is the
implementation's fill-in): providers are asked in priority order
(Cover Art Archive 10 > Embedded 50) and the first result meeting the
configured minimum resolution wins. If nothing meets the bar, the
largest-area candidate is still stored — a small cover beats no cover —
and an ``artwork_low_res`` item is parked so the user can upgrade it.

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

from musicvault.db.repositories.album_repo import AlbumRepository
from musicvault.db.repositories.artwork_repo import ArtworkRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.artwork import Artwork
from musicvault.models.entities.job import Job
from musicvault.models.entities.review_item import ReviewType
from musicvault.models.entities.track import Track
from musicvault.models.interfaces.artwork import ArtworkProvider, ArtworkQuery, ArtworkResult
from musicvault.services.dto.review_dto import ReviewItemCreate
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.review_queue_service import ReviewQueueService

_EXTENSION_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


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
    ) -> None:
        self._tracks = track_repo
        self._albums = album_repo
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
        query = self._build_query(track)
        chosen, saw_embedded = self._pick_result(query)

        if saw_embedded and not track.has_embedded_art:
            track = replace(track, has_embedded_art=True, updated_at=now)
            self._tracks.upsert(track)

        if chosen is None:
            self._park_review(
                job.library_id,
                track,
                ReviewType.ARTWORK_MISSING,
                title=f"No artwork found for '{track.file_name}'",
                description="No provider returned a cover image for this track.",
                now=now,
            )
            self._job_queue.mark_completed(job.id)
            return

        self._store_and_link(track, chosen, now)

        if not self._meets_minimum(chosen):
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
        self._job_queue.mark_completed(job.id)

    def _build_query(self, track: Track) -> ArtworkQuery:
        mb_release_id: str | None = None
        mb_release_group_id: str | None = None
        album_title: str | None = None
        if track.album_id is not None:
            album = self._albums.get(track.album_id)
            if album is not None:
                mb_release_id = album.mbid
                mb_release_group_id = album.release_group_mbid
                album_title = album.title
        return ArtworkQuery(
            file_path=track.file_path,
            mb_release_id=mb_release_id,
            mb_release_group_id=mb_release_group_id,
            mb_recording_id=track.mb_recording_id,
            album=album_title,
        )

    def _pick_result(self, query: ArtworkQuery) -> tuple[ArtworkResult | None, bool]:
        """Return ``(chosen result, embedded art was seen)``.

        Every provider is asked (the embedded probe is a cheap local
        read and is needed to keep ``has_embedded_art`` accurate even
        when a network provider wins). The first priority-ordered result
        meeting the minimum resolution is chosen; otherwise the
        largest-area candidate is kept.
        """
        candidates: list[ArtworkResult] = []
        saw_embedded = False
        for provider in self._providers:
            result = provider.fetch(query)
            if result is None:
                continue
            if result.source == "embedded_art":
                saw_embedded = True
            candidates.append(result)
        if not candidates:
            return None, saw_embedded
        for result in candidates:
            if self._meets_minimum(result):
                return result, saw_embedded
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

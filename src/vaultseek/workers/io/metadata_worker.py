"""MetadataWorker — runs `identify_metadata` jobs through MetadataArbitrator.

I/O-bound (Tier 2 — HTTP + Mutagen). When overall confidence is below
threshold, sets ``tracks.needs_review`` and creates a review item via
ReviewQueueService. Always enqueues ``detect_duplicates`` (Phase 9),
which chains to ``evaluate_rules`` once grouping is done — so rules see
the real ``has_lossless_duplicate`` flag. Phase 11 adds a parallel
``fetch_artwork`` enqueue (docs/architecture/04-service-layer.md worker
table: MetadataWorker enqueues both) — artwork is a terminal side
branch that never gates organizing.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.artwork_repo import ArtworkRepository
from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.metadata_confidence_repo import MetadataConfidenceRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.artist import Artist
from vaultseek.models.entities.job import Job, JobType
from vaultseek.models.entities.track import Track
from vaultseek.models.interfaces.metadata import FingerprintData
from vaultseek.models.value_objects.field_confidence import FieldConfidence
from vaultseek.models.value_objects.file_identity import FileIdentity
from vaultseek.services.folder_trust import FolderTrustService
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.metadata_arbitrator import MetadataArbitrator
from vaultseek.services.review_queue_service import ReviewQueueService


class MetadataWorker:
    def __init__(
        self,
        track_repo: TrackRepository,
        file_identity_repo: FileIdentityRepository,
        metadata_confidence_repo: MetadataConfidenceRepository,
        arbitrator: MetadataArbitrator,
        job_queue: JobQueueService,
        review_queue: ReviewQueueService,
        *,
        artist_repo: ArtistRepository | None = None,
        album_repo: AlbumRepository | None = None,
        artwork_repo: ArtworkRepository | None = None,
        folder_trust: FolderTrustService | None = None,
        fingerprint_mode: str = "all",
    ) -> None:
        self._tracks = track_repo
        self._identities = file_identity_repo
        self._confidence = metadata_confidence_repo
        self._arbitrator = arbitrator
        self._job_queue = job_queue
        self._reviews = review_queue
        self._artists = artist_repo
        self._albums = album_repo
        self._artwork = artwork_repo
        self._folder_trust = folder_trust
        self._fingerprint_mode = fingerprint_mode

    def execute(self, job: Job) -> None:
        track_id = UUID(job.payload["track_id"])
        track = self._tracks.get_by_id(track_id)
        if track is None:
            self._job_queue.mark_failed(job.id, f"Track {track_id} not found")
            return

        identity = self._identities.get(track_id)
        fingerprint = _fingerprint_from_identity(identity)
        force_acoustid = (
            self._fingerprint_mode == "sample"
            and self._folder_trust is not None
            and not self._folder_trust.is_trusted_for_track(track)
            and fingerprint is not None
        )
        result = self._arbitrator.resolve(
            track, fingerprint, force_acoustid=force_acoustid
        )

        now = datetime.now(UTC)
        updated = _apply_fields(
            track,
            result.fields,
            result.overall_confidence,
            result.needs_review,
            now,
            artist_repo=self._artists,
            album_repo=self._albums,
        )
        self._tracks.upsert(updated)
        self._confidence.upsert_fields(track_id, list(result.fields.values()), now=now)

        if identity is not None:
            acoustid_id = _winner_str(result.fields, "acoustid_id")
            acoustid_score = _winner_float(result.fields, "acoustid_score")
            if acoustid_id is not None or acoustid_score is not None:
                next_id = acoustid_id if acoustid_id is not None else identity.acoustid_id
                next_score = (
                    acoustid_score if acoustid_score is not None else identity.acoustid_score
                )
                identity = replace(identity, acoustid_id=next_id, acoustid_score=next_score)
                self._identities.upsert(identity)

        if result.needs_review:
            self._reviews.create_from_arbitration(
                library_id=job.library_id,
                track_id=track_id,
                result=result,
                now=now,
            )

        if self._fingerprint_mode == "sample" and self._folder_trust is not None:
            self._folder_trust.try_trust_after_identify(
                updated, result, identity, now=now
            )

        self._job_queue.enqueue(
            JobType.DETECT_DUPLICATES,
            job.library_id,
            {"track_id": str(track_id)},
            parent_job_id=job.id,
            now=now,
        )
        if not self._album_already_has_cover(updated):
            self._job_queue.enqueue(
                JobType.FETCH_ARTWORK,
                job.library_id,
                {"track_id": str(track_id)},
                parent_job_id=job.id,
                now=now,
            )
        summary = _identify_summary(updated, result.fields, result.overall_confidence, result.needs_review)
        self._job_queue.mark_completed(
            job.id,
            summary=summary,
            result={
                "outcome": "needs_review" if result.needs_review else "matched",
                "summary": summary,
                "confidence": result.overall_confidence,
                "needs_review": result.needs_review,
                "artist_id": str(updated.artist_id) if updated.artist_id else None,
                "album_id": str(updated.album_id) if updated.album_id else None,
            },
        )

    def _album_already_has_cover(self, track: Track) -> bool:
        """Skip enqueueing artwork when the album cover was already fetched."""
        if self._artwork is None or track.album_id is None:
            return False
        return self._artwork.get_primary_for_album(track.album_id) is not None


def _identify_summary(
    track: Track,
    fields: dict[str, FieldConfidence],
    confidence: float,
    needs_review: bool,
) -> str:
    title = _winner_str(fields, "title") or track.title or track.file_name
    artist = _winner_str(fields, "artist")
    album = _winner_str(fields, "album")
    if artist and album:
        summary = f"Identified: {artist} — {album} / {title} ({confidence:.0%})"
    elif artist:
        summary = f"Identified: {artist} / {title} ({confidence:.0%})"
    else:
        summary = f"Identified: {title} ({confidence:.0%})"
    if needs_review:
        summary += " — needs review"
    return summary


def _fingerprint_from_identity(identity: FileIdentity | None) -> FingerprintData | None:
    if identity is None or identity.fingerprint_data is None:
        return None
    duration = identity.fingerprint_duration if identity.fingerprint_duration is not None else 0.0
    return FingerprintData(
        fingerprint_data=identity.fingerprint_data,
        duration_seconds=duration,
        fingerprint_hash=identity.fingerprint_hash,
        acoustid_id=identity.acoustid_id,
        acoustid_score=identity.acoustid_score,
    )


def _apply_fields(
    track: Track,
    fields: dict[str, FieldConfidence],
    overall_confidence: float,
    needs_review: bool,
    now: datetime,
    *,
    artist_repo: ArtistRepository | None = None,
    album_repo: AlbumRepository | None = None,
) -> Track:
    updates: dict[str, object] = {
        "overall_confidence": overall_confidence,
        "needs_review": needs_review,
        "updated_at": now,
    }
    if "title" in fields:
        updates["title"] = fields["title"].value
    if "year" in fields and isinstance(fields["year"].value, int):
        updates["year"] = fields["year"].value
    if "genre" in fields:
        updates["genre"] = fields["genre"].value
    if "composer" in fields:
        updates["composer"] = fields["composer"].value
    if "track_number" in fields and isinstance(fields["track_number"].value, int):
        updates["track_number"] = fields["track_number"].value
    if "mb_recording_id" in fields and isinstance(fields["mb_recording_id"].value, str):
        updates["mb_recording_id"] = fields["mb_recording_id"].value

    artist_id = track.artist_id
    if artist_repo is not None:
        artist_name = _winner_str(fields, "artist")
        if artist_name:
            artist_id = _ensure_artist(artist_repo, artist_name, now=now)
            updates["artist_id"] = artist_id

    if album_repo is not None:
        album_title = _winner_str(fields, "album")
        if album_title:
            year = updates.get("year")
            album_year = year if isinstance(year, int) else track.year
            updates["album_id"] = _ensure_album(
                album_repo,
                album_title,
                album_artist_id=artist_id if isinstance(artist_id, UUID) else track.artist_id,
                year=album_year,
                mbid=_winner_str(fields, "mb_release_id"),
                release_group_mbid=_winner_str(fields, "mb_release_group_id"),
                now=now,
            )

    return replace(track, **updates)  # type: ignore[arg-type]


def _ensure_artist(artists: ArtistRepository, name: str, *, now: datetime) -> UUID:
    existing = artists.list_by_name(name)
    if existing:
        return existing[0].id
    artist = Artist(
        id=generate_uuid7(),
        name=name,
        sort_name=name,
        created_at=now,
        updated_at=now,
    )
    artists.create(artist)
    return artist.id


def _ensure_album(
    albums: AlbumRepository,
    title: str,
    *,
    album_artist_id: UUID | None,
    year: int | None,
    mbid: str | None,
    release_group_mbid: str | None,
    now: datetime,
) -> UUID:
    if mbid:
        existing_mb = albums.get_by_mbid(mbid)
        if existing_mb is not None:
            return existing_mb.id
    if album_artist_id is not None:
        for album in albums.list_by_artist(album_artist_id):
            if album.title == title:
                # Back-fill MBIDs when a later identify finds them.
                if (mbid and not album.mbid) or (
                    release_group_mbid and not album.release_group_mbid
                ):
                    updated = replace(
                        album,
                        mbid=mbid or album.mbid,
                        release_group_mbid=release_group_mbid or album.release_group_mbid,
                        updated_at=now,
                    )
                    albums.create(updated)
                return album.id
    album = Album(
        id=generate_uuid7(),
        title=title,
        sort_title=title,
        created_at=now,
        updated_at=now,
        album_artist_id=album_artist_id,
        year=year,
        mbid=mbid,
        release_group_mbid=release_group_mbid,
    )
    albums.create(album)
    return album.id


def _winner_str(fields: dict[str, FieldConfidence], name: str) -> str | None:
    item = fields.get(name)
    if item is None or not isinstance(item.value, str):
        return None
    value = item.value.strip()
    return value or None


def _winner_float(fields: dict[str, FieldConfidence], name: str) -> float | None:
    item = fields.get(name)
    if item is None:
        return None
    if isinstance(item.value, (int, float)):
        return float(item.value)
    return None

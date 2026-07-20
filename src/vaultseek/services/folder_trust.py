"""FolderTrustService — confirm album folders so siblings can skip fingerprinting.

When ``fingerprint_mode=sample``, Chromaprint runs until a folder meets all
four gates, then remaining files identify from tags only:

1. At least ``fingerprint_sample_min`` songs in the folder were confirmed
   via AcoustID (fingerprint) against the same MusicBrainz release
2. Embedded tags for every audio file match that official tracklist
3. Filenames look consistent with track number + title
4. Audio file count equals the official release track count
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.repositories.trusted_folder_repo import TrustedFolder, TrustedFolderRepository
from vaultseek.models.entities.job import JobStatus, JobType
from vaultseek.models.entities.track import Track
from vaultseek.models.interfaces.metadata import ArbitrationResult, MetadataQuery
from vaultseek.models.value_objects.file_identity import FileIdentity
from vaultseek.plugins.builtin.local_tags.provider import LocalTagsProvider
from vaultseek.plugins.builtin.musicbrainz.provider import (
    MusicBrainzProvider,
    OfficialTrack,
    ReleaseTracklist,
)
from vaultseek.services.job_queue_service import JobQueueService

_AUDIO_EXTENSIONS = frozenset(
    {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".ape", ".wv"}
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_folder_path(file_path: str | Path) -> str:
    """Stable folder key for trust lookups (Windows-safe)."""
    path = Path(file_path)
    parent = path.parent if path.suffix else path
    try:
        resolved = parent.resolve()
    except OSError:
        resolved = parent
    return str(resolved).replace("/", "\\").casefold()


class FolderTrustService:
    def __init__(
        self,
        trusted_repo: TrustedFolderRepository,
        track_repo: TrackRepository,
        file_identity_repo: FileIdentityRepository,
        album_repo: AlbumRepository,
        musicbrainz: MusicBrainzProvider,
        job_queue: JobQueueService,
        job_repo: JobRepository,
        *,
        sample_min: int = 3,
        local_tags: LocalTagsProvider | None = None,
    ) -> None:
        self._trusted = trusted_repo
        self._tracks = track_repo
        self._identities = file_identity_repo
        self._albums = album_repo
        self._musicbrainz = musicbrainz
        self._job_queue = job_queue
        self._jobs = job_repo
        self._sample_min = max(1, sample_min)
        self._local_tags = local_tags or LocalTagsProvider()
        self._tracklist_cache: dict[str, ReleaseTracklist | None] = {}

    def is_trusted(self, library_id: UUID, folder_path: str) -> bool:
        return self._trusted.is_trusted(library_id, normalize_folder_path(folder_path))

    def is_trusted_for_track(self, track: Track) -> bool:
        return self.is_trusted(track.library_id, Path(track.file_path).parent)

    def try_trust_after_identify(
        self,
        track: Track,
        result: ArbitrationResult,
        identity: FileIdentity | None,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return True when the track's folder becomes newly trusted."""
        folder = normalize_folder_path(track.file_path)
        if self._trusted.is_trusted(track.library_id, folder):
            return False
        if not _acoustid_confirmed(result, identity):
            return False
        release_mbid = _release_mbid_from_result(result, track, self._albums)
        if release_mbid is None:
            return False

        tracklist = self._tracklist(release_mbid)
        if tracklist is None or tracklist.track_count == 0:
            return False

        audio_files = _list_audio_files(Path(track.file_path).parent)
        if len(audio_files) != tracklist.track_count:
            return False
        if not _all_files_match_tracklist(audio_files, tracklist, self._local_tags):
            return False

        confirmed = self._count_fingerprint_confirmations(
            track.library_id, audio_files, release_mbid, tracklist
        )
        if confirmed < self._sample_min:
            return False

        resolved_at = now or datetime.now(UTC)
        self._trusted.upsert(
            TrustedFolder(
                library_id=track.library_id,
                folder_path=folder,
                release_mbid=release_mbid,
                official_track_count=tracklist.track_count,
                sample_confirmed=confirmed,
                trusted_at=resolved_at,
            )
        )
        self._cancel_pending_fingerprints(track.library_id, audio_files)
        return True

    def _tracklist(self, release_mbid: str) -> ReleaseTracklist | None:
        if release_mbid not in self._tracklist_cache:
            self._tracklist_cache[release_mbid] = self._musicbrainz.lookup_release_tracklist(
                release_mbid
            )
        return self._tracklist_cache[release_mbid]

    def _count_fingerprint_confirmations(
        self,
        library_id: UUID,
        audio_files: list[Path],
        release_mbid: str,
        tracklist: ReleaseTracklist,
    ) -> int:
        recording_ids = {
            track.recording_mbid for track in tracklist.tracks if track.recording_mbid
        }
        count = 0
        for path in audio_files:
            row = self._tracks.get_by_path(str(path))
            if row is None or row.library_id != library_id:
                # Also try normalized path variants.
                row = self._tracks.get_by_path(str(path.resolve())) if path.exists() else None
            if row is None:
                continue
            identity = self._identities.get(row.id)
            if identity is None or not identity.acoustid_id:
                continue
            if row.mb_recording_id and row.mb_recording_id in recording_ids:
                count += 1
                continue
            if row.album_id is not None:
                album = self._albums.get(row.album_id)
                if album is not None and album.mbid == release_mbid:
                    count += 1
        return count

    def _cancel_pending_fingerprints(self, library_id: UUID, audio_files: list[Path]) -> None:
        path_keys = {_path_key(path) for path in audio_files}
        pending = self._jobs.list_by_status(
            JobStatus.PENDING, library_id=library_id, limit=50_000
        )
        for job in pending:
            if job.job_type is not JobType.FINGERPRINT_FILE:
                continue
            track_id_raw = job.payload.get("track_id")
            if not isinstance(track_id_raw, str):
                continue
            try:
                track_id = UUID(track_id_raw)
            except ValueError:
                continue
            track = self._tracks.get_by_id(track_id)
            if track is None:
                continue
            if _path_key(Path(track.file_path)) in path_keys:
                self._job_queue.cancel(job.id)


def _acoustid_confirmed(result: ArbitrationResult, identity: FileIdentity | None) -> bool:
    if any(item.provider_id == "acoustid" for item in result.provider_results):
        return True
    return identity is not None and bool(identity.acoustid_id)


def _release_mbid_from_result(
    result: ArbitrationResult,
    track: Track,
    albums: AlbumRepository,
) -> str | None:
    field = result.fields.get("mb_release_id")
    if field is not None and isinstance(field.value, str) and field.value.strip():
        return field.value.strip()
    if track.album_id is not None:
        album = albums.get(track.album_id)
        if album is not None and album.mbid:
            return album.mbid
    return None


def _list_audio_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in _AUDIO_EXTENSIONS),
        key=lambda path: path.name.casefold(),
    )


def _all_files_match_tracklist(
    audio_files: list[Path],
    tracklist: ReleaseTracklist,
    local_tags: LocalTagsProvider,
) -> bool:
    by_number = {track.number: track for track in tracklist.tracks}
    used_numbers: set[int] = set()
    for path in audio_files:
        tags = local_tags.lookup_by_tags(MetadataQuery(file_path=str(path), file_name=path.name))
        if tags is None:
            return False
        values = {field.field: field.value for field in tags.fields}
        album = values.get("album")
        title = values.get("title")
        track_number = values.get("track_number")
        if not isinstance(album, str) or not isinstance(title, str):
            return False
        if not _titles_match(album, tracklist.title):
            return False
        if not isinstance(track_number, int) or track_number not in by_number:
            return False
        if track_number in used_numbers:
            return False
        used_numbers.add(track_number)
        official = by_number[track_number]
        if not _titles_match(title, official.title):
            return False
        if not _filename_looks_correct(path.name, track_number, official):
            return False
    return len(used_numbers) == len(audio_files)


def _filename_looks_correct(file_name: str, track_number: int, official: OfficialTrack) -> bool:
    stem = Path(file_name).stem.casefold()
    if str(track_number) not in stem and f"{track_number:02d}" not in stem:
        return False
    title_tokens = [token for token in _normalize(official.title).split() if len(token) > 2]
    if not title_tokens:
        return True
    # Require most distinctive title tokens to appear in the filename.
    hits = sum(1 for token in title_tokens if token in _normalize(stem))
    return hits >= max(1, (len(title_tokens) + 1) // 2)


def _titles_match(left: str, right: str) -> bool:
    a = _normalize(left)
    b = _normalize(right)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _normalize(value: str) -> str:
    return _NON_ALNUM.sub(" ", value.casefold()).strip()


def _path_key(path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return str(resolved).replace("/", "\\").casefold()

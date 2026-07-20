"""ScannerWorker — directory walking for the `scan_directory` job.

I/O-bound (Tier 2 — see docs/architecture/08-performance.md, "Three-Tier
Worker Model"), so unlike :mod:`vaultseek.workers.cpu.hash_worker` this
runs on a `ThreadPoolExecutor` thread and can hold live repository/writer
references directly — threads share the parent process's memory, so
nothing needs to cross a pickling boundary here.

`Job.payload` contract for `scan_directory`: ``{"directory": str,
"zone": str, "force": bool?}`` — ``force=True`` re-queues every audio
file even when size/mtime match a prior scan (dashboard “Force rescan”).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from loguru import logger

from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.db.writer import DatabaseWriter, WriteDTO
from vaultseek.models.entities.job import Job, JobType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.job_queue_service import JobQueueService

_AUDIO_EXTENSIONS = frozenset(
    {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".ape", ".wv"}
)
"""Not enumerated anywhere in the architecture docs — a reasonable,
documented fill-in covering the formats already named elsewhere in the
codebase (FLAC/MP3/AAC in `QualityScorer`) plus the other common lossy
and lossless container/codec extensions a real library would contain."""


class ScannerWorker:
    """Executes one `scan_directory` job: walks the directory, and for
    every audio file whose size/mtime differ from what's already
    recorded (or that's never been seen before), upserts a `Track` row
    and enqueues a `hash_file` job for it.
    """

    def __init__(
        self,
        track_repo: TrackRepository,
        file_identity_repo: FileIdentityRepository,
        database_writer: DatabaseWriter,
        job_queue: JobQueueService,
    ) -> None:
        self._track_repo = track_repo
        self._file_identity_repo = file_identity_repo
        self._writer = database_writer
        self._job_queue = job_queue

    def execute(self, job: Job) -> None:
        directory = Path(job.payload["directory"])
        zone = LibraryZone(job.payload["zone"])
        force = bool(job.payload.get("force"))

        if not directory.is_dir():
            self._job_queue.mark_failed(job.id, f"{directory} is not a directory")
            return

        try:
            audio_files = list(_iter_audio_files(directory))
        except OSError as exc:
            self._job_queue.mark_failed(job.id, f"Failed to list {directory}: {exc}")
            return

        found = 0
        skipped = 0
        queued = 0
        for path in audio_files:
            found += 1
            outcome = self._process_file(job, path, zone, force=force)
            if outcome == "skipped":
                skipped += 1
            elif outcome == "queued":
                queued += 1

        summary = (
            f"Scan {'(force) ' if force else ''}complete: "
            f"{found} audio file(s), {queued} queued for processing, "
            f"{skipped} unchanged skipped."
        )
        self._job_queue.mark_completed(
            job.id,
            summary=summary,
            result={
                "summary": summary,
                "files_found": found,
                "files_queued": queued,
                "files_skipped": skipped,
                "force": force,
            },
        )

    def _process_file(
        self, job: Job, path: Path, zone: LibraryZone, *, force: bool
    ) -> str:
        try:
            stat = path.stat()
        except OSError as exc:
            logger.warning("Skipping {} — could not stat it: {}", path, exc)
            return "error"

        existing = self._track_repo.get_by_path(str(path))
        track_id = existing.id if existing is not None else generate_uuid7()
        file_modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

        if existing is not None and not force:
            identity = self._file_identity_repo.get(track_id)
            if identity is not None and identity.matches_current_file(
                file_size=stat.st_size, file_modified=file_modified
            ):
                return "skipped"

        # Watch rescans every ~30s; don't stack duplicate hash jobs for the same track.
        if self._job_queue.has_active_for_track(JobType.HASH_FILE, job.library_id, track_id):
            return "skipped"

        tech = _probe_audio_tech(path)
        track = _build_track(
            existing,
            track_id=track_id,
            library_id=job.library_id,
            zone=zone,
            path=path,
            file_size=stat.st_size,
            file_modified=file_modified,
            tech=tech,
        )
        self._writer.submit(
            WriteDTO(table="tracks", operation="upsert", rows=[TrackRepository.to_row(track)])
        )
        payload: dict[str, object] = {
            "track_id": str(track_id),
            "file_path": str(path),
        }
        if force:
            payload["force"] = True
        self._job_queue.enqueue(
            JobType.HASH_FILE,
            job.library_id,
            payload,
            parent_job_id=job.id,
        )
        return "queued"


def _iter_audio_files(directory: Path) -> Iterator[Path]:
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in _AUDIO_EXTENSIONS:
            yield path


def _build_track(
    existing: Track | None,
    *,
    track_id: UUID,
    library_id: UUID,
    zone: LibraryZone,
    path: Path,
    file_size: int,
    file_modified: datetime,
    tech: dict[str, object] | None = None,
) -> Track:
    """A brand-new file gets a fresh `Track`; a re-scanned known file
    keeps every previously arbitrated field (title, artist, quality
    score, ...) and only refreshes what the filesystem can tell us —
    `TrackRepository.upsert_batch`'s underlying `batch_upsert` overwrites
    *every* column on conflict, so silently dropping the other fields
    here would erase metadata a later phase's MetadataWorker already
    filled in.
    """
    tech = tech or {}
    if existing is not None:
        updates: dict[str, object] = {
            "file_path": str(path),
            "file_name": path.name,
            "file_size": file_size,
            "file_modified": file_modified,
            "updated_at": datetime.now(UTC),
        }
        for key, value in tech.items():
            if value is not None and getattr(existing, key, None) is None:
                updates[key] = value
        return replace(existing, **updates)  # type: ignore[arg-type]
    now = datetime.now(UTC)
    return Track(
        id=track_id,
        library_id=library_id,
        zone=zone,
        file_path=str(path),
        file_name=path.name,
        file_size=file_size,
        file_modified=file_modified,
        created_at=now,
        updated_at=now,
        duration_ms=tech.get("duration_ms") if isinstance(tech.get("duration_ms"), int) else None,
        bitrate=tech.get("bitrate") if isinstance(tech.get("bitrate"), int) else None,
        sample_rate=tech.get("sample_rate") if isinstance(tech.get("sample_rate"), int) else None,
        channels=tech.get("channels") if isinstance(tech.get("channels"), int) else None,
        bit_depth=tech.get("bit_depth") if isinstance(tech.get("bit_depth"), int) else None,
        codec=tech.get("codec") if isinstance(tech.get("codec"), str) else None,
        is_lossless=bool(tech.get("is_lossless", False)),
    )


def _probe_audio_tech(path: Path) -> dict[str, object]:
    """Read container/codec technical fields via Mutagen (local — no network)."""
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return {}
    try:
        audio = MutagenFile(path)
    except Exception:
        return {}
    if audio is None or getattr(audio, "info", None) is None:
        return {}
    info = audio.info
    out: dict[str, object] = {}
    length = getattr(info, "length", None)
    if isinstance(length, (int, float)) and length > 0:
        out["duration_ms"] = int(round(float(length) * 1000))
    bitrate = getattr(info, "bitrate", None)
    if isinstance(bitrate, (int, float)) and bitrate > 0:
        out["bitrate"] = int(bitrate)
    sample_rate = getattr(info, "sample_rate", None)
    if isinstance(sample_rate, (int, float)) and sample_rate > 0:
        out["sample_rate"] = int(sample_rate)
    channels = getattr(info, "channels", None)
    if isinstance(channels, int) and channels > 0:
        out["channels"] = channels
    bits = getattr(info, "bits_per_sample", None) or getattr(info, "bit_depth", None)
    if isinstance(bits, int) and bits > 0:
        out["bit_depth"] = bits
    suffix = path.suffix.lower().lstrip(".")
    if suffix:
        out["codec"] = suffix
    out["is_lossless"] = suffix in {"flac", "wav", "aiff", "aif", "wv", "ape"}
    return out

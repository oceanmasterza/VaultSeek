"""ImportPipeline — post-verification hand-off into the library pipeline.

Stages verified files into the library Incoming zone and enqueues the
existing scan → hash → identify → organize → artwork → media-server path
via JobQueueService. See docs/ARCHITECTURE.md (Import Pipeline).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from loguru import logger

from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJobState
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.track import LibraryZone
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_labels import job_label, maybe_log_album_fully_acquired
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.verification_engine import VerificationResult


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Outcome of importing verified download paths into the library."""

    ok: bool
    job_id: UUID
    local_paths: tuple[Path, ...]
    steps_completed: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    staged_paths: tuple[Path, ...] = ()
    enqueued_job_ids: tuple[UUID, ...] = ()


class ImportPipeline:
    """Stage verified files into Incoming and enqueue scan / optional sync."""

    def __init__(
        self,
        acquisition_engine: AcquisitionEngine,
        *,
        library_repo: LibraryRepository | None = None,
        job_queue: JobQueueService | None = None,
    ) -> None:
        self._engine = acquisition_engine
        self._libraries = library_repo
        self._jobs = job_queue

    def run(
        self,
        job_id: UUID,
        local_paths: list[Path] | tuple[Path, ...] | None = None,
        *,
        refresh_media_servers: bool = False,
    ) -> ImportResult:
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        if job.state is not AcquisitionJobState.IMPORTING:
            raise ValueError(
                f"AcquisitionJob {job_id} must be IMPORTING "
                f"(current: {job.state.value}); verify before import"
            )

        if local_paths is not None:
            paths = [Path(p) for p in local_paths]
        else:
            raw = job.extra.get("local_paths") or job.extra.get("download_paths") or []
            paths = [Path(p) for p in raw]

        steps: list[str] = []
        failures: list[str] = []
        notes: list[str] = []
        staged: list[Path] = []
        enqueued: list[UUID] = []

        if not paths:
            failures.append("no_local_paths")
        else:
            steps.append("paths_accepted")
            for path in paths:
                if not path.exists() or not path.is_file():
                    failures.append(f"missing_file:{path.name}")
                else:
                    steps.append(f"verified_source:{path.name}")

        if not failures and self._libraries is not None and self._jobs is not None:
            library = self._libraries.get(job.library_id)
            if library is None:
                failures.append("library_not_found")
            else:
                incoming = Path(library.incoming_path)
                dest_root = incoming / "vaultseek-acquisition" / str(job_id)
                try:
                    dest_root.mkdir(parents=True, exist_ok=True)
                    for path in paths:
                        dest = _unique_dest(dest_root, path.name)
                        shutil.copy2(path, dest)
                        staged.append(dest)
                        steps.append(f"staged:{dest.name}")
                        # Clean VaultSeek-owned Nicotine drop folder originals.
                        try:
                            nicotine_root = incoming / "vaultseek-nicotine" / str(job_id)
                            if path.resolve().is_relative_to(nicotine_root.resolve()):
                                path.unlink(missing_ok=True)
                                steps.append(f"cleaned_source:{path.name}")
                        except (OSError, ValueError):
                            pass
                    steps.append("incoming_staged")
                    logger.info(
                        "Staged {} file(s) for {} into {}",
                        len(staged),
                        job_label(job),
                        dest_root,
                    )

                    scan_id = self._jobs.enqueue(
                        JobType.SCAN_DIRECTORY,
                        job.library_id,
                        {
                            "directory": str(dest_root),
                            "zone": LibraryZone.INCOMING.value,
                        },
                    )
                    enqueued.append(scan_id)
                    steps.append("scan_enqueued")
                    notes.append(f"scan_job={scan_id}")

                    # Artwork / organize run after scan→hash→identify (existing chain).
                    steps.append("organize_handoff")
                    steps.append("artwork_handoff")
                    notes.append("organize_artwork_via_scan_pipeline")

                    if refresh_media_servers:
                        sync_id = self._jobs.enqueue(
                            JobType.SYNC_MEDIA_SERVER,
                            job.library_id,
                            {},
                        )
                        enqueued.append(sync_id)
                        steps.append("media_server_refresh_enqueued")
                        notes.append(f"sync_job={sync_id}")
                    else:
                        notes.append("media_server_refresh_skipped")
                except OSError as exc:
                    failures.append(f"stage_failed:{exc}")
        elif not failures:
            # Skeleton path when container wiring is incomplete (unit tests).
            steps.append("incoming_stage_deferred")
            steps.append("organize_handoff_deferred")
            steps.append("artwork_handoff_deferred")
            if refresh_media_servers:
                steps.append("media_server_refresh_deferred")
                notes.append("media_server_refresh_deferred")
            else:
                notes.append("media_server_refresh_skipped")

        ok = not failures
        if ok:
            self._engine.advance(
                job_id,
                AcquisitionJobState.COMPLETED,
                note=f"imported {len(staged or paths)} file(s)",
            )
            loaded = self._engine.get(job_id)
            if loaded is not None:
                file_count = len(staged or paths)
                logger.info(
                    "Acquired {} — imported {} file(s) to Incoming",
                    job_label(loaded),
                    file_count,
                )
                maybe_log_album_fully_acquired(self._engine, loaded)
        else:
            self._engine.advance(
                job_id,
                AcquisitionJobState.IMPORT_FAILED,
                note=";".join(failures[:5]),
            )

        return ImportResult(
            ok=ok,
            job_id=job_id,
            local_paths=tuple(paths),
            steps_completed=tuple(steps),
            failures=tuple(failures),
            notes=tuple(notes),
            staged_paths=tuple(staged),
            enqueued_job_ids=tuple(enqueued),
        )

    def run_after_verification(self, verification: VerificationResult) -> ImportResult:
        """Import only when verification succeeded (mandatory gate)."""
        if not verification.ok:
            raise ValueError(
                f"Refusing import for job {verification.job_id}: verification failed"
            )
        return self.run(verification.job_id, verification.local_paths)


def _unique_dest(folder: Path, name: str) -> Path:
    dest = folder / name
    if not dest.exists():
        return dest
    stem = Path(name).stem
    suffix = Path(name).suffix
    index = 1
    while True:
        candidate = folder / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1

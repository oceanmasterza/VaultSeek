"""ImportPipeline — post-verification library intake wiring stubs.

Reuses MusicVault organize / artwork / media-server workers in later phases.
See docs/ARCHITECTURE.md (Import Pipeline).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from vaultseek.models.entities.acquisition_job import AcquisitionJobState
from vaultseek.services.acquisition_engine import AcquisitionEngine
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


class ImportPipeline:
    """Skeleton import pipeline — records paths and completes the job.

    Real organize / artwork / fingerprint / media-server refresh are deferred;
    this wires AcquisitionJob IMPORTING → COMPLETED (or IMPORT_FAILED).
    """

    def __init__(self, acquisition_engine: AcquisitionEngine) -> None:
        self._engine = acquisition_engine

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

        if not paths:
            failures.append("no_local_paths")
        else:
            steps.append("paths_accepted")
            for path in paths:
                if not path.exists() or not path.is_file():
                    failures.append(f"missing_file:{path.name}")
                else:
                    steps.append(f"staged:{path.name}")

        # Wiring stubs for MusicVault pipeline stages.
        steps.append("metadata_stub")
        steps.append("artwork_stub")
        steps.append("organize_stub")
        steps.append("library_update_stub")
        if refresh_media_servers:
            steps.append("media_server_refresh_stub")
            notes.append("media_server_refresh_deferred")
        else:
            notes.append("media_server_refresh_skipped")

        ok = not failures
        if ok:
            self._engine.advance(
                job_id,
                AcquisitionJobState.COMPLETED,
                note=f"imported {len(paths)} file(s)",
            )
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
        )

    def run_after_verification(self, verification: VerificationResult) -> ImportResult:
        """Import only when verification succeeded (mandatory gate)."""
        if not verification.ok:
            raise ValueError(
                f"Refusing import for job {verification.job_id}: verification failed"
            )
        return self.run(verification.job_id, verification.local_paths)

"""VerificationEngine — mandatory pre-import checks for downloads.

See docs/ARCHITECTURE.md (Verification Pipeline) and ADR-0005.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from vaultseek.models.entities.acquisition_job import AcquisitionJob, AcquisitionJobState
from vaultseek.services.acquisition_engine import AcquisitionEngine


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Outcome of mandatory verification before import."""

    ok: bool
    job_id: UUID
    local_paths: tuple[Path, ...]
    checks_passed: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class VerificationEngine:
    """Skeleton verification engine — path/metadata heuristics only.

    Live fingerprint / MusicBrainz release checks are deferred; this still
    advances AcquisitionJob through VERIFYING so the pipeline is wired.
    """

    def __init__(self, acquisition_engine: AcquisitionEngine) -> None:
        self._engine = acquisition_engine

    def verify(
        self,
        job_id: UUID,
        local_paths: list[Path] | tuple[Path, ...] | None = None,
    ) -> VerificationResult:
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        paths = self._resolve_paths(job, local_paths)

        if job.state is AcquisitionJobState.DOWNLOADING:
            self._engine.advance(
                job_id,
                AcquisitionJobState.VERIFYING,
                note=f"{len(paths)} path(s)",
            )
            job = self._engine.get(job_id)
            assert job is not None
        elif job.state is not AcquisitionJobState.VERIFYING:
            raise ValueError(
                f"AcquisitionJob {job_id} must be DOWNLOADING or VERIFYING "
                f"(current: {job.state.value})"
            )

        passed: list[str] = []
        failures: list[str] = []
        notes: list[str] = []

        if not paths:
            failures.append("no_local_paths")
        else:
            passed.append("paths_provided")

        for path in paths:
            if not path.exists():
                failures.append(f"missing_file:{path.name}")
            elif not path.is_file():
                failures.append(f"not_a_file:{path.name}")
            elif path.stat().st_size <= 0:
                failures.append(f"empty_file:{path.name}")
            else:
                passed.append(f"file_present:{path.name}")

        _meta_ok, meta_notes = self._check_metadata_hints(job, paths)
        notes.extend(meta_notes)
        if _meta_ok:
            passed.append("metadata_hints")
        elif paths:
            notes.append("metadata_hints_soft")

        # Duplicate + fingerprint + release: stubs until workers are wired.
        passed.append("duplicate_check_stub")
        notes.append("fingerprint_deferred")
        if job.mb_release_id:
            passed.append("release_id_present")
            notes.append(f"mb_release_id={job.mb_release_id}")
        else:
            notes.append("release_verification_deferred")

        ok = not failures
        if ok:
            self._engine.advance(
                job_id,
                AcquisitionJobState.IMPORTING,
                note=",".join(passed[:5]) or "verified",
            )
        else:
            self._engine.advance(
                job_id,
                AcquisitionJobState.VERIFICATION_FAILED,
                note=";".join(failures[:5]),
            )

        return VerificationResult(
            ok=ok,
            job_id=job_id,
            local_paths=tuple(paths),
            checks_passed=tuple(passed),
            failures=tuple(failures),
            notes=tuple(notes),
        )

    def _resolve_paths(
        self,
        job: AcquisitionJob,
        local_paths: list[Path] | tuple[Path, ...] | None,
    ) -> list[Path]:
        if local_paths is not None:
            return [Path(p) for p in local_paths]
        raw = job.extra.get("local_paths") or job.extra.get("download_paths") or []
        return [Path(p) for p in raw]

    def _check_metadata_hints(
        self,
        job: AcquisitionJob,
        paths: list[Path],
    ) -> tuple[bool, list[str]]:
        if not paths or not (job.title or job.album or job.artist):
            return True, ["metadata_hints_skipped"]
        joined = " ".join(p.stem.casefold() for p in paths)
        parent = " ".join(p.parent.name.casefold() for p in paths)
        haystack = f"{joined} {parent}"
        notes: list[str] = []
        hits = 0
        for label, value in (
            ("title", job.title),
            ("album", job.album),
            ("artist", job.artist),
        ):
            if not value:
                continue
            if value.casefold() in haystack:
                hits += 1
                notes.append(f"hint_match:{label}")
            else:
                notes.append(f"hint_miss:{label}")
        expected = sum(1 for v in (job.title, job.album, job.artist) if v)
        return hits > 0 or expected == 0, notes

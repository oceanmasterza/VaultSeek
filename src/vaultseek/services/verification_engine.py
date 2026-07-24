"""VerificationEngine — mandatory pre-import checks for downloads.

See docs/ARCHITECTURE.md (Verification Pipeline) and ADR-0005.
Uses existing MusicVault-style services (local tags, content hash,
DuplicateRepository, optional Chromaprint) without inventing new APIs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJob, AcquisitionJobState
from vaultseek.models.entities.duplicate_group import MatchType
from vaultseek.models.interfaces.fingerprint import FingerprintProvider
from vaultseek.models.interfaces.metadata import MetadataQuery
from vaultseek.services.acquisition_engine import AcquisitionEngine

# Sentinel track id so DuplicateRepository.find_matching_track_ids excludes nothing.
_NO_TRACK = UUID(int=0)


class _TagsLookup(Protocol):
    def lookup_by_tags(self, query: MetadataQuery) -> object | None: ...


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
    """Pre-import checks: paths, tags, content-hash duplicates, optional fingerprint."""

    def __init__(
        self,
        acquisition_engine: AcquisitionEngine,
        *,
        duplicate_repo: DuplicateRepository | None = None,
        tags_provider: _TagsLookup | None = None,
        fingerprint_provider: FingerprintProvider | None = None,
        reject_duplicates: bool = True,
    ) -> None:
        self._engine = acquisition_engine
        self._duplicates = duplicate_repo
        self._tags = tags_provider
        self._fingerprint = fingerprint_provider
        self._reject_duplicates = reject_duplicates

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

        present: list[Path] = []
        for path in paths:
            if not path.exists():
                failures.append(f"missing_file:{path.name}")
            elif not path.is_file():
                failures.append(f"not_a_file:{path.name}")
            elif path.stat().st_size <= 0:
                failures.append(f"empty_file:{path.name}")
            else:
                passed.append(f"file_present:{path.name}")
                present.append(path)

        # Sibling album downloads often list paths that Nicotine never finished.
        # Verify against files that actually landed; missing siblings are notes.
        if present and failures and all(
            f.startswith("missing_file:") or f.startswith("not_a_file:") for f in failures
        ):
            notes.extend(failures)
            failures.clear()
            notes.append("ignored_missing_sibling_paths")

        meta_ok, meta_notes = self._check_metadata(job, present)
        notes.extend(meta_notes)
        if meta_ok:
            passed.append("metadata_check")
        elif present:
            notes.append("metadata_check_soft")

        dup_passed, dup_failures, dup_notes = self._check_duplicates(job, present)
        passed.extend(dup_passed)
        failures.extend(dup_failures)
        notes.extend(dup_notes)

        fp_passed, fp_failures, fp_notes = self._check_fingerprints(job, present)
        passed.extend(fp_passed)
        failures.extend(fp_failures)
        notes.extend(fp_notes)

        if job.mb_release_id:
            passed.append("release_id_present")
            notes.append(f"mb_release_id={job.mb_release_id}")
        else:
            notes.append("release_id_absent")

        # Missing-track acquisition: hash/fingerprint already in the library means
        # the gap is filled (or we re-downloaded an owned copy). Treat as success
        # (COMPLETED / already_owned) — never park Review for duplicates.
        already_owned = bool(failures) and all(f.startswith("duplicate_") for f in failures)
        if already_owned:
            notes.extend(failures)
            notes.append("already_owned_duplicate")
            failures.clear()
            passed.append("already_owned")

        ok = not failures
        if ok:
            if already_owned or "already_owned" in passed:
                self._engine.update_extra(
                    job_id,
                    {
                        "outcome_code": "already_owned",
                        "outcome_label": "Already in library (duplicate match)",
                    },
                )
                self._engine.advance(
                    job_id,
                    AcquisitionJobState.COMPLETED,
                    note="already_owned",
                )
            else:
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
            local_paths=tuple(present if present else paths),
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

    def _check_metadata(
        self,
        job: AcquisitionJob,
        paths: list[Path],
    ) -> tuple[bool, list[str]]:
        """Prefer embedded tags via LocalTagsProvider; fall back to path hints."""
        if not paths:
            return True, ["metadata_skipped"]

        if self._tags is not None:
            notes: list[str] = []
            hits = 0
            expected = 0
            for path in paths:
                result = self._tags.lookup_by_tags(
                    MetadataQuery(
                        file_path=str(path),
                        file_name=path.name,
                        artist=job.artist,
                        album=job.album,
                        title=job.title,
                    )
                )
                if result is None:
                    notes.append(f"tags_unavailable:{path.name}")
                    continue
                fields = {f.field: f.value for f in getattr(result, "fields", ())}
                for label, wanted in (
                    ("title", job.title),
                    ("album", job.album),
                    ("artist", job.artist),
                ):
                    if not wanted:
                        continue
                    expected += 1
                    got = fields.get(label)
                    if got is not None and str(got).casefold() == wanted.casefold():
                        hits += 1
                        notes.append(f"tag_match:{label}")
                    else:
                        notes.append(f"tag_miss:{label}")
            if expected == 0:
                return True, notes or ["metadata_no_expectations"]
            return hits > 0, notes

        return self._check_metadata_hints(job, paths)

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

    def _check_duplicates(
        self,
        job: AcquisitionJob,
        paths: list[Path],
    ) -> tuple[list[str], list[str], list[str]]:
        passed: list[str] = []
        failures: list[str] = []
        notes: list[str] = []

        if self._duplicates is None:
            notes.append("duplicate_check_deferred")
            return passed, failures, notes

        if not paths:
            return passed, failures, notes

        any_hash_dup = False
        for path in paths:
            digest = _sha256_file(path)
            matches = self._duplicates.find_matching_track_ids(
                job.library_id,
                _NO_TRACK,
                content_hash=digest,
            )
            hash_hits = matches.get(MatchType.HASH) or []
            if hash_hits:
                any_hash_dup = True
                msg = f"duplicate_hash:{path.name}:{hash_hits[0]}"
                if self._reject_duplicates:
                    failures.append(msg)
                else:
                    notes.append(msg)
            else:
                passed.append(f"hash_unique:{path.name}")
                notes.append(f"content_hash={digest[:12]}")

        if not any_hash_dup:
            passed.append("duplicate_hash_clear")
        return passed, failures, notes

    def _check_fingerprints(
        self,
        job: AcquisitionJob,
        paths: list[Path],
    ) -> tuple[list[str], list[str], list[str]]:
        passed: list[str] = []
        failures: list[str] = []
        notes: list[str] = []

        if self._fingerprint is None:
            notes.append("fingerprint_deferred")
            return passed, failures, notes

        if not paths:
            return passed, failures, notes

        computed = 0
        for path in paths:
            try:
                result = self._fingerprint.fingerprint_file(path)
            except (OSError, RuntimeError) as exc:
                notes.append(f"fingerprint_unavailable:{path.name}:{exc}")
                continue
            computed += 1
            passed.append(f"fingerprint_ok:{path.name}")
            if self._duplicates is None:
                continue
            matches = self._duplicates.find_matching_track_ids(
                job.library_id,
                _NO_TRACK,
                fingerprint_hash=result.fingerprint_hash,
            )
            fp_hits = matches.get(MatchType.FINGERPRINT) or []
            if fp_hits:
                msg = f"duplicate_fingerprint:{path.name}:{fp_hits[0]}"
                if self._reject_duplicates:
                    failures.append(msg)
                else:
                    notes.append(msg)
            else:
                passed.append(f"fingerprint_unique:{path.name}")

        if computed:
            passed.append("fingerprint_check")
        else:
            notes.append("fingerprint_soft_skip")
        return passed, failures, notes


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()

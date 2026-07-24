"""AcquisitionWorkflow — thin verify→import hand-off after downloads."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from loguru import logger

from vaultseek.models.entities.acquisition_job import AcquisitionJobState
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_labels import job_label
from vaultseek.services.download_manager import DownloadManager
from vaultseek.services.import_pipeline import ImportPipeline, ImportResult
from vaultseek.services.verification_engine import VerificationEngine, VerificationResult


class AcquisitionWorkflow:
    """Skeleton end-to-end hand-off: complete download → verify → import."""

    def __init__(
        self,
        acquisition_engine: AcquisitionEngine,
        download_manager: DownloadManager,
        verification_engine: VerificationEngine,
        import_pipeline: ImportPipeline,
    ) -> None:
        self._engine = acquisition_engine
        self._downloads = download_manager
        self._verify = verification_engine
        self._import = import_pipeline

    def finish_download(
        self,
        job_id: UUID,
        local_paths: list[Path] | tuple[Path, ...] | None = None,
        *,
        auto_import: bool = True,
    ) -> tuple[VerificationResult | None, ImportResult | None]:
        """Mark download complete, verify, optionally import.

        Returns ``(None, None)`` when the download is still in progress or failed.
        """
        self._downloads.complete(job_id, local_paths)
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        if job.state is not AcquisitionJobState.VERIFYING:
            return None, None

        paths = local_paths
        if paths is None:
            raw = job.extra.get("local_paths") or []
            paths = [Path(p) for p in raw]

        verification = self._verify.verify(job_id, paths)
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        if job.state is AcquisitionJobState.COMPLETED:
            logger.info(
                "Already owned — marked complete for {} ({})",
                job_label(job),
                "; ".join(verification.notes[:2]) or "duplicate",
            )
            return verification, None

        if job.state is not AcquisitionJobState.VERIFYING and job.state is not AcquisitionJobState.IMPORTING:
            if not verification.ok:
                logger.warning(
                    "Verification failed for {}: {}",
                    job_label(job),
                    "; ".join(verification.failures[:3]) or "checks failed",
                )
            return verification, None

        if verification.ok:
            logger.info(
                "Verified {} — {} file(s) passed pre-import checks",
                job_label(job),
                len(verification.local_paths),
            )
        else:
            logger.warning(
                "Verification failed for {}: {}",
                job_label(job),
                "; ".join(verification.failures[:3]) or "checks failed",
            )
        if not auto_import or not verification.ok:
            return verification, None
        imported = self._import.run_after_verification(verification)
        return verification, imported

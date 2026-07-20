"""ReportWorker — runs `generate_report` jobs through ReportService.

I/O-bound (Tier 2 — DB aggregates + filesystem write). Terminal job
(docs/architecture/04-service-layer.md): nothing is enqueued downstream.
"""

from __future__ import annotations

from vaultseek.core.exceptions import ReportError
from vaultseek.models.entities.job import Job
from vaultseek.services.dto.report_dto import ReportFormat, ReportRequest, ReportType
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.report_service import ReportService


class ReportWorker:
    def __init__(self, report_service: ReportService, job_queue: JobQueueService) -> None:
        self._reports = report_service
        self._job_queue = job_queue

    def execute(self, job: Job) -> None:
        try:
            report_type = ReportType(job.payload.get("report_type", ReportType.LIBRARY_SUMMARY))
            report_format = ReportFormat(job.payload.get("format", ReportFormat.JSON))
        except ValueError as exc:
            self._job_queue.mark_failed(job.id, f"Invalid report payload: {exc}")
            return

        output_path = job.payload.get("output_path")
        if output_path is not None and not isinstance(output_path, str):
            self._job_queue.mark_failed(job.id, "output_path must be a string or null")
            return

        try:
            result = self._reports.generate(
                ReportRequest(
                    library_id=job.library_id,
                    report_type=report_type,
                    format=report_format,
                    output_path=output_path,
                )
            )
        except ReportError as exc:
            self._job_queue.mark_failed(job.id, str(exc))
            return

        self._job_queue.mark_completed(job.id)
        # Result path is available to callers via the job's completed status;
        # GUI Phase 14 can surface details from a follow-up query.
        _ = result

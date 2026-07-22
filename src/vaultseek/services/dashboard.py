"""Dashboard snapshot — collection health + live pipeline transparency.

Assembles the numbers the Dashboard page needs without the GUI importing
repositories directly beyond the container façade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from vaultseek.core.container import Container
from vaultseek.models.entities.acquisition_job import AcquisitionJobState
from vaultseek.models.entities.job import Job, JobStatus, JobType
from vaultseek.models.entities.track import LibraryZone

# Left-to-right processing journey (Beets / MusicBrainz Picard mental model).
# Third element is a JobQueue JobType value, or None for non-job stages
# (review gate, acquisition engine).
PIPELINE_STAGES: tuple[tuple[str, str, str | None], ...] = (
    ("acquire", "Acquiring", None),  # AcquisitionJob engine — before library Discover
    ("scan", "Discover", JobType.SCAN_DIRECTORY.value),
    ("hash", "Hash", JobType.HASH_FILE.value),
    ("fingerprint", "Fingerprint", JobType.FINGERPRINT_FILE.value),
    ("identify", "Identify", JobType.IDENTIFY_METADATA.value),
    ("review", "Review", None),  # human gate — not a job type
    ("duplicates", "Duplicates", JobType.DETECT_DUPLICATES.value),
    ("rules", "Rules", JobType.EVALUATE_RULES.value),
    ("organize", "Organize", JobType.ORGANIZE_FILE.value),
    ("artwork", "Artwork", JobType.FETCH_ARTWORK.value),
    ("sync", "Sync", JobType.SYNC_MEDIA_SERVER.value),
)


@dataclass(frozen=True, slots=True)
class PipelineStageStat:
    key: str
    label: str
    backlog: int  # pending + running for this stage (or review pending)
    running: int
    is_active: bool  # backlog > 0 or running > 0
    is_bottleneck: bool


@dataclass(frozen=True, slots=True)
class AcquisitionDashboardStat:
    """Acquisition job counts for the dashboard."""

    total: int = 0
    active: int = 0
    waiting_for_user: int = 0
    in_progress: int = 0
    failed: int = 0
    completed: int = 0


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    """Everything the Dashboard needs for one refresh."""

    has_library: bool
    library_name: str = ""
    # KPI strip
    track_count: int = 0
    pending_jobs: int = 0
    running_jobs: int = 0
    failed_jobs: int = 0
    review_pending: int = 0
    completed_today: int = 0
    open_duplicates: int = 0
    # Collection
    tracks_by_zone: dict[str, int] = field(default_factory=dict)
    confidence: dict[str, int] = field(default_factory=dict)
    average_confidence: float | None = None
    # Pipeline
    stages: tuple[PipelineStageStat, ...] = ()
    job_backlog_by_type: dict[str, int] = field(default_factory=dict)
    review_by_type: dict[str, int] = field(default_factory=dict)
    # Live work
    running_job_rows: tuple[Job, ...] = ()
    failed_job_rows: tuple[Job, ...] = ()
    top_failures: tuple[tuple[str, str, int], ...] = ()
    insight: str = ""
    last_scan_summary: str = ""
    processing_report: str = ""
    acquisition: AcquisitionDashboardStat = field(default_factory=AcquisitionDashboardStat)


def build_dashboard_snapshot(
    container: Container, library_id: UUID | None
) -> DashboardSnapshot:
    if library_id is None:
        return DashboardSnapshot(
            has_library=False,
            insight="Create a library in Settings, then scan Incoming to start the pipeline.",
        )

    library = container.library_repo.get(library_id)
    name = library.name if library is not None else "Library"
    stats = container.job_queue.get_stats(library_id)
    by_zone = container.track_repo.count_by_zone(library_id)
    confidence = container.track_repo.confidence_distribution(library_id)
    summary = container.track_repo.summarize_for_report(library_id)
    review_total = container.review_queue.count_pending(library_id)
    review_by_type = container.review_repo.count_pending_by_type(library_id)
    open_dups = len(container.duplicate_repo.list_open_by_library(library_id))
    last_scan_summary = _latest_scan_summary(container, library_id)
    processing_report = _processing_report(container, library_id, summary)

    # Running counts per type for the flow (subset of backlog).
    running_by_type = container.job_repo.count_by_type(
        library_id, statuses=(JobStatus.RUNNING,)
    )
    backlog = stats.by_type  # pending + running
    acquisition = _acquisition_stats(container, library_id)

    stage_backlogs: list[int] = []
    for key, _label, job_type in PIPELINE_STAGES:
        if key == "review":
            stage_backlogs.append(review_total)
        elif key == "acquire":
            stage_backlogs.append(acquisition.in_progress + acquisition.waiting_for_user)
        elif job_type is None:
            stage_backlogs.append(0)
        else:
            stage_backlogs.append(int(backlog.get(job_type, 0)))
    bottleneck_idx = (
        max(range(len(stage_backlogs)), key=lambda i: stage_backlogs[i])
        if any(stage_backlogs)
        else -1
    )

    stages: list[PipelineStageStat] = []
    for index, (key, label, job_type) in enumerate(PIPELINE_STAGES):
        if key == "review":
            running = 0
            stage_backlog = review_total
        elif key == "acquire":
            running = acquisition.in_progress
            stage_backlog = acquisition.in_progress + acquisition.waiting_for_user
        elif job_type is None:
            running = 0
            stage_backlog = 0
        else:
            running = int(running_by_type.get(job_type, 0))
            stage_backlog = int(backlog.get(job_type, 0))
        stages.append(
            PipelineStageStat(
                key=key,
                label=label,
                backlog=stage_backlog,
                running=running,
                is_active=stage_backlog > 0 or running > 0,
                is_bottleneck=index == bottleneck_idx and stage_backlog > 0,
            )
        )

    running_jobs = tuple(
        container.job_repo.list_by_status(
            JobStatus.RUNNING, library_id=library_id, limit=20
        )
    )
    failed_jobs = tuple(
        container.job_repo.list_by_status(
            JobStatus.FAILED, library_id=library_id, limit=10
        )
    )
    top_failures = tuple(container.job_repo.summarize_failures(library_id, limit=8))

    track_count = int(summary["track_count"])
    insight = _insight(
        track_count=track_count,
        stats_pending=stats.pending,
        stats_running=stats.running,
        stats_failed=stats.failed,
        review_pending=review_total,
        confidence=confidence,
        stages=stages,
        by_zone=by_zone,
        top_failures=top_failures,
        acquisition=acquisition,
    )

    return DashboardSnapshot(
        has_library=True,
        library_name=name,
        track_count=track_count,
        pending_jobs=stats.pending,
        running_jobs=stats.running,
        failed_jobs=stats.failed,
        review_pending=review_total,
        completed_today=stats.completed_today,
        open_duplicates=open_dups,
        tracks_by_zone={z.value: int(by_zone.get(z.value, 0)) for z in LibraryZone},
        confidence=confidence,
        average_confidence=(
            float(summary["average_confidence"])
            if summary.get("average_confidence") is not None
            else None
        ),
        stages=tuple(stages),
        job_backlog_by_type=dict(backlog),
        review_by_type=review_by_type,
        running_job_rows=running_jobs,
        failed_job_rows=failed_jobs,
        top_failures=top_failures,
        insight=insight,
        last_scan_summary=last_scan_summary,
        processing_report=processing_report,
        acquisition=acquisition,
    )


def _acquisition_stats(container: Container, library_id: UUID) -> AcquisitionDashboardStat:
    jobs = container.acquisition_engine.list_jobs(library_id=library_id)
    if not jobs:
        return AcquisitionDashboardStat()

    failed_states = {
        AcquisitionJobState.DOWNLOAD_FAILED,
        AcquisitionJobState.VERIFICATION_FAILED,
        AcquisitionJobState.IMPORT_FAILED,
        AcquisitionJobState.NO_RESULTS,
    }
    in_progress_states = {
        AcquisitionJobState.DOWNLOADING,
        AcquisitionJobState.VERIFYING,
        AcquisitionJobState.IMPORTING,
        AcquisitionJobState.SEARCHING,
        AcquisitionJobState.COLLECTING_RESULTS,
        AcquisitionJobState.SCORING,
        AcquisitionJobState.QUEUED,
        AcquisitionJobState.RETRY_SCHEDULED,
    }

    waiting = sum(1 for job in jobs if job.state is AcquisitionJobState.WAITING_FOR_USER)
    failed = sum(1 for job in jobs if job.state in failed_states)
    completed = sum(1 for job in jobs if job.state is AcquisitionJobState.COMPLETED)
    in_progress = sum(1 for job in jobs if job.state in in_progress_states)
    active = sum(1 for job in jobs if not job.is_terminal)

    return AcquisitionDashboardStat(
        total=len(jobs),
        active=active,
        waiting_for_user=waiting,
        in_progress=in_progress,
        failed=failed,
        completed=completed,
    )


def _latest_scan_summary(container: Container, library_id: UUID) -> str:
    """Most recent completed scan_directory result line, if any."""
    completed = container.job_repo.list_by_status(
        JobStatus.COMPLETED, library_id=library_id, limit=80
    )
    for job in completed:
        if job.job_type is not JobType.SCAN_DIRECTORY:
            continue
        summary = job.error_message or job.payload.get("summary")
        if isinstance(summary, str) and summary.strip():
            when = job.completed_at.isoformat(timespec="minutes") if job.completed_at else ""
            return f"Last scan{f' ({when})' if when else ''}: {summary}"
    return (
        "Last scan: none yet. Scan Incoming processes only new/changed files; "
        "use Force rescan to re-process everything."
    )


def _processing_report(
    container: Container, library_id: UUID, summary: dict[str, object]
) -> str:
    """Few-line digest of identify / artwork / organize outcomes since last scan."""
    completed = container.job_repo.list_by_status(
        JobStatus.COMPLETED, library_id=library_id, limit=400
    )
    since = None
    for job in completed:
        if job.job_type is JobType.SCAN_DIRECTORY and job.completed_at is not None:
            since = job.completed_at
            break

    identify_ok = identify_review = 0
    art_saved = art_missing = art_low = 0
    organized_library = organized_other = 0
    wave_jobs = 0

    for job in completed:
        if job.job_type is JobType.SCAN_DIRECTORY:
            continue
        if since is not None and (job.completed_at is None or job.completed_at < since):
            continue
        wave_jobs += 1
        outcome = job.payload.get("outcome")
        note = job.error_message if isinstance(job.error_message, str) else ""

        if job.job_type is JobType.IDENTIFY_METADATA:
            if outcome == "needs_review" or job.payload.get("needs_review") is True:
                identify_review += 1
            else:
                identify_ok += 1
        elif job.job_type is JobType.FETCH_ARTWORK:
            if outcome == "missing" or note.startswith("No artwork"):
                art_missing += 1
            elif outcome == "low_res" or note.startswith("Low-res"):
                art_low += 1
            elif outcome == "saved" or note.startswith("Cover saved"):
                art_saved += 1
        elif job.job_type is JobType.ORGANIZE_FILE:
            target = job.payload.get("target_zone")
            if target == LibraryZone.LIBRARY.value or "→ library" in note.lower() or (
                "library" in note.lower() and "Moved to" in note
            ):
                organized_library += 1
            else:
                organized_other += 1

    failed_identify = failed_art = 0
    for job in container.job_repo.list_by_status(
        JobStatus.FAILED, library_id=library_id, limit=100
    ):
        if since is not None and job.completed_at is not None and job.completed_at < since:
            continue
        if job.job_type is JobType.IDENTIFY_METADATA:
            failed_identify += 1
        elif job.job_type is JobType.FETCH_ARTWORK:
            failed_art += 1

    if wave_jobs == 0 and since is None:
        lines = [
            "Processing report:",
            "No completed pipeline jobs yet — run Scan Incoming.",
        ]
    else:
        lines = ["Processing report (since last scan):"]
        if identify_ok or identify_review or failed_identify:
            line = f"• Identify: {identify_ok} matched, {identify_review} need review"
            if failed_identify:
                line += f", {failed_identify} failed"
            lines.append(line)
        if art_saved or art_missing or art_low or failed_art:
            line = f"• Artwork: {art_saved} saved, {art_low} low-res, {art_missing} missing"
            if failed_art:
                line += f", {failed_art} failed"
            lines.append(line)
        if organized_library or organized_other:
            line = f"• Organized: {organized_library} → Library"
            if organized_other:
                line += f", {organized_other} other moves"
            lines.append(line)
        if len(lines) == 1:
            lines.append("• Pipeline jobs from this wave have not finished reporting yet.")

    lines.append(
        "• Catalog: "
        f"{int(summary.get('track_count', 0))} tracks · "
        f"{int(summary.get('artists_linked', 0))} artists · "
        f"{int(summary.get('albums_linked', 0))} albums · "
        f"{int(summary.get('tracks_with_cover', 0))} with cover"
    )
    return "\n".join(lines)


def _insight(
    *,
    track_count: int,
    stats_pending: int,
    stats_running: int,
    stats_failed: int,
    review_pending: int,
    confidence: dict[str, int],
    stages: list[PipelineStageStat],
    by_zone: dict[str, int],
    top_failures: tuple[tuple[str, str, int], ...] = (),
    acquisition: AcquisitionDashboardStat | None = None,
) -> str:
    acq = acquisition or AcquisitionDashboardStat()
    if acq.waiting_for_user:
        return (
            f"{acq.waiting_for_user} acquisition job(s) need your pick "
            f"(Attention needed / Acquisition page; {acq.active} active overall)."
        )
    if acq.failed:
        return (
            f"{acq.failed} acquisition job(s) failed or found no results — "
            "see Attention needed, then retry on Acquisition."
        )
    if acq.in_progress:
        return (
            f"Acquisition in progress: {acq.in_progress} job(s) searching or downloading. "
            "Open Acquisition for details."
        )
    if track_count == 0 and stats_pending == 0 and stats_running == 0:
        return (
            "No tracks yet. Drop files into Incoming and use File → Scan Incoming "
            "(or enable Watch) to discover them. Dashboard track totals grow with "
            "each scan; they are not replaced by the latest scan alone."
        )
    if stats_failed > 0:
        top = top_failures[0] if top_failures else None
        if top is not None:
            job_type, summary, count = top
            return (
                f"{stats_failed} failed job(s). Top issue ({count}×): {job_type} — {summary}. "
                "See “Common failures” below. Clear old failed jobs in Settings → Reset "
                "if they are stale missing-file errors after files already moved."
            )
        return (
            f"{stats_failed} job(s) failed — open Jobs to retry. "
            "Failures pause that file’s progress until cleared."
        )
    bottleneck = next((s for s in stages if s.is_bottleneck), None)
    if bottleneck is not None and bottleneck.key == "review":
        return (
            f"{review_pending} item(s) waiting for your decision in Review. "
            "Approve confident matches to move staging → library; reject or defer the rest."
        )
    if bottleneck is not None and bottleneck.backlog > 0:
        return (
            f"Pipeline bottleneck: {bottleneck.label} "
            f"({bottleneck.backlog} in queue"
            + (f", {bottleneck.running} running" if bottleneck.running else "")
            + "). Later stages wait until this clears."
        )
    if stats_running or stats_pending:
        return (
            f"Processing: {stats_running} running, {stats_pending} queued. "
            "Follow the pipeline strip to see which stage each wave of work is in."
        )
    high = confidence.get("high", 0)
    flagged = confidence.get("flagged", 0)
    unscored = confidence.get("unscored", 0)
    if flagged:
        return (
            f"Queue is idle. {flagged} track(s) still flagged for review; "
            f"{high} already at high confidence (≥90%)."
        )
    if unscored and track_count:
        return (
            f"Queue is idle, but {unscored} track(s) have no confidence yet — "
            "run a scan or re-queue identify jobs if metadata looks empty."
        )
    incoming = int(by_zone.get(LibraryZone.INCOMING.value, 0))
    if incoming:
        return (
            f"{incoming} file(s) sit in Incoming with no active jobs — "
            "Scan Incoming to start hashing and identification."
        )
    return (
        "Pipeline idle. Collection looks settled — check Library or Reports "
        "for a deeper look."
    )

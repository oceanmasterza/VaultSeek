"""Tests for dashboard snapshot assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from vaultseek.app import bootstrap
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.dashboard import PIPELINE_STAGES, build_dashboard_snapshot


def test_dashboard_empty_library_insight(tmp_path: Path) -> None:
    container = bootstrap(base_dir_override=tmp_path, console_logging=False)
    try:
        snap = build_dashboard_snapshot(container, None)
        assert snap.has_library is False
        assert "Settings" in snap.insight
    finally:
        container.close()


def test_dashboard_snapshot_with_tracks_and_confidence(tmp_path: Path) -> None:
    container = bootstrap(base_dir_override=tmp_path, console_logging=False)
    try:
        now = datetime.now(UTC)
        library_id = generate_uuid7()
        container.library_repo.upsert(
            Library(
                id=library_id,
                name="Dash Lib",
                incoming_path=str(tmp_path / "in"),
                staging_path=str(tmp_path / "st"),
                library_path=str(tmp_path / "lib"),
                archive_path=str(tmp_path / "ar"),
                created_at=now,
                updated_at=now,
            )
        )
        tracks = [
            Track(
                id=generate_uuid7(),
                library_id=library_id,
                zone=LibraryZone.STAGING,
                file_path=str(tmp_path / "a.flac"),
                file_name="a.flac",
                file_size=1,
                file_modified=now,
                created_at=now,
                updated_at=now,
                overall_confidence=0.95,
                needs_review=False,
            ),
            Track(
                id=generate_uuid7(),
                library_id=library_id,
                zone=LibraryZone.INCOMING,
                file_path=str(tmp_path / "b.flac"),
                file_name="b.flac",
                file_size=1,
                file_modified=now,
                created_at=now,
                updated_at=now,
                overall_confidence=0.70,
                needs_review=True,
            ),
            Track(
                id=generate_uuid7(),
                library_id=library_id,
                zone=LibraryZone.LIBRARY,
                file_path=str(tmp_path / "c.flac"),
                file_name="c.flac",
                file_size=1,
                file_modified=now,
                created_at=now,
                updated_at=now,
                overall_confidence=None,
                needs_review=False,
            ),
        ]
        container.track_repo.upsert_batch(tracks)

        snap = build_dashboard_snapshot(container, library_id)
        assert snap.has_library is True
        assert snap.library_name == "Dash Lib"
        assert snap.track_count == 3
        assert snap.confidence["high"] == 1
        assert snap.confidence["fair"] == 1
        assert snap.confidence["unscored"] == 1
        assert snap.confidence["flagged"] == 1
        assert len(snap.stages) == len(PIPELINE_STAGES)
        assert any(stage.key == "acquire" for stage in snap.stages)
        assert snap.tracks_by_zone[LibraryZone.STAGING.value] == 1
        assert snap.insight
        assert "Force rescan" in snap.last_scan_summary or "none yet" in snap.last_scan_summary
        assert "Catalog:" in snap.processing_report
        assert "3 tracks" in snap.processing_report
    finally:
        container.close()


def test_dashboard_acquisition_summary(tmp_path: Path) -> None:
    from vaultseek.models.entities.acquisition_job import AcquisitionJobState, AcquisitionJobType

    container = bootstrap(base_dir_override=tmp_path, console_logging=False)
    try:
        now = datetime.now(UTC)
        library_id = generate_uuid7()
        container.library_repo.upsert(
            Library(
                id=library_id,
                name="Acq Lib",
                incoming_path=str(tmp_path / "in"),
                staging_path=str(tmp_path / "st"),
                library_path=str(tmp_path / "lib"),
                archive_path=str(tmp_path / "ar"),
                created_at=now,
                updated_at=now,
            )
        )
        waiting = container.acquisition_engine.create_job(
            library_id=library_id,
            job_type=AcquisitionJobType.MISSING_TRACK,
            artist="Artist",
            album="Album",
            title="Track A",
        )
        container.acquisition_engine.queue(waiting.id)
        container.acquisition_engine.advance(waiting.id, AcquisitionJobState.SEARCHING)
        container.acquisition_engine.advance(waiting.id, AcquisitionJobState.COLLECTING_RESULTS)
        container.acquisition_engine.advance(waiting.id, AcquisitionJobState.SCORING)
        container.acquisition_engine.advance(
            waiting.id, AcquisitionJobState.WAITING_FOR_USER, note="below threshold"
        )
        failed = container.acquisition_engine.create_job(
            library_id=library_id,
            job_type=AcquisitionJobType.MISSING_TRACK,
            artist="Artist",
            album="Album",
            title="Track B",
        )
        container.acquisition_engine.queue(failed.id)
        container.acquisition_engine.advance(failed.id, AcquisitionJobState.SEARCHING)
        container.acquisition_engine.advance(failed.id, AcquisitionJobState.NO_RESULTS)

        snap = build_dashboard_snapshot(container, library_id)
        assert snap.acquisition.total == 2
        assert snap.acquisition.active == 2
        assert snap.acquisition.waiting_for_user == 1
        assert snap.acquisition.failed == 1
        assert "awaiting your pick" in snap.insight or "Acquisition" in snap.insight
        acquire = next(stage for stage in snap.stages if stage.key == "acquire")
        assert acquire.backlog == 1  # waiting_for_user only (failed NO_RESULTS not in backlog formula)
        assert acquire.running == 0
        assert acquire.is_active is True
    finally:
        container.close()


def test_dashboard_acquiring_stage_counts_in_progress(tmp_path: Path) -> None:
    from vaultseek.models.entities.acquisition_job import AcquisitionJobState, AcquisitionJobType

    container = bootstrap(base_dir_override=tmp_path, console_logging=False)
    try:
        now = datetime.now(UTC)
        library_id = generate_uuid7()
        container.library_repo.upsert(
            Library(
                id=library_id,
                name="Acq Progress",
                incoming_path=str(tmp_path / "in"),
                staging_path=str(tmp_path / "st"),
                library_path=str(tmp_path / "lib"),
                archive_path=str(tmp_path / "ar"),
                created_at=now,
                updated_at=now,
            )
        )
        job = container.acquisition_engine.create_job(
            library_id=library_id,
            job_type=AcquisitionJobType.MISSING_TRACK,
            artist="A",
            album="B",
            title="C",
        )
        container.acquisition_engine.queue(job.id)
        container.acquisition_engine.advance(job.id, AcquisitionJobState.SEARCHING)

        snap = build_dashboard_snapshot(container, library_id)
        acquire = next(stage for stage in snap.stages if stage.key == "acquire")
        assert acquire.running == 1
        assert acquire.backlog == 1
        assert acquire.label == "Acquiring"
        assert snap.stages[0].key == "scan"
        assert snap.stages[0].label == "Discover"
    finally:
        container.close()


def test_dashboard_pipeline_order() -> None:
    assert PIPELINE_STAGES[0][0] == "scan"
    assert PIPELINE_STAGES[0][1] == "Discover"
    acquire_index = next(i for i, stage in enumerate(PIPELINE_STAGES) if stage[0] == "acquire")
    sync_index = next(i for i, stage in enumerate(PIPELINE_STAGES) if stage[0] == "sync")
    assert acquire_index < sync_index
    assert PIPELINE_STAGES[acquire_index][1] == "Acquiring"


def test_dashboard_processing_report_tallies_wave_outcomes(tmp_path: Path) -> None:
    from vaultseek.models.entities.job import JobType

    container = bootstrap(base_dir_override=tmp_path, console_logging=False)
    try:
        now = datetime.now(UTC)
        library_id = generate_uuid7()
        container.library_repo.upsert(
            Library(
                id=library_id,
                name="Report Lib",
                incoming_path=str(tmp_path / "in"),
                staging_path=str(tmp_path / "st"),
                library_path=str(tmp_path / "lib"),
                archive_path=str(tmp_path / "ar"),
                created_at=now,
                updated_at=now,
            )
        )
        scan_id = container.job_queue.enqueue(
            JobType.SCAN_DIRECTORY,
            library_id,
            {"directory": str(tmp_path / "in"), "zone": "incoming"},
            now=now,
        )
        container.job_queue.mark_completed(
            scan_id,
            now=now,
            summary="Scan complete: 2 audio file(s), 2 queued for processing, 0 unchanged skipped.",
            result={"summary": "Scan complete: 2 audio file(s), 2 queued.", "files_queued": 2},
        )
        id_ok = container.job_queue.enqueue(
            JobType.IDENTIFY_METADATA, library_id, {"track_id": "a"}, now=now
        )
        container.job_queue.mark_completed(
            id_ok,
            now=now,
            summary="Identified: A — B / T (95%)",
            result={"outcome": "matched", "needs_review": False},
        )
        id_rev = container.job_queue.enqueue(
            JobType.IDENTIFY_METADATA, library_id, {"track_id": "b"}, now=now
        )
        container.job_queue.mark_completed(
            id_rev,
            now=now,
            summary="Identified: X (40%) — needs review",
            result={"outcome": "needs_review", "needs_review": True},
        )
        art = container.job_queue.enqueue(
            JobType.FETCH_ARTWORK, library_id, {"track_id": "a"}, now=now
        )
        container.job_queue.mark_completed(
            art,
            now=now,
            summary="Cover saved (embedded_art, 600x600) for 'a.flac'",
            result={"outcome": "saved"},
        )
        art_miss = container.job_queue.enqueue(
            JobType.FETCH_ARTWORK, library_id, {"track_id": "b"}, now=now
        )
        container.job_queue.mark_completed(
            art_miss,
            now=now,
            summary="No artwork for 'b.flac'",
            result={"outcome": "missing"},
        )

        snap = build_dashboard_snapshot(container, library_id)
        assert "Last scan" in snap.last_scan_summary
        assert "2 queued" in snap.last_scan_summary or "2 audio" in snap.last_scan_summary
        assert "1 matched, 1 need review" in snap.processing_report
        assert "1 saved" in snap.processing_report
        assert "1 missing" in snap.processing_report
    finally:
        container.close()

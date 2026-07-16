"""Unit tests for musicvault.core.container."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import insert, text

from musicvault.core.config import AppConfig
from musicvault.core.container import Container
from musicvault.core.event_bus import EventBus
from musicvault.core.paths import AppPaths
from musicvault.db.repositories.album_repo import AlbumRepository
from musicvault.db.repositories.artist_repo import ArtistRepository
from musicvault.db.repositories.file_identity_repo import FileIdentityRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.metadata_confidence_repo import MetadataConfidenceRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.rule_repo import RuleRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.tables import libraries
from musicvault.db.uuid_utils import generate_uuid7, uuid_to_blob
from musicvault.db.writer import DatabaseWriter
from musicvault.models.entities.job import Job, JobStatus, JobType
from musicvault.plugins.manager import PluginManager
from musicvault.services.job_dispatcher import JobDispatcher
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.metadata_arbitrator import MetadataArbitrator
from musicvault.services.review_queue_service import ReviewQueueService
from musicvault.workers.cpu.fingerprint_worker import FingerprintWorker
from musicvault.workers.cpu.hash_worker import HashWorker
from musicvault.workers.io.metadata_worker import MetadataWorker
from musicvault.workers.io.scanner_worker import ScannerWorker


def test_bootstrap_wires_provided_paths_and_config(
    app_paths: AppPaths, app_config: AppConfig
) -> None:
    container = Container.bootstrap(paths=app_paths, config=app_config)

    assert container.paths is app_paths
    assert container.config is app_config
    container.close()


def test_bootstrap_creates_an_event_bus(app_paths: AppPaths, app_config: AppConfig) -> None:
    container = Container.bootstrap(paths=app_paths, config=app_config)

    assert isinstance(container.event_bus, EventBus)
    container.close()


def test_each_bootstrap_call_creates_an_independent_event_bus(
    app_paths: AppPaths, app_config: AppConfig
) -> None:
    first = Container.bootstrap(paths=app_paths, config=app_config)
    first_bus = first.event_bus
    first.close()

    second = Container.bootstrap(paths=app_paths, config=app_config)

    assert first_bus is not second.event_bus
    second.close()


def test_bootstrap_creates_the_database_file_with_all_tables(
    app_paths: AppPaths, app_config: AppConfig
) -> None:
    container = Container.bootstrap(paths=app_paths, config=app_config)

    assert app_paths.database_file.is_file()
    with container.engine.connect() as conn:
        tables = {
            row.name
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
        }
    assert {
        "jobs",
        "review_items",
        "rules",
        "file_identity",
        "tracks",
        "albums",
        "artists",
    }.issubset(tables)
    container.close()


def test_bootstrap_wires_all_phase_2_repositories(
    app_paths: AppPaths, app_config: AppConfig
) -> None:
    container = Container.bootstrap(paths=app_paths, config=app_config)

    assert isinstance(container.job_repo, JobRepository)
    assert isinstance(container.review_repo, ReviewRepository)
    assert isinstance(container.rule_repo, RuleRepository)
    assert isinstance(container.file_identity_repo, FileIdentityRepository)
    container.close()


def test_bootstrap_wires_all_phase_3_repositories(
    app_paths: AppPaths, app_config: AppConfig
) -> None:
    container = Container.bootstrap(paths=app_paths, config=app_config)

    assert isinstance(container.track_repo, TrackRepository)
    assert isinstance(container.album_repo, AlbumRepository)
    assert isinstance(container.artist_repo, ArtistRepository)
    container.close()


def test_bootstrap_wires_the_phase_4_pipeline(app_paths: AppPaths, app_config: AppConfig) -> None:
    container = Container.bootstrap(paths=app_paths, config=app_config)

    assert isinstance(container.database_writer, DatabaseWriter)
    assert isinstance(container.job_queue, JobQueueService)
    assert isinstance(container.scanner_worker, ScannerWorker)
    assert isinstance(container.hash_worker, HashWorker)
    assert isinstance(container.fingerprint_worker, FingerprintWorker)
    assert isinstance(container.dispatcher, JobDispatcher)
    container.close()


def test_bootstrap_wires_the_phase_6_metadata_stack(
    app_paths: AppPaths, app_config: AppConfig
) -> None:
    container = Container.bootstrap(paths=app_paths, config=app_config)

    assert isinstance(container.metadata_confidence_repo, MetadataConfidenceRepository)
    assert isinstance(container.plugin_manager, PluginManager)
    assert isinstance(container.metadata_arbitrator, MetadataArbitrator)
    assert isinstance(container.metadata_worker, MetadataWorker)
    assert isinstance(container.review_queue, ReviewQueueService)
    provider_ids = {p.provider_id for p in container.plugin_manager.get_metadata_providers()}
    assert provider_ids == {"acoustid", "musicbrainz", "local_tags", "filename_parser"}
    container.close()


def test_bootstrap_recovers_orphaned_jobs_on_startup(
    app_paths: AppPaths, app_config: AppConfig
) -> None:
    """A `running` job left behind by a previous crash must not stay
    `running` once the next `Container.bootstrap` completes.

    The exact post-recovery status (`retry` vs `pending`) depends on
    dispatcher timing — `recover_orphaned` sets `retry`, and the first
    poll may promote it to `pending` or even claim it — so this test
    stops the dispatcher before asserting and only checks the job is no
    longer orphaned as `running`."""
    first = Container.bootstrap(paths=app_paths, config=app_config)
    library_id = generate_uuid7()
    now = datetime.now(UTC).isoformat()
    with first.engine.begin() as conn:
        conn.execute(
            insert(libraries).values(
                id=uuid_to_blob(library_id),
                name="Test Library",
                incoming_path="C:/incoming",
                staging_path="C:/staging",
                library_path="C:/library",
                archive_path="C:/archive",
                created_at=now,
                updated_at=now,
            )
        )
    job = Job(
        id=generate_uuid7(),
        library_id=library_id,
        job_type=JobType.SCAN_DIRECTORY,
        status=JobStatus.RUNNING,
        payload={
            "directory": "C:/nonexistent_musicvault_orphan_recovery_test",
            "zone": "incoming",
        },
        created_at=datetime.now(UTC),
    )
    first.job_repo.create(job)
    first.close()

    second = Container.bootstrap(paths=app_paths, config=app_config)
    second.dispatcher.stop()

    recovered = second.job_repo.get(job.id)
    assert recovered is not None
    assert recovered.status is not JobStatus.RUNNING
    second.close()


def test_bootstrap_is_safe_to_call_twice_against_the_same_database(
    app_paths: AppPaths, app_config: AppConfig
) -> None:
    """The second bootstrap must not fail just because migrations already ran."""
    first = Container.bootstrap(paths=app_paths, config=app_config)
    first.close()

    second = Container.bootstrap(paths=app_paths, config=app_config)

    assert app_paths.database_file.is_file()
    second.close()

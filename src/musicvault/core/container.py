"""Application-wide dependency injection container.

A single :class:`Container` instance is created during application
bootstrap (see :mod:`musicvault.app`) and threaded through explicitly to
whatever needs it. There is no module-level singleton, which keeps every
component trivially testable: a test builds its own container from a
temporary directory and an in-memory configuration instead of relying on
global state.

Later phases extend this container with additional services as those
layers are implemented (see docs/architecture/07-roadmap.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Engine

from musicvault.core.config import AppConfig, ArtworkConfig, MetadataConfig
from musicvault.core.event_bus import EventBus
from musicvault.core.paths import AppPaths
from musicvault.db.engine import create_sqlite_engine
from musicvault.db.migrations.runner import run_migrations
from musicvault.db.repositories.album_repo import AlbumRepository
from musicvault.db.repositories.artist_repo import ArtistRepository
from musicvault.db.repositories.artwork_repo import ArtworkRepository
from musicvault.db.repositories.duplicate_repo import DuplicateRepository
from musicvault.db.repositories.file_identity_repo import FileIdentityRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.library_repo import LibraryRepository
from musicvault.db.repositories.media_server_repo import MediaServerStateRepository
from musicvault.db.repositories.metadata_confidence_repo import MetadataConfidenceRepository
from musicvault.db.repositories.operation_repo import OperationRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.rule_repo import RuleRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.writer import DatabaseWriter
from musicvault.models.interfaces.artwork import ArtworkProvider
from musicvault.models.interfaces.media_server import MediaServerPlugin
from musicvault.models.interfaces.metadata import MetadataProvider
from musicvault.models.services.duplicate_matcher import DuplicateMatcher
from musicvault.models.services.organize_engine import OrganizeEngine
from musicvault.models.services.quality_scorer import DEFAULT_WEIGHTS, QualityScorer
from musicvault.plugins.builtin.acoustid import AcoustIdProvider
from musicvault.plugins.builtin.cover_art_archive import CoverArtArchiveProvider
from musicvault.plugins.builtin.embedded_art import EmbeddedArtProvider
from musicvault.plugins.builtin.filename_parser import FilenameParserProvider
from musicvault.plugins.builtin.jellyfin import JellyfinPlugin
from musicvault.plugins.builtin.local_tags import LocalTagsProvider
from musicvault.plugins.builtin.musicbrainz import MusicBrainzProvider
from musicvault.plugins.builtin.navidrome import NavidromePlugin
from musicvault.plugins.builtin.plex import PlexPlugin
from musicvault.plugins.builtin.subsonic import SubsonicPlugin
from musicvault.plugins.manager import PluginManager
from musicvault.services.job_dispatcher import JobDispatcher
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.metadata_arbitrator import MetadataArbitrator
from musicvault.services.operation_orchestrator import OperationOrchestrator
from musicvault.services.report_service import ReportService
from musicvault.services.review_queue_service import ReviewQueueService
from musicvault.services.rules_engine import RulesEngine
from musicvault.services.watch_folder_service import WatchFolderService
from musicvault.workers.cpu.fingerprint_worker import FingerprintWorker
from musicvault.workers.cpu.hash_worker import HashWorker
from musicvault.workers.io.artwork_worker import ArtworkWorker
from musicvault.workers.io.duplicate_worker import DuplicateWorker
from musicvault.workers.io.media_server_worker import MediaServerWorker
from musicvault.workers.io.metadata_worker import MetadataWorker
from musicvault.workers.io.organizer_worker import OrganizerWorker
from musicvault.workers.io.report_worker import ReportWorker
from musicvault.workers.io.rule_worker import RuleWorker
from musicvault.workers.io.scanner_worker import ScannerWorker


@dataclass
class Container:
    """Holds the fully wired set of application-level dependencies."""

    paths: AppPaths
    config: AppConfig
    engine: Engine
    job_repo: JobRepository
    review_repo: ReviewRepository
    rule_repo: RuleRepository
    duplicate_repo: DuplicateRepository
    library_repo: LibraryRepository
    media_server_repo: MediaServerStateRepository
    operation_repo: OperationRepository
    artwork_repo: ArtworkRepository
    file_identity_repo: FileIdentityRepository
    track_repo: TrackRepository
    album_repo: AlbumRepository
    artist_repo: ArtistRepository
    metadata_confidence_repo: MetadataConfidenceRepository
    database_writer: DatabaseWriter
    job_queue: JobQueueService
    review_queue: ReviewQueueService
    rules_engine: RulesEngine
    duplicate_matcher: DuplicateMatcher
    organize_engine: OrganizeEngine
    operation_orchestrator: OperationOrchestrator
    report_service: ReportService
    watch_folder: WatchFolderService
    plugin_manager: PluginManager
    metadata_arbitrator: MetadataArbitrator
    scanner_worker: ScannerWorker
    hash_worker: HashWorker
    fingerprint_worker: FingerprintWorker
    metadata_worker: MetadataWorker
    rule_worker: RuleWorker
    duplicate_worker: DuplicateWorker
    organizer_worker: OrganizerWorker
    artwork_worker: ArtworkWorker
    report_worker: ReportWorker
    media_server_worker: MediaServerWorker
    dispatcher: JobDispatcher
    event_bus: EventBus = field(default_factory=EventBus)

    @classmethod
    def bootstrap(cls, *, paths: AppPaths, config: AppConfig) -> Container:
        """Construct a container for normal application startup.

        Runs pending Alembic migrations first — this is how the database
        file and its schema get created on first run — then opens the
        (now up-to-date) database and wires the repositories that read
        and write it.

        Also starts the pipeline: the single-writer
        :class:`DatabaseWriter` thread and the :class:`JobDispatcher`
        polling loop. Crash recovery (resetting jobs orphaned by a
        previous crash back to `retry`) runs synchronously, before the
        dispatcher starts polling — see
        :meth:`~musicvault.services.job_dispatcher.JobDispatcher.recover`.
        Starting the dispatcher here is safe even though nothing enqueues
        jobs yet: `ThreadPoolExecutor`/`ProcessPoolExecutor`
        only spawn actual OS threads/processes lazily, on first
        `submit()`, so an idle dispatcher costs one lightweight polling
        thread and no worker processes.
        """
        run_migrations(paths.database_file)
        engine = create_sqlite_engine(paths.database_file)

        job_repo = JobRepository(engine)
        track_repo = TrackRepository(engine)
        review_repo = ReviewRepository(engine)
        rule_repo = RuleRepository(engine)
        duplicate_repo = DuplicateRepository(engine)
        library_repo = LibraryRepository(engine)
        media_server_repo = MediaServerStateRepository(engine)
        operation_repo = OperationRepository(engine)
        artwork_repo = ArtworkRepository(engine)
        artist_repo = ArtistRepository(engine)
        album_repo = AlbumRepository(engine)
        file_identity_repo = FileIdentityRepository(engine)
        metadata_confidence_repo = MetadataConfidenceRepository(engine)
        event_bus = EventBus()

        database_writer = DatabaseWriter(
            engine,
            batch_size=config.pipeline.db_writer_batch_size,
            flush_interval_ms=config.pipeline.db_writer_flush_interval_ms,
        )
        job_queue = JobQueueService(job_repo, config.pipeline)
        review_queue = ReviewQueueService(
            review_repo,
            track_repo,
            event_bus,
            confidence_threshold=config.metadata.confidence_threshold,
            job_queue=job_queue,
            duplicate_repository=duplicate_repo,
        )
        rules_engine = RulesEngine(
            rule_repo, track_repo, artist_repo, review_queue, event_bus, job_queue
        )
        duplicate_matcher = DuplicateMatcher(QualityScorer(DEFAULT_WEIGHTS))
        organize_engine = OrganizeEngine()
        operation_orchestrator = OperationOrchestrator(
            operation_repo,
            track_repo,
            library_repo,
            artist_repo,
            album_repo,
            organize_engine,
            job_queue=job_queue,
        )
        report_service = ReportService(
            library_repo,
            track_repo,
            review_repo,
            duplicate_repo,
            reports_dir=paths.reports_dir,
            job_queue=job_queue,
        )
        watch_folder = WatchFolderService(
            library_repo,
            job_queue,
            poll_interval_seconds=config.watch.poll_interval_seconds,
        )

        plugin_manager = PluginManager(
            _build_metadata_providers(config.metadata),
            _build_artwork_providers(config.artwork),
            _build_media_server_plugins(),
        )
        metadata_arbitrator = MetadataArbitrator(
            plugin_manager.get_metadata_providers(),
            confidence_threshold=config.metadata.confidence_threshold,
        )

        scanner_worker = ScannerWorker(track_repo, file_identity_repo, database_writer, job_queue)
        hash_worker = HashWorker(file_identity_repo, database_writer, job_queue)
        fingerprint_worker = FingerprintWorker(file_identity_repo, database_writer, job_queue)
        metadata_worker = MetadataWorker(
            track_repo,
            file_identity_repo,
            metadata_confidence_repo,
            metadata_arbitrator,
            job_queue,
            review_queue,
        )
        rule_worker = RuleWorker(track_repo, rules_engine, duplicate_repo, job_queue)
        duplicate_worker = DuplicateWorker(
            track_repo,
            file_identity_repo,
            duplicate_repo,
            duplicate_matcher,
            review_queue,
            job_queue,
        )
        organizer_worker = OrganizerWorker(
            track_repo,
            library_repo,
            artist_repo,
            album_repo,
            review_repo,
            duplicate_repo,
            operation_repo,
            organize_engine,
            job_queue,
        )
        artwork_worker = ArtworkWorker(
            track_repo,
            album_repo,
            artwork_repo,
            plugin_manager.get_artwork_providers(),
            review_queue,
            job_queue,
            artwork_dir=paths.cache_dir / "artwork",
            min_width=config.artwork.min_width,
            min_height=config.artwork.min_height,
        )
        report_worker = ReportWorker(report_service, job_queue)
        media_server_worker = MediaServerWorker(
            media_server_repo,
            track_repo,
            plugin_manager.get_media_servers(),
            job_queue,
        )
        dispatcher = JobDispatcher(
            job_queue,
            scanner_worker,
            hash_worker,
            fingerprint_worker,
            metadata_worker,
            rule_worker,
            duplicate_worker,
            organizer_worker,
            artwork_worker,
            report_worker,
            media_server_worker,
            scanner_threads=config.pipeline.scanner_worker_threads,
            hash_processes=config.pipeline.hash_worker_processes,
            metadata_threads=config.pipeline.metadata_worker_threads,
            claim_batch_size=config.pipeline.job_claim_batch_size,
        )

        database_writer.start()
        dispatcher.recover()
        dispatcher.start()
        watch_folder.start()

        return cls(
            paths=paths,
            config=config,
            engine=engine,
            job_repo=job_repo,
            review_repo=review_repo,
            rule_repo=rule_repo,
            duplicate_repo=duplicate_repo,
            library_repo=library_repo,
            media_server_repo=media_server_repo,
            operation_repo=operation_repo,
            artwork_repo=artwork_repo,
            file_identity_repo=file_identity_repo,
            track_repo=track_repo,
            album_repo=album_repo,
            artist_repo=artist_repo,
            metadata_confidence_repo=metadata_confidence_repo,
            database_writer=database_writer,
            job_queue=job_queue,
            review_queue=review_queue,
            rules_engine=rules_engine,
            duplicate_matcher=duplicate_matcher,
            organize_engine=organize_engine,
            operation_orchestrator=operation_orchestrator,
            report_service=report_service,
            watch_folder=watch_folder,
            plugin_manager=plugin_manager,
            metadata_arbitrator=metadata_arbitrator,
            scanner_worker=scanner_worker,
            hash_worker=hash_worker,
            fingerprint_worker=fingerprint_worker,
            metadata_worker=metadata_worker,
            rule_worker=rule_worker,
            duplicate_worker=duplicate_worker,
            organizer_worker=organizer_worker,
            artwork_worker=artwork_worker,
            report_worker=report_worker,
            media_server_worker=media_server_worker,
            dispatcher=dispatcher,
            event_bus=event_bus,
        )

    def close(self) -> None:
        """Release resources held by this container.

        Stops the watch-folder poller, the dispatcher (waiting for any
        in-flight work to finish), and the database writer thread
        (flushing anything still buffered) before disposing the database
        engine's connection pool. Call this during application shutdown;
        tests should call it (or use the ``container`` fixture, which
        does) to avoid leaking SQLite connections and background threads
        across test cases.
        """
        self.watch_folder.stop()
        self.dispatcher.stop()
        self.database_writer.stop()
        self.engine.dispose()


def _build_metadata_providers(metadata: MetadataConfig) -> list[MetadataProvider]:
    """Construct enabled built-in metadata providers (explicit wiring —
    entry-point discovery stays a later phase)."""
    enabled = set(metadata.enabled_providers)
    providers: list[MetadataProvider] = []
    if "acoustid" in enabled:
        providers.append(AcoustIdProvider(api_key=metadata.acoustid_api_key or None))
    if "musicbrainz" in enabled:
        providers.append(MusicBrainzProvider())
    if "local_tags" in enabled:
        providers.append(LocalTagsProvider())
    if "filename_parser" in enabled:
        providers.append(FilenameParserProvider())
    return providers


def _build_artwork_providers(artwork: ArtworkConfig) -> list[ArtworkProvider]:
    """Construct built-in artwork providers. ``fetch_enabled`` gates only
    the network provider — embedded extraction always runs."""
    providers: list[ArtworkProvider] = []
    if artwork.fetch_enabled:
        providers.append(CoverArtArchiveProvider())
    providers.append(EmbeddedArtProvider())
    return providers


def _build_media_server_plugins() -> list[MediaServerPlugin]:
    """Construct built-in media-server plugins (explicit wiring)."""
    return [
        NavidromePlugin(),
        JellyfinPlugin(),
        PlexPlugin(),
        SubsonicPlugin(),
    ]

"""Application-wide dependency injection container.

A single :class:`Container` instance is created during application
bootstrap (see :mod:`vaultseek.app`) and threaded through explicitly to
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

from vaultseek.core.config import AppConfig, ArtworkConfig, MetadataConfig
from vaultseek.core.event_bus import EventBus
from vaultseek.core.paths import AppPaths
from vaultseek.db.engine import create_sqlite_engine
from vaultseek.db.migrations.runner import run_migrations
from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.artwork_repo import ArtworkRepository
from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.repositories.media_server_repo import MediaServerStateRepository
from vaultseek.db.repositories.metadata_confidence_repo import MetadataConfidenceRepository
from vaultseek.db.repositories.operation_repo import OperationRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.rule_repo import RuleRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.repositories.trusted_folder_repo import TrustedFolderRepository
from vaultseek.db.writer import DatabaseWriter
from vaultseek.models.interfaces.acquisition import AcquisitionProvider
from vaultseek.models.interfaces.artwork import ArtworkProvider
from vaultseek.models.interfaces.media_server import MediaServerPlugin
from vaultseek.models.interfaces.metadata import MetadataProvider
from vaultseek.models.services.duplicate_matcher import DuplicateMatcher
from vaultseek.models.services.organize_engine import OrganizeEngine
from vaultseek.models.services.quality_scorer import DEFAULT_WEIGHTS, QualityScorer
from vaultseek.plugins.builtin.acoustid import AcoustIdProvider, AcoustIdProviderPool, build_acoustid_endpoints
from vaultseek.plugins.builtin.acquisition_stub import StubAcquisitionProvider
from vaultseek.plugins.builtin.ampache import AmpachePlugin
from vaultseek.plugins.builtin.chromaprint.provider import ChromaprintFingerprintProvider
from vaultseek.plugins.builtin.cover_art_archive import CoverArtArchiveProvider
from vaultseek.plugins.builtin.discogs import DiscogsArtworkProvider, DiscogsProvider
from vaultseek.plugins.builtin.embedded_art import EmbeddedArtProvider
from vaultseek.plugins.builtin.embedded_art import EmbeddedArtProvider
from vaultseek.plugins.builtin.emby import EmbyPlugin
from vaultseek.plugins.builtin.filename_parser import FilenameParserProvider
from vaultseek.plugins.builtin.funkwhale import FunkwhalePlugin
from vaultseek.plugins.builtin.jellyfin import JellyfinPlugin
from vaultseek.plugins.builtin.koel import KoelPlugin
from vaultseek.plugins.builtin.local_tags import LocalTagsProvider
from vaultseek.plugins.builtin.lyrion import LyrionPlugin
from vaultseek.plugins.builtin.musicbrainz import MusicBrainzProvider
from vaultseek.plugins.builtin.navidrome import NavidromePlugin
from vaultseek.plugins.builtin.nicotine_plus import NicotinePlusProvider
from vaultseek.plugins.builtin.plex import PlexPlugin
from vaultseek.plugins.builtin.subsonic import SubsonicPlugin
from vaultseek.plugins.manager import PluginManager
from vaultseek.services.acquisition_bootstrap import connect_acquisition_providers
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_automation_service import AcquisitionAutomationService
from vaultseek.services.acquisition_runner import AcquisitionRunner
from vaultseek.services.acquisition_workflow import AcquisitionWorkflow
from vaultseek.services.download_manager import DownloadManager
from vaultseek.services.import_pipeline import ImportPipeline
from vaultseek.services.folder_trust import FolderTrustService
from vaultseek.services.job_dispatcher import JobDispatcher
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.metadata_arbitrator import MetadataArbitrator
from vaultseek.services.missing_media_analyzer import MissingMediaAnalyzer
from vaultseek.services.operation_orchestrator import OperationOrchestrator
from vaultseek.services.provider_manager import ProviderManager
from vaultseek.services.report_service import ReportService
from vaultseek.services.review_queue_service import ReviewQueueService
from vaultseek.services.rules_engine import RulesEngine
from vaultseek.services.scoring_engine import ScoringEngine
from vaultseek.services.search_dispatcher import SearchDispatcher
from vaultseek.services.verification_engine import VerificationEngine
from vaultseek.services.watch_folder_service import WatchFolderService
from vaultseek.workers.cpu.fingerprint_worker import FingerprintWorker
from vaultseek.workers.cpu.hash_worker import HashWorker
from vaultseek.workers.io.artwork_worker import ArtworkWorker
from vaultseek.workers.io.duplicate_worker import DuplicateWorker
from vaultseek.workers.io.media_server_worker import MediaServerWorker
from vaultseek.workers.io.metadata_worker import MetadataWorker
from vaultseek.workers.io.organizer_worker import OrganizerWorker
from vaultseek.workers.io.report_worker import ReportWorker
from vaultseek.workers.io.rule_worker import RuleWorker
from vaultseek.workers.io.scanner_worker import ScannerWorker


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
    acquisition_job_repo: AcquisitionJobRepository
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
    provider_manager: ProviderManager
    acquisition_engine: AcquisitionEngine
    search_dispatcher: SearchDispatcher
    scoring_engine: ScoringEngine
    download_manager: DownloadManager
    verification_engine: VerificationEngine
    import_pipeline: ImportPipeline
    acquisition_workflow: AcquisitionWorkflow
    acquisition_runner: AcquisitionRunner
    acquisition_automation_service: AcquisitionAutomationService
    missing_media_analyzer: MissingMediaAnalyzer | None
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
        :meth:`~vaultseek.services.job_dispatcher.JobDispatcher.recover`.
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
        trusted_folder_repo = TrustedFolderRepository(engine)
        acquisition_job_repo = AcquisitionJobRepository(engine)
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
            _build_artwork_providers(
                config.artwork,
                discogs_user_token=config.metadata.discogs_user_token,
            ),
            _build_media_server_plugins(),
            _build_acquisition_providers(),
        )
        provider_manager = ProviderManager(plugin_manager.get_acquisition_providers())
        connect_acquisition_providers(config.acquisition, provider_manager)
        acquisition_engine = AcquisitionEngine(provider_manager, acquisition_job_repo)
        search_dispatcher = SearchDispatcher(
            provider_manager,
            acquisition_engine,
            timeout_seconds=config.acquisition.search_timeout_seconds,
        )
        scoring_engine = ScoringEngine()
        download_manager = DownloadManager(provider_manager, acquisition_engine)
        local_tags = next(
            (
                provider
                for provider in plugin_manager.get_metadata_providers()
                if isinstance(provider, LocalTagsProvider)
            ),
            LocalTagsProvider(),
        )
        verification_engine = VerificationEngine(
            acquisition_engine,
            duplicate_repo=duplicate_repo,
            tags_provider=local_tags,
            fingerprint_provider=ChromaprintFingerprintProvider(),
        )
        import_pipeline = ImportPipeline(
            acquisition_engine,
            library_repo=library_repo,
            job_queue=job_queue,
        )
        acquisition_workflow = AcquisitionWorkflow(
            acquisition_engine,
            download_manager,
            verification_engine,
            import_pipeline,
        )
        acquisition_runner = AcquisitionRunner(
            acquisition_engine,
            search_dispatcher,
            scoring_engine,
            download_manager,
            acquisition_workflow,
            auto_acquire_threshold=config.acquisition.auto_acquire_threshold,
            review_queue=review_queue,
            library_repo=library_repo,
            acquisition_config=config.acquisition,
        )
        acquisition_automation_service = AcquisitionAutomationService(
            library_repo=library_repo,
            acquisition_job_repo=acquisition_job_repo,
            acquisition_engine=acquisition_engine,
            acquisition_runner=acquisition_runner,
            pipeline_config=config.pipeline,
            event_bus=event_bus,
            acquisition_config=config.acquisition,
            provider_manager=provider_manager,
            review_queue=review_queue,
        )
        metadata_arbitrator = MetadataArbitrator(
            plugin_manager.get_metadata_providers(),
            confidence_threshold=config.metadata.confidence_threshold,
        )
        musicbrainz = next(
            (
                provider
                for provider in plugin_manager.get_metadata_providers()
                if isinstance(provider, MusicBrainzProvider)
            ),
            None,
        )
        folder_trust = (
            FolderTrustService(
                trusted_folder_repo,
                track_repo,
                file_identity_repo,
                album_repo,
                musicbrainz,
                job_queue,
                job_repo,
                sample_min=config.metadata.fingerprint_sample_min,
            )
            if musicbrainz is not None
            else None
        )
        missing_media_analyzer = (
            MissingMediaAnalyzer(album_repo, track_repo, musicbrainz, artist_repo)
            if musicbrainz is not None
            else None
        )

        scanner_worker = ScannerWorker(track_repo, file_identity_repo, database_writer, job_queue)
        hash_worker = HashWorker(
            file_identity_repo,
            database_writer,
            job_queue,
            track_repo=track_repo,
            folder_trust=folder_trust,
            fingerprint_mode=config.metadata.fingerprint_mode,
        )
        fingerprint_worker = FingerprintWorker(file_identity_repo, database_writer, job_queue)
        metadata_worker = MetadataWorker(
            track_repo,
            file_identity_repo,
            metadata_confidence_repo,
            metadata_arbitrator,
            job_queue,
            review_queue,
            artist_repo=artist_repo,
            album_repo=album_repo,
            artwork_repo=artwork_repo,
            folder_trust=folder_trust,
            fingerprint_mode=config.metadata.fingerprint_mode,
        )
        rule_worker = RuleWorker(
            track_repo,
            rules_engine,
            duplicate_repo,
            job_queue,
            library_repo=library_repo,
        )
        duplicate_worker = DuplicateWorker(
            track_repo,
            file_identity_repo,
            duplicate_repo,
            duplicate_matcher,
            review_queue,
            job_queue,
            album_repo=album_repo,
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
            metadata_confidence_repo=metadata_confidence_repo,
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
            artist_repo=artist_repo,
            metadata_confidence_repo=metadata_confidence_repo,
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
        acquisition_automation_service.start()

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
            acquisition_job_repo=acquisition_job_repo,
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
            provider_manager=provider_manager,
            acquisition_engine=acquisition_engine,
            search_dispatcher=search_dispatcher,
            scoring_engine=scoring_engine,
            download_manager=download_manager,
            verification_engine=verification_engine,
            import_pipeline=import_pipeline,
            acquisition_workflow=acquisition_workflow,
            acquisition_runner=acquisition_runner,
            acquisition_automation_service=acquisition_automation_service,
            missing_media_analyzer=missing_media_analyzer,
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
        self.acquisition_automation_service.stop()
        self.database_writer.stop()
        self.engine.dispose()


def _build_metadata_providers(metadata: MetadataConfig) -> list[MetadataProvider]:
    """Construct enabled built-in metadata providers (explicit wiring —
    entry-point discovery stays a later phase)."""
    import os

    enabled = set(metadata.enabled_providers)
    providers: list[MetadataProvider] = []
    if "acoustid" in enabled:
        api_key = metadata.acoustid_api_key or os.environ.get("VAULTSEEK_ACOUSTID_API_KEY", "")
        endpoints = build_acoustid_endpoints(
            api_key=api_key,
            endpoints=metadata.acoustid_endpoints,
        )
        if endpoints:
            if len(endpoints) == 1:
                providers.append(endpoints[0])
            else:
                providers.append(AcoustIdProviderPool(endpoints))
        else:
            providers.append(AcoustIdProvider(api_key=None))
    if "musicbrainz" in enabled:
        providers.append(MusicBrainzProvider())
    if "discogs" in enabled:
        providers.append(DiscogsProvider(user_token=metadata.discogs_user_token))
    if "local_tags" in enabled:
        providers.append(LocalTagsProvider())
    if "filename_parser" in enabled:
        providers.append(FilenameParserProvider())
    return providers


def _build_artwork_providers(
    artwork: ArtworkConfig,
    *,
    discogs_user_token: str = "",
) -> list[ArtworkProvider]:
    """Construct built-in artwork providers. ``fetch_enabled`` gates only
    the network provider — embedded extraction always runs."""
    providers: list[ArtworkProvider] = []
    if artwork.fetch_enabled:
        providers.append(CoverArtArchiveProvider())
        if discogs_user_token.strip():
            providers.append(DiscogsArtworkProvider(user_token=discogs_user_token))
    providers.append(EmbeddedArtProvider())
    return providers


def _build_media_server_plugins() -> list[MediaServerPlugin]:
    """Construct built-in media-server plugins (explicit wiring)."""
    return [
        NavidromePlugin(),
        JellyfinPlugin(),
        EmbyPlugin(),
        PlexPlugin(),
        SubsonicPlugin(),
        AmpachePlugin(),
        KoelPlugin(),
        FunkwhalePlugin(),
        LyrionPlugin(),
    ]


def _build_acquisition_providers() -> list[AcquisitionProvider]:
    """Construct acquisition providers (stub + Nicotine+ skeleton)."""
    return [StubAcquisitionProvider(), NicotinePlusProvider()]


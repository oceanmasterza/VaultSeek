"""Application-wide dependency injection container.

A single :class:`Container` instance is created during application
bootstrap (see :mod:`musicvault.app`) and threaded through explicitly to
whatever needs it. There is no module-level singleton, which keeps every
component trivially testable: a test builds its own container from a
temporary directory and an in-memory configuration instead of relying on
global state.

Later phases extend this container with the job queue manager, plugin
manager, and application services as those layers are implemented (see
docs/architecture/07-roadmap.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Engine

from musicvault.core.config import AppConfig
from musicvault.core.event_bus import EventBus
from musicvault.core.paths import AppPaths
from musicvault.db.engine import create_sqlite_engine
from musicvault.db.migrations.runner import run_migrations
from musicvault.db.repositories.file_identity_repo import FileIdentityRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.rule_repo import RuleRepository


@dataclass
class Container:
    """Holds the fully wired set of application-level dependencies."""

    paths: AppPaths
    config: AppConfig
    engine: Engine
    job_repo: JobRepository
    review_repo: ReviewRepository
    rule_repo: RuleRepository
    file_identity_repo: FileIdentityRepository
    event_bus: EventBus = field(default_factory=EventBus)

    @classmethod
    def bootstrap(cls, *, paths: AppPaths, config: AppConfig) -> Container:
        """Construct a container for normal application startup.

        Runs pending Alembic migrations first — this is how the database
        file and its schema get created on first run — then opens the
        (now up-to-date) database and wires the repositories that read
        and write it.
        """
        run_migrations(paths.database_file)
        engine = create_sqlite_engine(paths.database_file)
        return cls(
            paths=paths,
            config=config,
            engine=engine,
            job_repo=JobRepository(engine),
            review_repo=ReviewRepository(engine),
            rule_repo=RuleRepository(engine),
            file_identity_repo=FileIdentityRepository(engine),
        )

    def close(self) -> None:
        """Release resources held by this container.

        Disposes the database engine's connection pool. Call this during
        application shutdown; tests should call it (or use the
        ``container`` fixture, which does) to avoid leaking SQLite
        connections across test cases.
        """
        self.engine.dispose()

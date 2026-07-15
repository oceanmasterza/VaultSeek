"""Unit tests for musicvault.core.container."""

from __future__ import annotations

from sqlalchemy import text

from musicvault.core.config import AppConfig
from musicvault.core.container import Container
from musicvault.core.event_bus import EventBus
from musicvault.core.paths import AppPaths
from musicvault.db.repositories.album_repo import AlbumRepository
from musicvault.db.repositories.artist_repo import ArtistRepository
from musicvault.db.repositories.file_identity_repo import FileIdentityRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.rule_repo import RuleRepository
from musicvault.db.repositories.track_repo import TrackRepository


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
    second = Container.bootstrap(paths=app_paths, config=app_config)

    assert first.event_bus is not second.event_bus
    first.close()
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


def test_bootstrap_is_safe_to_call_twice_against_the_same_database(
    app_paths: AppPaths, app_config: AppConfig
) -> None:
    """The second bootstrap must not fail just because migrations already ran."""
    first = Container.bootstrap(paths=app_paths, config=app_config)
    first.close()

    second = Container.bootstrap(paths=app_paths, config=app_config)

    assert app_paths.database_file.is_file()
    second.close()

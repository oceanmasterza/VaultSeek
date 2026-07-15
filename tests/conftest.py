"""Shared pytest fixtures for the MusicVault test suite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from musicvault.core.config import AppConfig, default_config
from musicvault.core.container import Container
from musicvault.core.paths import AppPaths, get_app_paths


@pytest.fixture
def app_data_dir(tmp_path: Path) -> Path:
    """Isolated base directory standing in for the real per-user profile."""
    return tmp_path / "app-data-home"


@pytest.fixture
def app_paths(app_data_dir: Path) -> AppPaths:
    """Resolved :class:`AppPaths` rooted under a temporary directory, created on disk."""
    paths = get_app_paths(base_override=app_data_dir)
    paths.ensure_created()
    return paths


@pytest.fixture
def app_config() -> AppConfig:
    """The built-in default configuration."""
    return default_config()


@pytest.fixture
def container(app_paths: AppPaths, app_config: AppConfig) -> Iterator[Container]:
    """A fully wired container using isolated test paths and default config.

    Closes the container's database engine on teardown so tests don't
    leak SQLite connections into later test cases.
    """
    built = Container.bootstrap(paths=app_paths, config=app_config)
    yield built
    built.close()

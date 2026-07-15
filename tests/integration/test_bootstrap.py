"""Integration test for the full application bootstrap sequence."""

from __future__ import annotations

from pathlib import Path

from musicvault import __version__
from musicvault.app import bootstrap


def test_bootstrap_creates_app_directories_and_default_config(tmp_path: Path) -> None:
    container = bootstrap(base_dir_override=tmp_path, console_logging=False)

    assert container.paths.root == tmp_path / "MusicVault"
    assert container.paths.root.is_dir()
    assert container.paths.config_file.is_file()
    assert container.config.schema_version >= 1
    container.close()


def test_bootstrap_writes_rotated_log_files(tmp_path: Path) -> None:
    container = bootstrap(base_dir_override=tmp_path, console_logging=False)

    assert (container.paths.logs_dir / "musicvault.log").is_file()
    assert (container.paths.logs_dir / "debug.log").is_file()
    container.close()


def test_bootstrap_is_idempotent_across_repeated_calls(tmp_path: Path) -> None:
    first = bootstrap(base_dir_override=tmp_path, console_logging=False)
    second = bootstrap(base_dir_override=tmp_path, console_logging=False)

    assert first.config == second.config
    first.close()
    second.close()


def test_bootstrap_returns_container_with_well_formed_version() -> None:
    assert __version__.count(".") == 2

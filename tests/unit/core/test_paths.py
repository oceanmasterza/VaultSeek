"""Unit tests for vaultseek.core.paths."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vaultseek.core.paths import _resolve_base_dir, get_app_paths


def test_get_app_paths_roots_under_base_override(tmp_path: Path) -> None:
    paths = get_app_paths(base_override=tmp_path)

    assert paths.root == tmp_path / "VaultSeek"


def test_get_app_paths_derives_all_locations_under_root(tmp_path: Path) -> None:
    paths = get_app_paths(base_override=tmp_path)

    for location in (
        paths.config_file,
        paths.secrets_file,
        paths.database_file,
        paths.logs_dir,
        paths.crashes_dir,
        paths.cache_dir,
        paths.backups_dir,
        paths.rollback_dir,
        paths.reports_dir,
    ):
        assert paths.root == location or paths.root in location.parents


def test_crashes_dir_is_nested_under_logs_dir(tmp_path: Path) -> None:
    paths = get_app_paths(base_override=tmp_path)

    assert paths.logs_dir in paths.crashes_dir.parents


def test_ensure_created_creates_directory_tree(tmp_path: Path) -> None:
    paths = get_app_paths(base_override=tmp_path)
    assert not paths.root.exists()

    paths.ensure_created()

    assert paths.root.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.crashes_dir.is_dir()
    assert paths.cache_dir.is_dir()
    assert paths.backups_dir.is_dir()
    assert paths.rollback_dir.is_dir()
    assert paths.reports_dir.is_dir()


def test_ensure_created_is_idempotent(tmp_path: Path) -> None:
    paths = get_app_paths(base_override=tmp_path)
    paths.ensure_created()

    paths.ensure_created()  # Must not raise on the second call

    assert paths.root.is_dir()


def test_resolve_base_dir_uses_appdata_env_var_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert _resolve_base_dir() == tmp_path


def test_resolve_base_dir_falls_back_when_appdata_unset_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)

    assert _resolve_base_dir() == Path.home() / "AppData" / "Roaming"


def test_resolve_base_dir_uses_application_support_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")

    assert _resolve_base_dir() == Path.home() / "Library" / "Application Support"


def test_resolve_base_dir_uses_xdg_data_home_on_linux(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert _resolve_base_dir() == tmp_path


def test_resolve_base_dir_falls_back_when_xdg_data_home_unset_on_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert _resolve_base_dir() == Path.home() / ".local" / "share"

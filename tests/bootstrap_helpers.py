"""Shared helpers for integration tests that exercise real bootstrap."""

from __future__ import annotations

from pathlib import Path

from vaultseek.app import bootstrap
from vaultseek.core.config import AppConfig, PipelineConfig, save_config
from vaultseek.core.container import Container
from vaultseek.core.paths import get_app_paths


def bootstrap_with_test_pipeline(tmp_path: Path) -> Container:
    """Bootstrap through the real app entry path with pipeline pools pinned
    for test stability (avoids spawning a full ProcessPool on every call)."""
    paths = get_app_paths(base_override=tmp_path)
    paths.ensure_created()
    save_config(
        AppConfig(pipeline=PipelineConfig(hash_worker_processes=1)),
        paths.config_file,
    )
    return bootstrap(base_dir_override=tmp_path, console_logging=False)

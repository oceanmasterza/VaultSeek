"""Tests for vaultseek.core.logging."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from loguru import logger

from vaultseek.core.logging import configure_logging
from vaultseek.core.paths import get_app_paths


def test_configure_logging_skips_none_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windowed PyInstaller builds set sys.stderr to None."""
    paths = get_app_paths(base_override=tmp_path)
    paths.ensure_created()
    monkeypatch.setattr(sys, "stderr", None)

    configure_logging(paths, console=True)

    logger.info("file sinks still work without a console")
    assert (paths.logs_dir / "vaultseek.log").is_file()

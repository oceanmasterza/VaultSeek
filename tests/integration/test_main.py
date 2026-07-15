"""Smoke test for the ``python -m musicvault`` entry point."""

from __future__ import annotations

from pathlib import Path

import pytest

import musicvault.__main__ as main_module
from musicvault.__main__ import main
from musicvault.core.config import AppConfig, PipelineConfig, save_config
from musicvault.core.exceptions import ConfigError
from musicvault.core.paths import get_app_paths


def test_main_returns_zero_on_successful_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    paths = get_app_paths()
    paths.ensure_created()
    save_config(
        AppConfig(pipeline=PipelineConfig(hash_worker_processes=1)),
        paths.config_file,
    )

    exit_code = main()

    assert exit_code == 0


def test_main_returns_one_and_prints_error_when_bootstrap_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _raise_config_error(**_kwargs: object) -> None:
        raise ConfigError("simulated bootstrap failure")

    monkeypatch.setattr(main_module, "bootstrap", _raise_config_error)

    exit_code = main()

    assert exit_code == 1
    assert "simulated bootstrap failure" in capsys.readouterr().err

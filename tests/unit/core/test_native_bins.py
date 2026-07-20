"""Tests for vaultseek.core.native_bins."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from vaultseek.core.native_bins import configure_native_bin_path, find_fpcalc


def test_configure_native_bin_path_prefers_fpcalc_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "fpcalc.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setenv("FPCALC", str(fake))
    monkeypatch.delenv("FPCALC_COMMAND", raising=False)

    found = configure_native_bin_path()

    assert found == fake.resolve()
    assert Path(os.environ["FPCALC"]) == fake.resolve()
    assert os.environ["FPCALC_COMMAND"] == str(fake.resolve())
    path_parts = os.environ["PATH"].split(os.pathsep)
    assert any(Path(part).resolve() == fake.parent.resolve() for part in path_parts if part)


def test_find_fpcalc_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("FPCALC", raising=False)
    monkeypatch.delenv("FPCALC_COMMAND", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(
        "vaultseek.core.native_bins.application_dir",
        lambda: tmp_path,
    )
    assert find_fpcalc() is None


def test_find_fpcalc_checks_meipass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("FPCALC", raising=False)
    monkeypatch.delenv("FPCALC_COMMAND", raising=False)
    meipass = tmp_path / "_internal"
    meipass.mkdir()
    fake = meipass / "fpcalc.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(
        "vaultseek.core.native_bins.application_dir",
        lambda: tmp_path / "empty",
    )
    assert find_fpcalc() == fake.resolve()

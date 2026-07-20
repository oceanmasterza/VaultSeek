"""Unit tests for vaultseek.plugins.builtin.chromaprint."""

from __future__ import annotations

import hashlib
from pathlib import Path

import acoustid
import pytest

from vaultseek.models.interfaces.fingerprint import FingerprintResult
from vaultseek.plugins.builtin.chromaprint import (
    ChromaprintFingerprintProvider,
    generate_chromaprint,
)


def test_generate_chromaprint_normalizes_str_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")

    monkeypatch.setattr(acoustid, "fingerprint_file", lambda _path: (42.0, "ABC123"))

    result = generate_chromaprint(audio)

    assert result == FingerprintResult(
        duration_seconds=42.0,
        fingerprint_data=b"ABC123",
        fingerprint_hash=hashlib.sha256(b"ABC123").hexdigest(),
    )


def test_generate_chromaprint_keeps_bytes_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")

    monkeypatch.setattr(acoustid, "fingerprint_file", lambda _path: (9.5, b"raw-fp"))

    result = generate_chromaprint(audio)

    assert result.fingerprint_data == b"raw-fp"
    assert result.duration_seconds == 9.5
    assert result.fingerprint_hash == hashlib.sha256(b"raw-fp").hexdigest()


def test_generate_chromaprint_translates_no_backend_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")

    def _raise(_path: str) -> tuple[float, bytes]:
        raise acoustid.NoBackendError("missing")

    monkeypatch.setattr(acoustid, "fingerprint_file", _raise)

    with pytest.raises(RuntimeError, match="Chromaprint backend not found"):
        generate_chromaprint(audio)


def test_generate_chromaprint_translates_generation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")

    def _raise(_path: str) -> tuple[float, bytes]:
        raise acoustid.FingerprintGenerationError("bad file")

    monkeypatch.setattr(acoustid, "fingerprint_file", _raise)

    with pytest.raises(RuntimeError, match="Chromaprint failed"):
        generate_chromaprint(audio)


def test_provider_delegates_to_generate_chromaprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    expected = FingerprintResult(1.0, b"fp", "hh" * 32)
    monkeypatch.setattr(
        "vaultseek.plugins.builtin.chromaprint.provider.generate_chromaprint",
        lambda _path: expected,
    )

    assert ChromaprintFingerprintProvider().fingerprint_file(audio) is expected

"""Unit tests for the embedded artwork provider."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from vaultseek.models.interfaces.artwork import ArtworkQuery
from vaultseek.plugins.builtin.embedded_art import EmbeddedArtProvider
from vaultseek.plugins.builtin.embedded_art import provider as embedded_mod


def _png(width: int = 600, height: int = 600) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(buffer, "PNG")
    return buffer.getvalue()


class _Picture:
    """Stand-in for mutagen.flac.Picture / ID3 APIC frames."""

    def __init__(self, data: bytes, mime: str = "image/png", pic_type: int = 3) -> None:
        self.data = data
        self.mime = mime
        self.type = pic_type


class _FlacLike:
    def __init__(self, pictures: list[_Picture]) -> None:
        self.pictures = pictures
        self.tags = None


class _Id3Tags:
    def __init__(self, frames: list[_Picture]) -> None:
        self._frames = frames

    def getall(self, key: str) -> list[_Picture]:
        return self._frames if key == "APIC" else []


class _Mp3Like:
    def __init__(self, frames: list[_Picture]) -> None:
        self.tags = _Id3Tags(frames)


class _Mp4Like:
    def __init__(self, covers: list[bytes]) -> None:
        self.tags = {"covr": covers}


@pytest.fixture
def audio_path(tmp_path: Path) -> Path:
    path = tmp_path / "track.flac"
    path.write_bytes(b"x")
    return path


def test_extracts_flac_front_cover(audio_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    back = _Picture(_png(100, 100), pic_type=4)
    front = _Picture(_png(600, 500), pic_type=3)
    monkeypatch.setattr(embedded_mod, "MutagenFile", lambda *_a, **_k: _FlacLike([back, front]))

    result = EmbeddedArtProvider().fetch(ArtworkQuery(file_path=str(audio_path)))

    assert result is not None
    assert result.source == "embedded_art"
    assert (result.width, result.height) == (600, 500)
    assert result.mime_type == "image/png"


def test_extracts_id3_apic_frame(audio_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedded_mod, "MutagenFile", lambda *_a, **_k: _Mp3Like([_Picture(_png())]))

    result = EmbeddedArtProvider().fetch(ArtworkQuery(file_path=str(audio_path)))

    assert result is not None
    assert (result.width, result.height) == (600, 600)


def test_extracts_mp4_covr_atom_and_sniffs_png_mime(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(embedded_mod, "MutagenFile", lambda *_a, **_k: _Mp4Like([_png()]))

    result = EmbeddedArtProvider().fetch(ArtworkQuery(file_path=str(audio_path)))

    assert result is not None
    assert result.mime_type == "image/png"


def test_returns_none_when_file_has_no_pictures(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(embedded_mod, "MutagenFile", lambda *_a, **_k: _FlacLike([]))

    assert EmbeddedArtProvider().fetch(ArtworkQuery(file_path=str(audio_path))) is None


def test_returns_none_for_undecodable_picture_bytes(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    junk = _Picture(b"not an image")
    monkeypatch.setattr(embedded_mod, "MutagenFile", lambda *_a, **_k: _FlacLike([junk]))

    assert EmbeddedArtProvider().fetch(ArtworkQuery(file_path=str(audio_path))) is None


def test_returns_none_for_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "gone.flac"
    assert EmbeddedArtProvider().fetch(ArtworkQuery(file_path=str(missing))) is None


def test_returns_none_when_mutagen_raises(
    audio_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("decode failed")

    monkeypatch.setattr(embedded_mod, "MutagenFile", _boom)
    assert EmbeddedArtProvider().fetch(ArtworkQuery(file_path=str(audio_path))) is None

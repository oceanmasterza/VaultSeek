"""Unit tests for the local embedded-tags metadata provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from musicvault.models.interfaces.metadata import MetadataQuery
from musicvault.plugins.builtin.local_tags import LocalTagsProvider
from musicvault.plugins.builtin.local_tags import provider as local_tags_mod


class _FakeAudio(dict[str, list[str]]):
    pass


def test_reads_common_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio_path = tmp_path / "track.flac"
    audio_path.write_bytes(b"x")
    fake = _FakeAudio(
        {
            "title": ["Paranoid Android"],
            "artist": ["Radiohead"],
            "album": ["OK Computer"],
            "genre": ["Rock"],
            "composer": ["Yorke"],
            "date": ["1997-05-21"],
            "tracknumber": ["3/12"],
        }
    )
    monkeypatch.setattr(local_tags_mod, "MutagenFile", lambda *_a, **_k: fake)

    result = LocalTagsProvider().lookup_by_tags(MetadataQuery(file_path=str(audio_path)))

    assert result is not None
    by_field = {f.field: f.value for f in result.fields}
    assert by_field["title"] == "Paranoid Android"
    assert by_field["artist"] == "Radiohead"
    assert by_field["year"] == 1997
    assert by_field["track_number"] == 3
    assert result.lookup_method == "tags"


def test_returns_none_for_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "gone.flac"
    assert LocalTagsProvider().lookup_by_tags(MetadataQuery(file_path=str(missing))) is None


def test_returns_none_when_mutagen_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio_path = tmp_path / "bad.flac"
    audio_path.write_bytes(b"x")

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("decode failed")

    monkeypatch.setattr(local_tags_mod, "MutagenFile", _boom)
    assert LocalTagsProvider().lookup_by_tags(MetadataQuery(file_path=str(audio_path))) is None

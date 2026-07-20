"""Unit tests for folder-trust matching helpers."""

from __future__ import annotations

from pathlib import Path

from vaultseek.plugins.builtin.musicbrainz.provider import OfficialTrack, ReleaseTracklist
from vaultseek.services.folder_trust import (
    _filename_looks_correct,
    _titles_match,
    normalize_folder_path,
)


def test_normalize_folder_path_is_casefold_parent() -> None:
    path = Path("C:/Music/Album/01 - Song.flac")
    assert normalize_folder_path(path).endswith("album")


def test_titles_match_ignores_punctuation_and_case() -> None:
    assert _titles_match("OK Computer", "ok-computer")
    assert not _titles_match("Kid A", "Amnesiac")


def test_filename_looks_correct_requires_number_and_title_tokens() -> None:
    official = OfficialTrack(number=6, title="Karma Police")
    assert _filename_looks_correct("06 - Karma Police.flac", 6, official)
    assert not _filename_looks_correct("track.flac", 6, official)


def test_release_tracklist_count() -> None:
    tracklist = ReleaseTracklist(
        release_mbid="r1",
        title="OK Computer",
        artist="Radiohead",
        tracks=(
            OfficialTrack(1, "Airbag"),
            OfficialTrack(2, "Paranoid Android"),
        ),
    )
    assert tracklist.track_count == 2

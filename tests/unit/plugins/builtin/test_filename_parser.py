"""Unit tests for the filename parser metadata provider."""

from __future__ import annotations

from vaultseek.models.interfaces.metadata import MetadataQuery
from vaultseek.plugins.builtin.filename_parser import FilenameParserProvider


def test_parses_artist_album_track_title_path() -> None:
    provider = FilenameParserProvider()
    result = provider.lookup_by_tags(
        MetadataQuery(file_path=r"C:\music\Radiohead - OK Computer\01. Airbag.flac")
    )

    assert result is not None
    by_field = {f.field: f.value for f in result.fields}
    assert by_field == {
        "artist": "Radiohead",
        "album": "OK Computer",
        "title": "Airbag",
        "track_number": 1,
    }
    assert result.lookup_method == "filename"


def test_parses_artist_title_stem() -> None:
    provider = FilenameParserProvider()
    result = provider.lookup_by_tags(MetadataQuery(file_name="Nirvana - Smells Like.flac"))

    assert result is not None
    by_field = {f.field: f.value for f in result.fields}
    assert by_field == {"artist": "Nirvana", "title": "Smells Like"}


def test_falls_back_to_title_only() -> None:
    provider = FilenameParserProvider()
    result = provider.lookup_by_tags(MetadataQuery(file_name="untitled.flac"))

    assert result is not None
    assert result.fields[0].field == "title"
    assert result.fields[0].value == "untitled"


def test_returns_none_without_path_or_name() -> None:
    assert FilenameParserProvider().lookup_by_tags(MetadataQuery()) is None

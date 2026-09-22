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


def test_skips_uuid_parent_and_parses_track_number_title() -> None:
    provider = FilenameParserProvider()
    result = provider.lookup_by_tags(
        MetadataQuery(
            file_path=(
                r"C:\Dev\Incoming\vaultseek-nicotine\\"
                r"01a090ad-7dbc-7000-b76e-66601cf1998b\10 - Soul Messiah.mp3"
            )
        )
    )
    assert result is not None
    by_field = {f.field: f.value for f in result.fields}
    assert by_field["title"] == "Soul Messiah"
    assert by_field["track_number"] == 10
    assert "artist" not in by_field


def test_pandora_lullaby_from_uuid_folder() -> None:
    provider = FilenameParserProvider()
    result = provider.lookup_by_tags(
        MetadataQuery(
            file_path=(
                r"C:\Dev\Incoming\vaultseek-nicotine\\"
                r"01a090ad-7dbc-7000-b76e-66601cf1998b\12 - Pandora's Lullaby.mp3"
            )
        )
    )
    assert result is not None
    by_field = {f.field: f.value for f in result.fields}
    assert by_field["title"] == "Pandora's Lullaby"
    assert by_field["track_number"] == 12

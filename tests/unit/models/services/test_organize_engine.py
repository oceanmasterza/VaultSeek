"""Unit tests for musicvault.models.services.organize_engine."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePath
from uuid import UUID

import pytest

from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.library import Library
from musicvault.models.entities.track import LibraryZone, Track
from musicvault.models.services.organize_engine import (
    ALLOWED_TRANSITIONS,
    OrganizeEngine,
    sanitize_component,
)

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


def _library(library_id: UUID | None = None) -> Library:
    return Library(
        id=library_id or generate_uuid7(),
        name="Test Library",
        incoming_path="C:/vault/Incoming",
        staging_path="C:/vault/Staging",
        library_path="C:/vault/Music",
        archive_path="C:/vault/Archive",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _track(**overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": generate_uuid7(),
        "zone": LibraryZone.INCOMING,
        "file_path": "C:/vault/Incoming/raw_file.flac",
        "file_name": "raw_file.flac",
        "file_size": 1024,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def engine() -> OrganizeEngine:
    return OrganizeEngine()


class TestTransitions:
    def test_documented_transitions_are_allowed(self, engine: OrganizeEngine) -> None:
        assert engine.can_transition(LibraryZone.INCOMING, LibraryZone.STAGING)
        assert engine.can_transition(LibraryZone.STAGING, LibraryZone.LIBRARY)
        assert engine.can_transition(LibraryZone.STAGING, LibraryZone.INCOMING)
        assert engine.can_transition(LibraryZone.LIBRARY, LibraryZone.ARCHIVE)
        assert engine.can_transition(LibraryZone.ARCHIVE, LibraryZone.LIBRARY)

    def test_archive_extension_transitions_are_allowed(self, engine: OrganizeEngine) -> None:
        """Incoming/staging -> archive keep the shipped archive-MP3 rule actionable."""
        assert engine.can_transition(LibraryZone.INCOMING, LibraryZone.ARCHIVE)
        assert engine.can_transition(LibraryZone.STAGING, LibraryZone.ARCHIVE)

    def test_forbidden_transitions(self, engine: OrganizeEngine) -> None:
        assert not engine.can_transition(LibraryZone.INCOMING, LibraryZone.LIBRARY)
        assert not engine.can_transition(LibraryZone.LIBRARY, LibraryZone.STAGING)
        assert not engine.can_transition(LibraryZone.LIBRARY, LibraryZone.INCOMING)
        assert not engine.can_transition(LibraryZone.ARCHIVE, LibraryZone.STAGING)
        assert not engine.can_transition(LibraryZone.ARCHIVE, LibraryZone.INCOMING)

    def test_every_zone_has_a_transition_entry(self) -> None:
        assert set(ALLOWED_TRANSITIONS) == set(LibraryZone)

    def test_validate_transition_raises_with_allowed_list(self, engine: OrganizeEngine) -> None:
        with pytest.raises(ValueError, match="incoming -> library"):
            engine.validate_transition(LibraryZone.INCOMING, LibraryZone.LIBRARY)


class TestDestinationPath:
    def test_full_template_with_artist_album_year_and_track_number(
        self, engine: OrganizeEngine
    ) -> None:
        track = _track(title="Karma Police", track_number=6, year=1997)

        path = engine.destination_path(
            _library(),
            LibraryZone.LIBRARY,
            track,
            artist_name="Radiohead",
            album_title="OK Computer",
            album_year=1997,
        )

        assert path == PurePath(
            "C:/vault/Music/Radiohead/1997 - OK Computer/06 - Karma Police.flac"
        )

    def test_missing_artist_falls_back_to_unknown_artist(self, engine: OrganizeEngine) -> None:
        track = _track(title="Mystery Song")

        path = engine.destination_path(_library(), LibraryZone.STAGING, track)

        assert path == PurePath("C:/vault/Staging/Unknown Artist/Mystery Song.flac")

    def test_missing_album_skips_the_album_folder(self, engine: OrganizeEngine) -> None:
        track = _track(title="Single", track_number=1)

        path = engine.destination_path(_library(), LibraryZone.LIBRARY, track, artist_name="Artist")

        assert path == PurePath("C:/vault/Music/Artist/01 - Single.flac")

    def test_album_without_year_uses_track_year_then_bare_album(
        self, engine: OrganizeEngine
    ) -> None:
        with_track_year = engine.destination_path(
            _library(),
            LibraryZone.LIBRARY,
            _track(title="T", year=2001),
            artist_name="A",
            album_title="Album",
        )
        without_any_year = engine.destination_path(
            _library(),
            LibraryZone.LIBRARY,
            _track(title="T"),
            artist_name="A",
            album_title="Album",
        )

        assert with_track_year == PurePath("C:/vault/Music/A/2001 - Album/T.flac")
        assert without_any_year == PurePath("C:/vault/Music/A/Album/T.flac")

    def test_missing_title_keeps_the_original_filename(self, engine: OrganizeEngine) -> None:
        track = _track(file_name="raw_file.flac")

        path = engine.destination_path(_library(), LibraryZone.STAGING, track, artist_name="Artist")

        assert path == PurePath("C:/vault/Staging/Artist/raw_file.flac")

    def test_moves_to_incoming_keep_a_flat_filename(self, engine: OrganizeEngine) -> None:
        track = _track(title="Ignored For Incoming")

        path = engine.destination_path(
            _library(), LibraryZone.INCOMING, track, artist_name="Artist"
        )

        assert path == PurePath("C:/vault/Incoming/raw_file.flac")

    def test_components_are_sanitized_for_windows(self, engine: OrganizeEngine) -> None:
        track = _track(title='What: A "Song"?', track_number=2)

        path = engine.destination_path(
            _library(),
            LibraryZone.LIBRARY,
            track,
            artist_name="AC/DC",
            album_title="Back <in> Black.",
        )

        assert path == PurePath("C:/vault/Music/AC_DC/Back _in_ Black/02 - What_ A _Song__.flac")


class TestSanitizeComponent:
    def test_replaces_reserved_characters(self) -> None:
        assert sanitize_component('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"

    def test_strips_trailing_dots_and_spaces(self) -> None:
        assert sanitize_component("Album. ") == "Album"

    def test_collapses_whitespace(self) -> None:
        assert sanitize_component("Too   many\tspaces") == "Too many spaces"

    def test_empty_input_stays_empty(self) -> None:
        assert sanitize_component("  .. ") == ""

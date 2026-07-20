"""Unit tests for vaultseek.models.services.rename_engine.

Mirrors docs/architecture/09-testing-strategy.md ("Domain Layer",
`TestRenameEngine`) exactly, plus additional coverage cases.
"""

from __future__ import annotations

import pytest

from vaultseek.models.services.rename_engine import RenameEngine


class TestRenameEngine:
    @pytest.mark.parametrize(
        ("input_name", "expected"),
        [
            (
                "Allen_Watts_-_Indicator-(KR147)-SINGLE-16BIT-WEB-FLAC-2024-FMC",
                "Allen Watts - Indicator",
            ),
            ("Artist_-_Album-[AFO]-WEB-FLAC", "Artist - Album"),
            ("01_-_Track_Name", "01 - Track Name"),
        ],
    )
    def test_cleans_scene_names(self, input_name: str, expected: str) -> None:
        assert RenameEngine().clean_filename(input_name) == expected

    def test_filename_with_no_scene_tag_block_is_unchanged_besides_underscores(self) -> None:
        assert RenameEngine().clean_filename("Artist_-_Title") == "Artist - Title"

    def test_only_the_first_scene_tag_block_is_the_cut_point(self) -> None:
        assert RenameEngine().clean_filename("Artist_-_Title-(TAG1)-[TAG2]") == "Artist - Title"

    def test_empty_string_returns_empty_string(self) -> None:
        assert RenameEngine().clean_filename("") == ""

    def test_already_clean_filename_is_unchanged(self) -> None:
        assert RenameEngine().clean_filename("Artist - Title") == "Artist - Title"

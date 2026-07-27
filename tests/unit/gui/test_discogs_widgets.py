"""Tests for Discogs browse UI helpers."""

from vaultseek.gui.widgets.discogs_widgets import release_subtitle, release_tooltip


def test_release_subtitle_includes_format_and_kind() -> None:
    text = release_subtitle(kind="master", format_text="Album, CD", role="Main")
    assert "Master" in text
    assert "Album, CD" in text
    assert "Main" not in text


def test_release_subtitle_shows_non_main_role() -> None:
    text = release_subtitle(kind="release", format_text="Single", role="Appearance")
    assert "Appearance" in text


def test_release_tooltip_multiline() -> None:
    tip = release_tooltip(
        artist="Queen",
        format_text="LP",
        kind="release",
        role="Main",
        secondary="In collection: 100 · Want: 50",
    )
    assert "Queen" in tip
    assert "LP" in tip
    assert "In collection" in tip

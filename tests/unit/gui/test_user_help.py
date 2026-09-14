"""Tests for bundled user help resolution."""

from pathlib import Path

from vaultseek.gui.user_help import help_html_path

_REQUIRED_HELP_ANCHORS = (
    "overview",
    "first-run",
    "where-settings",
    "choose-source",
    "acquisition-flow",
    "waterfall",
    "nicotine",
    "prowlarr",
    "lastfm-spotify",
    "settings",
    "plugins",
    "quality",
    "troubleshooting",
)


def test_help_html_path_finds_repo_docs() -> None:
    path = help_html_path()
    assert path is not None
    assert path.name == "HELP.html"
    assert path.is_file()
    repo_root = Path(__file__).resolve().parents[3]
    assert path.resolve() == (repo_root / "docs" / "HELP.html").resolve()


def test_help_html_covers_settings_and_download_options() -> None:
    path = help_html_path()
    assert path is not None
    html = path.read_text(encoding="utf-8")
    for anchor in _REQUIRED_HELP_ANCHORS:
        assert f'id="{anchor}"' in html, f"missing help section #{anchor}"
    assert "Save library" in html
    assert "Save plugin settings" in html
    assert "Wishlist &amp; downloads" in html
    assert "Soulseek only" in html
    assert "Torrents only" in html
    assert "Usenet only" in html

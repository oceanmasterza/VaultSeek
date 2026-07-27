"""Tests for bundled user help resolution."""

from pathlib import Path

from vaultseek.gui.user_help import help_html_path


def test_help_html_path_finds_repo_docs() -> None:
    path = help_html_path()
    assert path is not None
    assert path.name == "HELP.html"
    assert path.is_file()
    repo_root = Path(__file__).resolve().parents[3]
    assert path.resolve() == (repo_root / "docs" / "HELP.html").resolve()

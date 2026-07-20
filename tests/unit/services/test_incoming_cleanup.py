"""Tests for Incoming leftover cleanup after organize."""

from __future__ import annotations

from pathlib import Path

from vaultseek.services.incoming_cleanup import cleanup_incoming_after_move


def test_cleanup_removes_sidecars_and_empty_album_folder(tmp_path: Path) -> None:
    incoming = tmp_path / "Incoming"
    album = incoming / "Artist" / "Album"
    album.mkdir(parents=True)
    audio = album / "01 - Track.flac"
    audio.write_bytes(b"flac")
    (album / "album.nfo").write_text("nfo")
    (album / "file.sfv").write_text("sfv")
    (album / "folder.jpg").write_bytes(b"jpg")
    (album / "playlist.m3u").write_text("#EXTM3U")

    # Simulate move: audio already gone from Incoming
    audio.unlink()

    deleted = cleanup_incoming_after_move(audio, incoming)

    assert not album.exists()
    assert not (incoming / "Artist").exists()
    assert incoming.is_dir()
    assert any(path.endswith("album.nfo") for path in deleted)
    assert any(path.endswith("folder.jpg") for path in deleted)


def test_cleanup_keeps_folder_when_sibling_audio_remains(tmp_path: Path) -> None:
    incoming = tmp_path / "Incoming"
    album = incoming / "Album"
    album.mkdir(parents=True)
    moved = album / "01.flac"
    sibling = album / "02.flac"
    moved.write_bytes(b"a")
    sibling.write_bytes(b"b")
    (album / "cover.jpg").write_bytes(b"jpg")
    moved.unlink()

    deleted = cleanup_incoming_after_move(moved, incoming)

    assert deleted == []
    assert sibling.is_file()
    assert (album / "cover.jpg").is_file()
    assert album.is_dir()


def test_cleanup_ignores_paths_outside_incoming(tmp_path: Path) -> None:
    incoming = tmp_path / "Incoming"
    incoming.mkdir()
    other = tmp_path / "Elsewhere" / "Album" / "01.flac"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"x")
    other.unlink()

    assert cleanup_incoming_after_move(other, incoming) == []


def test_cleanup_clears_junk_in_incoming_root_when_no_audio_left(tmp_path: Path) -> None:
    incoming = tmp_path / "Incoming"
    incoming.mkdir()
    audio = incoming / "lonely.flac"
    audio.write_bytes(b"flac")
    junk = incoming / "readme.nfo"
    junk.write_text("nfo")
    audio.unlink()

    deleted = cleanup_incoming_after_move(audio, incoming)

    assert incoming.is_dir()
    assert not junk.exists()
    assert any(path.endswith("readme.nfo") for path in deleted)

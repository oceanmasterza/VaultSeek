"""Clean leftover Incoming junk after audio files are organized away.

When the last audio file leaves an album/scene folder under Incoming,
sidecars (``.nfo``, ``.sfv``, loose cover art, playlists, …) and the
now-empty folder tree are removed. The Incoming root itself is never
deleted. Folders that still contain audio are left untouched.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

# Same audio set the scanner recognizes — keep in sync with scanner_worker.
_AUDIO_EXTENSIONS = frozenset(
    {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".ape", ".wv"}
)


def cleanup_incoming_after_move(moved_from: Path, incoming_root: Path) -> list[str]:
    """Remove leftover non-audio files/folders under Incoming after a move.

    ``moved_from`` is the path the audio file occupied *before* the move
    (the parent folder may still hold siblings or junk).

    Returns the list of deleted paths (files and directories) for logging.
    """
    try:
        incoming = incoming_root.resolve()
        start = moved_from.parent.resolve()
    except OSError as exc:
        logger.warning("Incoming cleanup skipped (resolve failed): {}", exc)
        return []

    if not _is_under_or_equal(start, incoming):
        return []
    if start == incoming:
        # Only clear loose junk beside files in the Incoming root when no
        # audio remains there; never remove the root directory.
        if _directory_has_audio(incoming):
            return []
        return _delete_non_audio_files(incoming)

    # Walk from the album folder upward: clean each level that has no audio left.
    deleted: list[str] = []
    current = start
    while True:
        if not current.exists() or not current.is_dir():
            break
        if not _is_under_or_equal(current, incoming) or current == incoming:
            break
        if _tree_has_audio(current):
            break
        deleted.extend(_wipe_non_audio_tree(current))
        parent = current.parent
        # current may already be gone; continue upward
        current = parent
    return deleted


def _is_under_or_equal(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _AUDIO_EXTENSIONS


def _directory_has_audio(directory: Path) -> bool:
    try:
        return any(_is_audio(child) for child in directory.iterdir())
    except OSError:
        return False


def _tree_has_audio(directory: Path) -> bool:
    try:
        for path in directory.rglob("*"):
            if _is_audio(path):
                return True
    except OSError:
        return False
    return False


def _delete_non_audio_files(directory: Path) -> list[str]:
    deleted: list[str] = []
    try:
        children = list(directory.iterdir())
    except OSError:
        return deleted
    for child in children:
        if not child.is_file():
            continue
        if _is_audio(child):
            continue
        try:
            child.unlink(missing_ok=True)
            deleted.append(str(child))
        except OSError as exc:
            logger.warning("Could not delete leftover {}: {}", child, exc)
    return deleted


def _wipe_non_audio_tree(directory: Path) -> list[str]:
    """Delete all files under ``directory``, then remove empty dirs bottom-up."""
    deleted: list[str] = []
    try:
        entries = sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True)
    except OSError:
        return deleted
    for path in entries:
        try:
            if path.is_file() or path.is_symlink():
                if _is_audio(path):
                    continue
                path.unlink(missing_ok=True)
                deleted.append(str(path))
            elif path.is_dir():
                path.rmdir()
                deleted.append(str(path))
        except OSError as exc:
            logger.debug("Incoming cleanup could not remove {}: {}", path, exc)
    try:
        if directory.exists():
            directory.rmdir()
            deleted.append(str(directory))
    except OSError as exc:
        logger.debug("Incoming cleanup left folder {}: {}", directory, exc)
    return deleted

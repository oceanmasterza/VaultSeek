"""Write embedded audio tags from VaultSeek identity fields (Mutagen).

Backs up the original file under ``%APPDATA%\\VaultSeek\\tag-backups`` (or an
explicit backup dir), writes via a temporary sibling, then atomically replaces.
Unrelated tags and embedded art are preserved (easy tags only overwrite named
fields). Identical requested tags are a no-op (no backup, no mtime churn).
Callers must treat ``wrote=False`` as fail-closed.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from loguru import logger

_MIN_TRACK_OR_DISC = 1
_YEAR_MIN = 1000
_YEAR_MAX = 9999


@dataclass(frozen=True, slots=True)
class TagWriteRequest:
    """Fields to embed into an audio file."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    year: int | None = None


@dataclass(frozen=True, slots=True)
class TagWriteResult:
    """Outcome of one tag write attempt.

    ``wrote=True`` means success (including an idempotent no-op). ``changed``
    is True only when the file was rewritten.
    """

    path: str
    wrote: bool
    error: str | None = None
    backup_path: str | None = None
    changed: bool = False


def write_embedded_tags(
    path: str,
    request: TagWriteRequest,
    *,
    backup_dir: Path | str | None = None,
) -> TagWriteResult:
    """Persist identity tags into ``path`` with backup + temp replace."""
    cleaned, validation_error = _validate_request(request)
    if cleaned is None:
        return TagWriteResult(
            path=path,
            wrote=False,
            error=validation_error or "empty tag request",
        )

    target = Path(path)
    if not target.is_file():
        return TagWriteResult(path=path, wrote=False, error="file missing")
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return TagWriteResult(path=path, wrote=False, error="mutagen unavailable")

    try:
        existing = MutagenFile(str(target), easy=True)
        if existing is None or not hasattr(existing, "__setitem__"):
            return TagWriteResult(path=path, wrote=False, error="unsupported format")
        if _tags_already_match(existing, cleaned):
            return TagWriteResult(path=path, wrote=True, changed=False)
        snapshot = _file_snapshot(target)
    except Exception as exc:  # noqa: BLE001 — mutagen / filesystem boundary
        logger.warning("Tag inspect failed for {}: {}", path, exc)
        return TagWriteResult(path=path, wrote=False, error=str(exc))

    backup_root = Path(backup_dir) if backup_dir is not None else _default_backup_dir()
    backup_path: Path | None = None
    tmp_path: Path | None = None
    replaced = False
    try:
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_path = _allocate_backup_path(backup_root, target)
        shutil.copy2(target, backup_path)
        _write_backup_identity(backup_path, target)
    except OSError as exc:
        _cleanup_path(tmp_path)
        return TagWriteResult(path=path, wrote=False, error=f"backup failed: {exc}")

    try:
        with tempfile.NamedTemporaryFile(
            dir=str(target.parent),
            prefix=f".{target.stem}.tagwrite-",
            suffix=target.suffix,
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
        shutil.copy2(target, tmp_path)
        audio = MutagenFile(str(tmp_path), easy=True)
        if audio is None or not hasattr(audio, "__setitem__"):
            return TagWriteResult(
                path=path,
                wrote=False,
                error="unsupported format",
                backup_path=str(backup_path),
            )
        _apply_tags(audio, cleaned)
        audio.save()
        if _file_snapshot(target) != snapshot:
            return TagWriteResult(
                path=path,
                wrote=False,
                error="source modified during tag write",
                backup_path=str(backup_path),
            )
        os.replace(str(tmp_path), str(target))
        replaced = True
        tmp_path = None
    except Exception as exc:  # noqa: BLE001 — mutagen / filesystem boundary
        logger.warning("Tag write failed for {}: {}", path, exc)
        if replaced:
            # Source was already swapped; restore from the backup we just made.
            with contextlib.suppress(OSError):
                if backup_path is not None:
                    shutil.copy2(backup_path, target)
        return TagWriteResult(
            path=path,
            wrote=False,
            error=str(exc),
            backup_path=str(backup_path) if backup_path is not None else None,
        )
    finally:
        _cleanup_path(tmp_path)

    return TagWriteResult(
        path=path,
        wrote=True,
        backup_path=str(backup_path),
        changed=True,
    )


def _validate_request(
    request: TagWriteRequest,
) -> tuple[TagWriteRequest | None, str | None]:
    """Reject empty or corruptible field values; return a cleaned request."""
    title = _clean_text(request.title)
    artist = _clean_text(request.artist)
    album = _clean_text(request.album)

    if request.title is not None and title is None:
        return None, "invalid title"
    if request.artist is not None and artist is None:
        return None, "invalid artist"
    if request.album is not None and album is None:
        return None, "invalid album"

    if request.track_number is not None and request.track_number < _MIN_TRACK_OR_DISC:
        return None, "invalid track_number"
    if request.disc_number is not None and request.disc_number < _MIN_TRACK_OR_DISC:
        return None, "invalid disc_number"
    if request.year is not None and not (_YEAR_MIN <= request.year <= _YEAR_MAX):
        return None, "invalid year"

    cleaned = TagWriteRequest(
        title=title,
        artist=artist,
        album=album,
        track_number=request.track_number,
        disc_number=request.disc_number,
        year=request.year,
    )
    if not _request_has_fields(cleaned):
        return None, "empty tag request"
    return cleaned, None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _request_has_fields(request: TagWriteRequest) -> bool:
    return any(
        (
            request.title is not None,
            request.artist is not None,
            request.album is not None,
            request.track_number is not None,
            request.disc_number is not None,
            request.year is not None,
        )
    )


def _tags_already_match(audio: object, request: TagWriteRequest) -> bool:
    """True when every requested field already equals the embedded value."""
    checks: list[bool] = []
    if request.title is not None:
        checks.append(_text_tag(audio, "title") == request.title)
    if request.artist is not None:
        checks.append(_text_tag(audio, "artist") == request.artist)
    if request.album is not None:
        checks.append(_text_tag(audio, "album") == request.album)
    if request.track_number is not None:
        checks.append(_number_tag(audio, "tracknumber") == str(request.track_number))
    if request.disc_number is not None:
        checks.append(_number_tag(audio, "discnumber") == str(request.disc_number))
    if request.year is not None:
        checks.append(_year_tag(audio) == str(request.year))
    return all(checks)


def _text_tag(audio: object, key: str) -> str | None:
    raw = _first_tag_value(audio, key)
    return _clean_text(raw)


def _number_tag(audio: object, key: str) -> str | None:
    raw = _first_tag_value(audio, key)
    if raw is None:
        return None
    head = raw.strip().split("/", 1)[0].strip()
    return head or None


def _year_tag(audio: object) -> str | None:
    raw = _first_tag_value(audio, "date")
    if raw is None:
        return None
    text = raw.strip()
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return text or None


def _first_tag_value(audio: object, key: str) -> str | None:
    getter = getattr(audio, "get", None)
    if not callable(getter):
        return None
    try:
        values = getter(key)
    except Exception:  # noqa: BLE001 — mutagen tag read boundary
        return None
    if not values:
        return None
    return str(values[0])


def _file_snapshot(path: Path) -> tuple[int, int]:
    """Identity used to detect concurrent modification before replace."""
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _apply_tags(audio: object, request: TagWriteRequest) -> None:
    """Write only provided identity fields onto a Mutagen easy file."""
    tags = cast(MutableMapping[str, list[str]], audio)
    if request.title is not None:
        tags["title"] = [request.title]
    if request.artist is not None:
        tags["artist"] = [request.artist]
    if request.album is not None:
        tags["album"] = [request.album]
    if request.track_number is not None:
        tags["tracknumber"] = [str(request.track_number)]
    if request.disc_number is not None:
        tags["discnumber"] = [str(request.disc_number)]
    if request.year is not None:
        tags["date"] = [str(request.year)]


def _allocate_backup_path(backup_root: Path, target: Path) -> Path:
    """Create a unique backup path; never overwrite an existing backup."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = _safe_filename_component(target.stem) or "audio"
    suffix = target.suffix
    # uuid4 makes same-basename / same-second / cross-folder writes collide-proof.
    for _ in range(32):
        token = uuid4().hex[:12]
        candidate = backup_root / f"{stem}.{stamp}.{token}{suffix}.bak"
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        else:
            os.close(fd)
            return candidate
    raise OSError("unable to allocate unique backup path")


def _write_backup_identity(backup_path: Path, source: Path) -> None:
    """Sidecar so a backup can be traced back to its absolute source path."""
    meta_path = Path(f"{backup_path}.source.json")
    payload = {
        "source_path": str(source.resolve()),
        "source_name": source.name,
        "backup_path": str(backup_path),
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _safe_filename_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)
    return cleaned.strip("._")[:80]


def _cleanup_path(path: Path | None) -> None:
    if path is None:
        return
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _default_backup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "VaultSeek" / "tag-backups"
    return Path.home() / ".vaultseek" / "tag-backups"

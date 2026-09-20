"""Labels and playability for the Review queue.

Fingerprint misses often store an id fragment as the title. The queue should
still show a filename or embedded tag so a person can recognise the song, and
it should omit rows that have no local audio file to play.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from vaultseek.models.entities.review_item import ReviewItem
from vaultseek.models.entities.track import Track

_OPAQUE_ID = re.compile(
    r"^(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[0-9a-f]{8,})$",
    re.IGNORECASE,
)
_TRACK_PREFIX = re.compile(r"^(?:\d{1,3}\s*[-._)]\s*)+")
_STATUS_PREFIXES = (
    "no artwork",
    "not on soulseek",
    "unknown or low-confidence",
    "needs review",
    "providers disagree",
    "rule requires",
    "rule:",
    "rule wants",
)


@dataclass(frozen=True, slots=True)
class PlayableReview:
    """One Review row that can be heard from the page."""

    item_id: UUID
    review_type: str
    label: str
    confidence: float | None
    reason: str
    audio_path: str


def looks_like_opaque_id(value: str) -> bool:
    """True for UUIDs and hex fragments that are not song titles."""
    return bool(_OPAQUE_ID.fullmatch(value.strip()))


def filename_song(file_name: str) -> str:
    """Drop the extension and a leading track number."""
    stem = Path(file_name).stem.strip()
    cleaned = _TRACK_PREFIX.sub("", stem).strip(" .-_")
    return cleaned or stem


def human_song_label(
    *,
    file_name: str,
    tag_title: str | None = None,
    tag_artist: str | None = None,
    stored_title: str = "",
) -> str:
    """Prefer a real tag, then the filename, over ids and status sentences."""
    title = (tag_title or "").strip()
    if not title or looks_like_opaque_id(title):
        title = filename_song(file_name)
    if not title or looks_like_opaque_id(title):
        stored = stored_title.strip()
        if stored and not looks_like_opaque_id(stored) and not _is_status_sentence(stored):
            title = stored
    if not title:
        title = filename_song(file_name) or "Untitled audio"
    artist = (tag_artist or "").strip()
    if artist and not looks_like_opaque_id(artist):
        return f"{artist} — {title}"
    return title


def select_playable_reviews(
    items: Sequence[ReviewItem],
    *,
    track_for: Callable[[UUID], Track | None],
    artist_name: Callable[[UUID], str | None],
    duplicate_track_ids: Callable[[UUID], Sequence[UUID]],
    file_exists: Callable[[str], bool] | None = None,
    read_tags: Callable[[str], tuple[str | None, str | None]] | None = None,
) -> list[PlayableReview]:
    """Keep only reviews whose audio file is on disk."""
    exists = file_exists or _path_is_file
    tags_of = read_tags or embedded_tag_identity
    rows: list[PlayableReview] = []
    for item in items:
        track = _first_playable_track(
            item,
            track_for=track_for,
            duplicate_track_ids=duplicate_track_ids,
            file_exists=exists,
        )
        if track is None:
            continue
        tag_title, tag_artist = tags_of(track.file_path)
        if not tag_title and track.title and not looks_like_opaque_id(track.title):
            tag_title = track.title
        if not tag_artist and track.artist_id is not None:
            tag_artist = artist_name(track.artist_id)
        rows.append(
            PlayableReview(
                item_id=item.id,
                review_type=item.review_type.value,
                label=human_song_label(
                    file_name=track.file_name or Path(track.file_path).name,
                    tag_title=tag_title,
                    tag_artist=tag_artist,
                    stored_title=item.title,
                ),
                confidence=(
                    item.confidence if item.confidence is not None else track.overall_confidence
                ),
                reason=item.description or "",
                audio_path=track.file_path,
            )
        )
    return rows


def embedded_tag_identity(path: str) -> tuple[str | None, str | None]:
    """Read title and artist from an audio file. Missing tags return None."""
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return None, None
    try:
        audio = MutagenFile(path, easy=True)
    except Exception:
        return None, None
    if audio is None:
        return None, None
    return _first_tag(audio, "title"), _first_tag(audio, "artist")


def _first_playable_track(
    item: ReviewItem,
    *,
    track_for: Callable[[UUID], Track | None],
    duplicate_track_ids: Callable[[UUID], Sequence[UUID]],
    file_exists: Callable[[str], bool],
) -> Track | None:
    ids: list[UUID] = []
    if item.track_id is not None:
        ids.append(item.track_id)
    elif item.duplicate_group_id is not None:
        ids.extend(duplicate_track_ids(item.duplicate_group_id))
    for track_id in ids:
        track = track_for(track_id)
        if track is not None and track.file_path and file_exists(track.file_path):
            return track
    return None


def _path_is_file(path: str) -> bool:
    try:
        return Path(path).is_file()
    except OSError:
        return False


def _is_status_sentence(value: str) -> bool:
    lowered = value.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _STATUS_PREFIXES)


def _first_tag(audio: object, key: str) -> str | None:
    getter = getattr(audio, "get", None)
    if getter is None:
        return None
    try:
        values = getter(key)
    except Exception:
        return None
    if not values:
        return None
    text = str(values[0]).strip()
    return text or None

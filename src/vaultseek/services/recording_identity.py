"""Strict recording / version identity helpers for matching and scoring.

Public API used by library tracklist matching and QUALITY_UPGRADE scoring so
auto-acquire never starts an explicitly contradictory recording.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from rapidfuzz import fuzz

from vaultseek.models.interfaces.acquisition import SearchResult

_TITLE_SCORE_MIN = 82.0
_PAREN = re.compile(r"\s*[\(\[]([^\)\]]+)[\)\]]")
_VERSION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("live", re.compile(r"\b(live|concert|unplugged)\b", re.IGNORECASE)),
    (
        "remix",
        re.compile(
            r"\b(remix|rmx|bootleg|(?:radio|club|extended)\s+mix)\b",
            re.IGNORECASE,
        ),
    ),
    ("demo", re.compile(r"\bdemo\b", re.IGNORECASE)),
    ("acoustic", re.compile(r"\bacoustic\b", re.IGNORECASE)),
    ("instrumental", re.compile(r"\binstrumental\b", re.IGNORECASE)),
)
_NAMED_MIX = re.compile(
    r"\(([^)]*?\b(?:mix|edit|remix)[^)]*)\)",
    re.IGNORECASE,
)
_TRACK_NUM_PREFIX = re.compile(r"^\d{1,3}\s*[-._ ]+\s*")
_AUDIO_EXTENSIONS = frozenset(
    {
        ".flac",
        ".mp3",
        ".m4a",
        ".aac",
        ".ogg",
        ".opus",
        ".wav",
        ".aiff",
        ".aif",
        ".alac",
        ".wma",
        ".ape",
        ".wv",
        ".mpc",
        ".tak",
        ".dsf",
        ".dff",
    }
)


def normalize_recording_title(value: str) -> str:
    """Collapse whitespace / punctuation noise for title comparison."""
    cleaned = re.sub(r"[^\w\s]", " ", value.casefold())
    return " ".join(cleaned.split())


def version_kind(title: str) -> str:
    """Classify a recording title as studio / live / remix / demo / …"""
    # Any explicit mix/edit parenthetical is a distinct variant of studio.
    if named_mix(title) is not None:
        return "remix"
    for kind, pattern in _VERSION_PATTERNS:
        if pattern.search(title):
            return kind
    return "studio"


def versions_conflict(incoming: str, slot: str) -> bool:
    """True when two version kinds cannot be the same recording."""
    if incoming == slot:
        return False
    if incoming == "studio" and slot != "studio":
        return True
    if slot == "studio" and incoming != "studio":
        return True
    return incoming != slot


def named_mix(title: str) -> str | None:
    match = _NAMED_MIX.search(title)
    if match is None:
        return None
    return normalize_recording_title(match.group(1))


def split_recording_base(title: str) -> tuple[str, str | None]:
    mix = named_mix(title)
    base = _PAREN.sub("", title).strip()
    return base or title, mix


def recordings_compatible(job_title: str, candidate_title: str) -> bool:
    """True when candidate is the same recording (base + version) as the job."""
    job_base, job_mix = split_recording_base(job_title)
    cand_base, cand_mix = split_recording_base(candidate_title)
    if fuzz.ratio(normalize_recording_title(job_base), normalize_recording_title(cand_base)) < (
        _TITLE_SCORE_MIN
    ):
        return False
    if versions_conflict(version_kind(job_title), version_kind(candidate_title)):
        return False
    # One side bare studio, the other an explicit mix/edit — keep variants apart.
    if bool(job_mix) != bool(cand_mix):
        return False
    return not (job_mix and cand_mix and job_mix != cand_mix)


def recording_label_from_search_result(result: SearchResult) -> str | None:
    """Best-effort single-recording title from a search hit.

    Prefers ``result.title``. Falls back to an audio-file basename with a
    leading track number and optional ``Artist - `` prefix stripped. Never
    returns a whole-folder display string — those are album packs.
    """
    if result.title and result.title.strip():
        return result.title.strip()
    stem = _audio_file_stem(result)
    if stem is None:
        return None
    return _strip_artist_prefix(stem, result.artist)


def is_album_pack_without_track(result: SearchResult) -> bool:
    """True for torrent/NZB/folder album packs that do not name one recording."""
    if recording_label_from_search_result(result) is not None:
        return False
    if result.track_count is not None and result.track_count > 1:
        return True
    # Folder / release name without an audio extension.
    raw = result.raw or {}
    for candidate in (
        str(raw.get("file_path") or ""),
        str(raw.get("virtual_path") or ""),
        result.display_name or "",
    ):
        name = candidate.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        if not name:
            continue
        suffix = PurePosixPath(name).suffix.casefold()
        if suffix and suffix in _AUDIO_EXTENSIONS:
            return False
        if (
            suffix
            and suffix not in _AUDIO_EXTENSIONS
            and result.track_count
            and result.track_count > 1
        ):
            # .nzb / .torrent style release names count as packs when multi-track.
            return True
        if not suffix and (result.album or result.track_count):
            return True
    return bool(result.album and result.track_count and result.track_count > 1)


def quality_upgrade_result_compatible(job_title: str, result: SearchResult) -> bool:
    """Whether a QUALITY_UPGRADE hit may be auto-started for ``job_title``.

    Explicit recording titles (including single-file basenames that still
    advertise a sibling ``track_count``) must match. True album packs without
    a per-track title remain eligible for whole-album download.
    """
    label = recording_label_from_search_result(result)
    if label is not None:
        return recordings_compatible(job_title, label)
    return is_album_pack_without_track(result)


def _audio_file_stem(result: SearchResult) -> str | None:
    raw = result.raw or {}
    candidates = [
        str(raw.get("file_path") or ""),
        str(raw.get("virtual_path") or ""),
        result.display_name or "",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        name = candidate.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        path = PurePosixPath(name)
        if path.suffix.casefold() not in _AUDIO_EXTENSIONS:
            continue
        stem = _TRACK_NUM_PREFIX.sub("", path.stem).strip()
        return stem or None
    return None


def _strip_artist_prefix(label: str, artist: str | None) -> str:
    """``Live - All Over You`` with artist Live → ``All Over You``."""
    if not artist or " - " not in label:
        return label
    left, right = label.split(" - ", 1)
    if normalize_recording_title(left) == normalize_recording_title(artist):
        return right.strip() or label
    return label

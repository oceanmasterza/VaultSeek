"""OrganizeEngine — zone state machine + destination-path computation.

Pure (no I/O): validates zone transitions and computes where a track's
file belongs under a zone root. The actual filesystem move lives in
:class:`~vaultseek.workers.io.organizer_worker.OrganizerWorker`.

**Zone policy (in-place processing):** originals stay in *incoming* through
hash → fingerprint → identify → rules. The first physical move is either:

- incoming → **library** when identity is confirmed (auto-approve), or
- incoming → **library** after Review approval, or
- incoming → **archive** when a rule explicitly archives a loser.

*Staging* remains available for manual/legacy holding and rejected
re-process (staging → incoming), but the default pipeline no longer moves
there early. Allowed transitions also keep staging → library for tracks
already sitting in staging from older runs.
"""

from __future__ import annotations

import re
from pathlib import PurePath

from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone, Track

ALLOWED_TRANSITIONS: dict[LibraryZone, frozenset[LibraryZone]] = {
    LibraryZone.INCOMING: frozenset(
        {LibraryZone.LIBRARY, LibraryZone.STAGING, LibraryZone.ARCHIVE}
    ),
    LibraryZone.STAGING: frozenset(
        {LibraryZone.LIBRARY, LibraryZone.INCOMING, LibraryZone.ARCHIVE}
    ),
    LibraryZone.LIBRARY: frozenset({LibraryZone.ARCHIVE}),
    LibraryZone.ARCHIVE: frozenset({LibraryZone.LIBRARY}),
}

_INVALID_COMPONENT_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


class OrganizeEngine:
    """Validates zone transitions and computes organized destination paths."""

    def can_transition(self, source: LibraryZone, target: LibraryZone) -> bool:
        return target in ALLOWED_TRANSITIONS[source]

    def validate_transition(self, source: LibraryZone, target: LibraryZone) -> None:
        """Raise ``ValueError`` for a transition the state machine forbids."""
        if not self.can_transition(source, target):
            allowed = ", ".join(sorted(zone.value for zone in ALLOWED_TRANSITIONS[source]))
            raise ValueError(
                f"Illegal zone transition {source.value} -> {target.value} "
                f"(allowed from {source.value}: {allowed})"
            )

    def destination_path(
        self,
        library: Library,
        target: LibraryZone,
        track: Track,
        *,
        artist_name: str | None = None,
        album_title: str | None = None,
        album_year: int | None = None,
    ) -> PurePath:
        """Where ``track``'s file belongs once moved into ``target``."""
        root = PurePath(library.zone_root(target))
        if target is LibraryZone.INCOMING:
            return root / sanitize_component(track.file_name)
        return root / self._relative_path(
            track,
            artist_name=artist_name,
            album_title=album_title,
            album_year=album_year,
        )

    def _relative_path(
        self,
        track: Track,
        *,
        artist_name: str | None,
        album_title: str | None,
        album_year: int | None,
    ) -> PurePath:
        artist_dir = sanitize_component(artist_name or "") or "Unknown Artist"
        path = PurePath(artist_dir)

        album = sanitize_component(album_title or "")
        if album:
            year = album_year if album_year is not None else track.year
            path = path / (f"{year} - {album}" if year is not None else album)

        return path / self._file_name(track)

    def _file_name(self, track: Track) -> str:
        extension = PurePath(track.file_name).suffix
        title = sanitize_component(track.title or "")
        if not title:
            return sanitize_component(track.file_name)
        if track.track_number is not None:
            return f"{track.track_number:02d} - {title}{extension}"
        return f"{title}{extension}"


def sanitize_component(component: str) -> str:
    """Make a single path component safe on Windows (and everywhere else).

    Replaces reserved characters with ``_``, collapses runs of
    whitespace, and strips trailing dots/spaces (illegal in Windows
    directory names). Returns ``""`` when nothing salvageable remains.
    """
    cleaned = _WHITESPACE.sub(" ", component)
    cleaned = _INVALID_COMPONENT_CHARS.sub("_", cleaned).strip()
    return cleaned.rstrip(". ")

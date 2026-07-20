"""DTOs for the rules engine (Phase 8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from vaultseek.models.value_objects.rule_action import RuleAction


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Fields available to condition evaluation for one track.

    Built from :class:`~vaultseek.models.entities.track.Track` plus
    optional joins. ``has_lossless_duplicate`` is stubbed ``False`` until
    Phase 9 duplicate detection.
    """

    track_id: UUID
    library_id: UUID
    zone: str
    filename: str
    file_path: str
    codec: str | None = None
    bitrate: int | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None
    quality_score: int | None = None
    title: str | None = None
    artist: str = ""
    album: str = ""
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None
    composer: str | None = None
    duration_ms: int | None = None
    is_lossless: bool = False
    needs_review: bool = False
    overall_confidence: float | None = None
    has_lossless_duplicate: bool = False

    def as_mapping(self) -> dict[str, Any]:
        """Flat context dict for :meth:`RuleNode.evaluate`."""
        return {
            "track_id": self.track_id,
            "library_id": self.library_id,
            "zone": self.zone,
            "filename": self.filename,
            "file_path": self.file_path,
            "file_name": self.filename,
            "codec": self.codec,
            "bitrate": self.bitrate,
            "bit_depth": self.bit_depth,
            "sample_rate": self.sample_rate,
            "quality_score": self.quality_score,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "genre": self.genre,
            "year": self.year,
            "track_number": self.track_number,
            "composer": self.composer,
            "duration_ms": self.duration_ms,
            "is_lossless": self.is_lossless,
            "needs_review": self.needs_review,
            "overall_confidence": self.overall_confidence,
            "has_lossless_duplicate": self.has_lossless_duplicate,
        }


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """One enabled rule whose conditions matched a track."""

    rule_id: UUID
    rule_name: str
    actions: list[RuleAction]
    requires_approval: bool


@dataclass(frozen=True, slots=True)
class RuleCreate:
    """Input for creating a user rule."""

    library_id: UUID
    name: str
    conditions: dict[str, Any]
    actions: list[dict[str, Any]]
    enabled: bool = True
    priority: int = 100
    requires_approval: bool = False

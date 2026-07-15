"""QualityScorer — ranks tracks by audio quality (0-100).

Implements the `tracks.quality_score` column documented in
docs/architecture/03-database-schema.md ("0-100") and matches the
concrete example scores from docs/architecture/09-testing-strategy.md
exactly (FLAC 24-bit → 100, FLAC 16-bit → 95, MP3 320 → 70, configurable
via `QualityWeights`). No formula for scores *between* those documented
points exists anywhere in the architecture docs, so the bitrate/bit-depth
brackets below (256/192/128 kbps tiers, AAC brackets, etc.) are this
implementation's own reasonable fill-in — every bracket is a named,
overridable field on `QualityWeights` rather than a hardcoded constant,
so they can be retuned later without changing this module's logic.

Used by :class:`~musicvault.models.services.duplicate_matcher.DuplicateMatcher`
(Phase 9) to pick the best copy of a duplicate group — that consumer,
and the actual duplicate-detection algorithm, are Phase 9 scope; this
module only needs to score and rank individual tracks.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from musicvault.models.entities.track import Track


@dataclass(frozen=True, slots=True)
class QualityWeights:
    """Named quality-score brackets. Override any field to retune scoring
    without touching :class:`QualityScorer`'s logic."""

    lossless_24bit: int = 100
    lossless_16bit: int = 95
    mp3_320: int = 70
    mp3_256: int = 60
    mp3_192: int = 50
    mp3_128: int = 35
    aac_256: int = 65
    aac_128: int = 40
    default_lossy: int = 20


DEFAULT_WEIGHTS = QualityWeights()


class QualityScorer:
    """Scores and ranks tracks by audio quality using a fixed `QualityWeights` table."""

    def __init__(self, weights: QualityWeights) -> None:
        self._weights = weights

    def score(self, track: Track) -> int:
        """Return this track's quality score (0-100)."""
        if track.is_lossless:
            return self._score_lossless(track)
        return self._score_lossy(track)

    def rank(self, tracks: Sequence[Track]) -> list[Track]:
        """Sort ``tracks`` by quality score, best first.

        Ties preserve the input order (Python's sort is stable).
        """
        return sorted(tracks, key=self.score, reverse=True)

    def _score_lossless(self, track: Track) -> int:
        if track.bit_depth is not None and track.bit_depth >= 24:
            return self._weights.lossless_24bit
        return self._weights.lossless_16bit

    def _score_lossy(self, track: Track) -> int:
        if track.bitrate is None:
            return self._weights.default_lossy
        codec = (track.codec or "").lower()
        if codec == "mp3":
            return self._score_mp3(track.bitrate)
        if codec in {"aac", "m4a"}:
            return self._score_aac(track.bitrate)
        return self._weights.default_lossy

    def _score_mp3(self, bitrate: int) -> int:
        if bitrate >= 320:
            return self._weights.mp3_320
        if bitrate >= 256:
            return self._weights.mp3_256
        if bitrate >= 192:
            return self._weights.mp3_192
        if bitrate >= 128:
            return self._weights.mp3_128
        return self._weights.default_lossy

    def _score_aac(self, bitrate: int) -> int:
        if bitrate >= 256:
            return self._weights.aac_256
        if bitrate >= 128:
            return self._weights.aac_128
        return self._weights.default_lossy

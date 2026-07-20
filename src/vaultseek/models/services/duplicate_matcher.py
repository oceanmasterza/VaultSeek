"""DuplicateMatcher — pure duplicate-group construction with quality ranking.

The candidate discovery (which tracks share a hash / fingerprint / MBID)
is SQL in :class:`~vaultseek.db.repositories.duplicate_repo.DuplicateRepository`;
this domain service only turns an already-matched set of tracks into a
:class:`DuplicateGroup` + members, picking the best copy via
:class:`~vaultseek.models.services.quality_scorer.QualityScorer`.

Match confidences per tier are this implementation's own fill-in (no
documented thresholds exist): identical content hash is certain (1.0),
identical Chromaprint hash is near-certain (0.95), and a shared
MusicBrainz recording ID means "same recording, possibly different
master" (0.90). Fuzzy tag matching stays unimplemented.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from vaultseek.models.entities.duplicate_group import (
    DuplicateGroup,
    DuplicateMember,
    GroupStatus,
    MatchType,
)
from vaultseek.models.entities.track import Track
from vaultseek.models.services.quality_scorer import QualityScorer

MATCH_CONFIDENCE: dict[MatchType, float] = {
    MatchType.HASH: 1.0,
    MatchType.FINGERPRINT: 0.95,
    MatchType.MBID: 0.90,
}


class DuplicateMatcher:
    """Builds duplicate groups from matched tracks, ranking by quality."""

    def __init__(self, scorer: QualityScorer) -> None:
        self._scorer = scorer

    def score(self, track: Track) -> int:
        return self._scorer.score(track)

    def build_group(
        self,
        group_id: UUID,
        library_id: UUID,
        tracks: Sequence[Track],
        match_type: MatchType,
        *,
        detected_at: datetime,
    ) -> tuple[DuplicateGroup, list[DuplicateMember]]:
        """Construct a group + members for ``tracks`` (at least two).

        The highest-quality track becomes ``best_track_id`` /
        ``is_best`` (ties keep input order — quality sort is stable).
        """
        if len(tracks) < 2:
            raise ValueError("A duplicate group needs at least two tracks")
        ranked = self._scorer.rank(tracks)
        best = ranked[0]
        group = DuplicateGroup(
            id=group_id,
            library_id=library_id,
            match_type=match_type,
            match_confidence=MATCH_CONFIDENCE.get(match_type, 0.5),
            best_track_id=best.id,
            track_count=len(ranked),
            detected_at=detected_at,
            status=GroupStatus.OPEN,
        )
        members = [
            DuplicateMember(
                group_id=group_id,
                track_id=track.id,
                quality_score=self._scorer.score(track),
                zone=track.zone.value,
                is_best=track.id == best.id,
            )
            for track in ranked
        ]
        return group, members

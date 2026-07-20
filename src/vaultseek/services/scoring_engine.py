"""ScoringEngine — rank provider search hits for an AcquisitionJob."""

from __future__ import annotations

from dataclasses import dataclass

from vaultseek.models.entities.acquisition_job import AcquisitionJob
from vaultseek.models.interfaces.acquisition import SearchResult


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """Relative weights for normalized result scoring."""

    format_match: float = 0.30
    bit_depth: float = 0.20
    title_match: float = 0.25
    album_match: float = 0.15
    track_count: float = 0.10


class ScoringEngine:
    """Skeleton scoring engine — deterministic weighted heuristics."""

    def __init__(self, weights: ScoringWeights | None = None) -> None:
        self._weights = weights or ScoringWeights()

    def score_results(
        self,
        job: AcquisitionJob,
        results: list[SearchResult],
    ) -> list[tuple[SearchResult, float]]:
        scored = [(result, self.score_one(job, result)) for result in results]
        return sorted(scored, key=lambda item: item[1], reverse=True)

    def score_one(self, job: AcquisitionJob, result: SearchResult) -> float:
        score = 0.0
        if job.preferred_codec and result.format:
            if job.preferred_codec.casefold() == result.format.casefold():
                score += self._weights.format_match
        if job.preferred_bit_depth and result.bit_depth:
            if result.bit_depth >= job.preferred_bit_depth:
                score += self._weights.bit_depth
        if job.title and result.title:
            if job.title.casefold() in result.title.casefold():
                score += self._weights.title_match
        if job.album and result.album:
            if job.album.casefold() in result.album.casefold():
                score += self._weights.album_match
        if result.track_count and result.track_count > 0:
            score += self._weights.track_count
        return min(score, 1.0)

    def select_best(
        self,
        scored: list[tuple[SearchResult, float]],
        *,
        threshold: float = 0.0,
    ) -> SearchResult | None:
        if not scored:
            return None
        best_result, best_score = scored[0]
        if best_score < threshold:
            return None
        return best_result

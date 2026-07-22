"""ScoringEngine — rank provider search hits for an AcquisitionJob."""

from __future__ import annotations

import re
from dataclasses import dataclass

from vaultseek.models.entities.acquisition_job import AcquisitionJob
from vaultseek.models.interfaces.acquisition import SearchResult

_TOKEN_SPLIT = re.compile(r"[\s_\-./\\|()\[\]]+")
_LOSSLESS = frozenset({"flac", "wav", "aiff", "aif", "alac", "wv", "dsf", "dff"})


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """Relative weights for normalized result scoring."""

    format_match: float = 0.20
    bit_depth: float = 0.10
    title_match: float = 0.30
    album_match: float = 0.15
    artist_match: float = 0.20
    track_count: float = 0.05


class ScoringEngine:
    """Deterministic weighted heuristics for acquisition hits.

    Nicotine+/Soulseek results often only expose a file path — so artist,
    album, and title are also matched against ``display_name`` / path text.
    """

    def __init__(self, weights: ScoringWeights | None = None) -> None:
        self._weights = weights or ScoringWeights()

    def score_results(
        self,
        job: AcquisitionJob,
        results: list[SearchResult],
    ) -> list[tuple[SearchResult, float]]:
        scored = [(result, self.score_one(job, result)) for result in results]
        # Prefer peer folders that already contain several album matches — useful
        # when "download whole album" upgrades are enabled.
        folder_hits: dict[str, int] = {}
        for result, score in scored:
            if score < 0.25:
                continue
            key = _folder_key(result)
            if key:
                folder_hits[key] = folder_hits.get(key, 0) + 1
        boosted: list[tuple[SearchResult, float]] = []
        for result, score in scored:
            key = _folder_key(result)
            if key and folder_hits.get(key, 0) >= 2:
                score = min(1.0, score + 0.10)
            boosted.append((result, score))
        return sorted(boosted, key=lambda item: item[1], reverse=True)

    def score_one(self, job: AcquisitionJob, result: SearchResult) -> float:
        score = 0.0
        haystack = _result_haystack(result)

        if job.preferred_codec and result.format:
            if job.preferred_codec.casefold() == result.format.casefold():
                score += self._weights.format_match
        elif result.format and result.format.casefold() in _LOSSLESS:
            # Soft preference for lossless when the job has no codec preference.
            score += self._weights.format_match * 0.5

        if job.preferred_bit_depth and result.bit_depth:
            if result.bit_depth >= job.preferred_bit_depth:
                score += self._weights.bit_depth

        if _field_matches(job.title, result.title, haystack):
            score += self._weights.title_match
        if _field_matches(job.album, result.album, haystack):
            score += self._weights.album_match
        if _field_matches(job.artist, result.artist, haystack):
            score += self._weights.artist_match

        # Prefer higher bitrate when the hit exposes it (Soulseek file_attributes).
        bitrate = None
        raw = result.raw or {}
        if raw.get("bitrate") is not None:
            try:
                bitrate = int(raw["bitrate"])
            except (TypeError, ValueError):
                bitrate = None
        if bitrate and bitrate >= 320:
            score += 0.05
        elif bitrate and bitrate >= 192:
            score += 0.03

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


def _result_haystack(result: SearchResult) -> str:
    raw = result.raw or {}
    parts = [
        result.display_name,
        result.title,
        result.artist,
        result.album,
        str(raw.get("file_path") or ""),
        str(raw.get("virtual_path") or ""),
    ]
    return " ".join(part for part in parts if part).casefold()


def _folder_key(result: SearchResult) -> str | None:
    raw = result.raw or {}
    path = str(raw.get("file_path") or raw.get("virtual_path") or result.display_name or "")
    if not path:
        return None
    normalized = path.replace("\\", "/")
    if "/" not in normalized:
        return None
    parent = normalized.rsplit("/", 1)[0]
    user = str(result.source_user or raw.get("username") or "")
    return f"{user}:{parent}".casefold() if parent else None


def _field_matches(
    job_value: str | None,
    result_value: str | None,
    haystack: str,
) -> bool:
    if not job_value:
        return False
    needle = job_value.casefold().strip()
    if not needle:
        return False
    if result_value and needle in result_value.casefold():
        return True
    if needle in haystack:
        return True
    tokens = [token for token in _TOKEN_SPLIT.split(needle) if len(token) > 2]
    if len(tokens) >= 2:
        return all(token in haystack for token in tokens)
    if len(tokens) == 1:
        return tokens[0] in haystack
    return False

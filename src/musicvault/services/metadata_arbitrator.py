"""MetadataArbitrator — multi-provider per-field confidence resolution.

See docs/architecture/04-service-layer.md and docs/architecture/10-revision-v2.md
("Metadata Arbitration"). Identification cascade (no MusicBrainz ID yet):

1. AcoustID fingerprint → MB recording ID
2. MusicBrainz by ID / tags
3. Local embedded tags
4. Filename parser

Enrichment (MBID already present) prefers local tags then MusicBrainz fill-gaps.
"""

from __future__ import annotations

from collections.abc import Sequence

from musicvault.models.entities.track import Track
from musicvault.models.interfaces.metadata import (
    ArbitrationResult,
    FingerprintData,
    MetadataProvider,
    MetadataQuery,
    ProviderResult,
)
from musicvault.models.value_objects.field_confidence import FieldConfidence

_LOOKUP_METHOD_RANK = {
    "fingerprint": 0,
    "id": 1,
    "tags": 2,
    "filename": 3,
    "search": 4,
}


class MetadataArbitrator:
    def __init__(
        self,
        providers: Sequence[MetadataProvider],
        *,
        confidence_threshold: float = 0.90,
    ) -> None:
        self._providers = sorted(providers, key=lambda p: p.priority)
        self._threshold = confidence_threshold
        self._by_id = {p.provider_id: p for p in self._providers}

    def resolve(
        self, track: Track, fingerprint: FingerprintData | None = None
    ) -> ArbitrationResult:
        """Query enabled providers and pick the highest-confidence value
        per field."""
        results = self._query_providers(track, fingerprint)
        fields = self._arbitrate_fields(results)
        if not fields:
            return ArbitrationResult(
                track_id=track.id,
                fields={},
                overall_confidence=0.0,
                needs_review=True,
                provider_results=results,
            )
        overall = min(item.confidence for item in fields.values())
        return ArbitrationResult(
            track_id=track.id,
            fields=fields,
            overall_confidence=overall,
            needs_review=overall < self._threshold,
            provider_results=results,
        )

    def _query_providers(
        self, track: Track, fingerprint: FingerprintData | None
    ) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        query = _query_from_track(track)
        has_mbid = bool(track.mb_recording_id)

        if not has_mbid and fingerprint is not None:
            acoustid = self._by_id.get("acoustid")
            if acoustid is not None:
                hit = acoustid.lookup_by_fingerprint(
                    fingerprint.fingerprint_data, fingerprint.duration_seconds
                )
                if hit is not None:
                    results.append(_with_priority(hit, acoustid.priority))
                    mbid = _field_value(hit, "mb_recording_id")
                    if isinstance(mbid, str) and mbid:
                        musicbrainz = self._by_id.get("musicbrainz")
                        if musicbrainz is not None:
                            by_id = musicbrainz.lookup_by_id(mbid, "recording")
                            if by_id is not None:
                                results.append(_with_priority(by_id, musicbrainz.priority))

        for provider_id in ("musicbrainz", "local_tags", "filename_parser"):
            provider = self._by_id.get(provider_id)
            if provider is None:
                continue
            if provider_id == "musicbrainz" and track.mb_recording_id:
                by_id = provider.lookup_by_id(track.mb_recording_id, "recording")
                if by_id is not None:
                    results.append(_with_priority(by_id, provider.priority))
            tags_hit = provider.lookup_by_tags(query)
            if tags_hit is not None:
                results.append(_with_priority(tags_hit, provider.priority))

        return results

    def _arbitrate_fields(self, results: Sequence[ProviderResult]) -> dict[str, FieldConfidence]:
        winners: dict[str, FieldConfidence] = {}
        winner_meta: dict[str, tuple[int, int]] = {}

        for result in results:
            method_rank = _LOOKUP_METHOD_RANK.get(result.lookup_method, 99)
            for field in result.fields:
                if field.value is None or field.value == "":
                    continue
                candidate = FieldConfidence(
                    field=field.field,
                    value=field.value,
                    confidence=field.confidence,
                    source=result.provider_id,
                )
                existing = winners.get(field.field)
                if existing is None:
                    winners[field.field] = candidate
                    winner_meta[field.field] = (result.priority, method_rank)
                    continue
                prev_priority, prev_method = winner_meta[field.field]
                if field.confidence > existing.confidence:
                    winners[field.field] = candidate
                    winner_meta[field.field] = (result.priority, method_rank)
                elif field.confidence == existing.confidence:
                    if result.priority < prev_priority or (
                        result.priority == prev_priority and method_rank < prev_method
                    ):
                        winners[field.field] = candidate
                        winner_meta[field.field] = (result.priority, method_rank)
        return winners


def _query_from_track(track: Track) -> MetadataQuery:
    return MetadataQuery(
        file_path=track.file_path,
        file_name=track.file_name,
        title=track.title,
        year=track.year,
        track_number=track.track_number,
        duration_ms=track.duration_ms,
    )


def _field_value(result: ProviderResult, name: str) -> str | int | float | None:
    for item in result.fields:
        if item.field == name:
            return item.value
    return None


def _with_priority(result: ProviderResult, priority: int) -> ProviderResult:
    if result.priority == priority:
        return result
    return ProviderResult(
        provider_id=result.provider_id,
        fields=result.fields,
        overall_confidence=result.overall_confidence,
        lookup_method=result.lookup_method,
        raw_response=result.raw_response,
        priority=priority,
    )

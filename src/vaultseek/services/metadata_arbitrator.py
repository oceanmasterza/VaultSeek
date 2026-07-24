"""MetadataArbitrator — multi-provider per-field confidence resolution.

See docs/architecture/04-service-layer.md and docs/architecture/10-revision-v2.md
("Metadata Arbitration"). Identification cascade (Picard-style):

1. Local embedded tags
2. MusicBrainz by existing recording ID / by tags (seeded from tags)
3. Discogs by tags — when MusicBrainz did not attach a recording MBID
4. Filename parser (only if core identity is still weak)
5. AcoustID fingerprint → MusicBrainz by ID — when no recording MBID yet
   (strong tags alone are not enough; missing-media needs MusicBrainz links)
6. Shazamio audio recognition — when AcoustID has no key / returns nothing

AcoustID itself enforces ≤ 3 requests/second. Shazamio routes enforce ≤ 1
request/second per public IP (direct + configured proxies). Overall
confidence uses **core** fields only (artist, album, title).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from vaultseek.models.entities.track import Track
from vaultseek.models.interfaces.metadata import (
    ArbitrationResult,
    FingerprintData,
    MetadataProvider,
    MetadataQuery,
    ProviderResult,
)
from vaultseek.models.value_objects.field_confidence import FieldConfidence

_LOOKUP_METHOD_RANK = {
    "fingerprint": 0,
    "audio": 0,  # Shazamio — same rank as Chromaprint/AcoustID hits
    "id": 1,
    "tags": 2,
    "filename": 3,
    "search": 4,
}

# Gate auto-approve / needs_review on identity fields only.
_CORE_FIELDS = frozenset({"artist", "album", "title"})


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
        self,
        track: Track,
        fingerprint: FingerprintData | None = None,
        *,
        force_acoustid: bool = False,
    ) -> ArbitrationResult:
        """Query enabled providers and pick the highest-confidence value
        per field.

        ``force_acoustid`` is used by album-folder sampling: even strong
        tags still run AcoustID until the folder is trusted, so the
        sample confirmation count is real fingerprint evidence.
        """
        results = self._query_providers(track, fingerprint, force_acoustid=force_acoustid)
        fields = self._arbitrate_fields(results)
        if not fields:
            return ArbitrationResult(
                track_id=track.id,
                fields={},
                overall_confidence=0.0,
                needs_review=True,
                provider_results=results,
            )
        overall = _core_overall(fields)
        artist = fields.get("artist")
        needs_review = (
            artist is None
            or not str(artist.value or "").strip()
            or overall < self._threshold
        )
        return ArbitrationResult(
            track_id=track.id,
            fields=fields,
            overall_confidence=overall,
            needs_review=needs_review,
            provider_results=results,
        )

    def _query_providers(
        self,
        track: Track,
        fingerprint: FingerprintData | None,
        *,
        force_acoustid: bool = False,
    ) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        query = _query_from_track(track)

        # 1. Embedded tags — free, fast, seeds MusicBrainz / Discogs search.
        local = self._by_id.get("local_tags")
        if local is not None:
            tags_hit = local.lookup_by_tags(query)
            if tags_hit is not None:
                results.append(_with_priority(tags_hit, local.priority))
                query = _enrich_query(query, tags_hit)

        musicbrainz = self._by_id.get("musicbrainz")
        if musicbrainz is not None:
            # 2a. Already-known recording MBID.
            if track.mb_recording_id:
                by_id = musicbrainz.lookup_by_id(track.mb_recording_id, "recording")
                if by_id is not None:
                    results.append(_with_priority(by_id, musicbrainz.priority))
                    query = _enrich_query(query, by_id)
            # 2b. Tag search — skip when we already have a recording MBID.
            if not _has_recording_mbid(results, track=track):
                tags_hit = musicbrainz.lookup_by_tags(query)
                if tags_hit is not None:
                    results.append(_with_priority(tags_hit, musicbrainz.priority))
                    query = _enrich_query(query, tags_hit)

        # 3. Discogs — when MusicBrainz did not attach a recording MBID.
        if not _has_recording_mbid(results, track=track):
            discogs = self._by_id.get("discogs")
            if discogs is not None:
                discogs_hit = discogs.lookup_by_tags(query)
                if discogs_hit is not None:
                    results.append(_with_priority(discogs_hit, discogs.priority))
                    query = _enrich_query(query, discogs_hit)
                    # Retry MusicBrainz with Discogs-enriched artist/album/title.
                    if musicbrainz is not None:
                        mb_retry = musicbrainz.lookup_by_tags(query)
                        if mb_retry is not None:
                            results.append(_with_priority(mb_retry, musicbrainz.priority))
                            query = _enrich_query(query, mb_retry)

        # 4. Filename only when core identity is still weak.
        if not _identity_is_strong(results, self._threshold):
            filename = self._by_id.get("filename_parser")
            if filename is not None:
                tags_hit = filename.lookup_by_tags(query)
                if tags_hit is not None:
                    results.append(_with_priority(tags_hit, filename.priority))
                    query = _enrich_query(query, tags_hit)

        # 5. AcoustID — whenever we still lack a recording MBID, or sampling
        #    forces fingerprint confirmation. Strong tags alone are not enough
        #    for missing-media (needs MusicBrainz release linkage).
        want_audio_id = force_acoustid or _should_use_acoustid(results, track=track)
        acoustid_hit: ProviderResult | None = None
        if fingerprint is not None and want_audio_id:
            acoustid = self._by_id.get("acoustid")
            if acoustid is not None:
                acoustid_hit = acoustid.lookup_by_fingerprint(
                    fingerprint.fingerprint_data, fingerprint.duration_seconds
                )
                if acoustid_hit is not None:
                    results.append(_with_priority(acoustid_hit, acoustid.priority))
                    mbid = _field_value(acoustid_hit, "mb_recording_id")
                    if isinstance(mbid, str) and mbid and musicbrainz is not None:
                        by_id = musicbrainz.lookup_by_id(mbid, "recording")
                        if by_id is not None:
                            results.append(_with_priority(by_id, musicbrainz.priority))

        # 6. Shazamio fallback — AcoustID miss / no key, same fingerprint gate.
        if (
            fingerprint is not None
            and want_audio_id
            and acoustid_hit is None
            and track.file_path
        ):
            shazam = self._by_id.get("shazamio")
            if shazam is not None:
                recognize = getattr(shazam, "recognize_file", None)
                if callable(recognize):
                    shazam_hit = recognize(track.file_path)
                else:
                    shazam_hit = shazam.lookup_by_tags(query)
                if shazam_hit is not None:
                    results.append(_with_priority(shazam_hit, shazam.priority))
                    query = _enrich_query(query, shazam_hit)
                    if musicbrainz is not None:
                        mb_from_shazam = musicbrainz.lookup_by_tags(query)
                        if mb_from_shazam is not None:
                            results.append(
                                _with_priority(mb_from_shazam, musicbrainz.priority)
                            )

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


def _should_use_acoustid(
    results: Sequence[ProviderResult],
    *,
    track: Track,
) -> bool:
    """True when fingerprint / Shazam lookup is still worth an API call."""
    # Skip only when a MusicBrainz recording is already linked.
    return not _has_recording_mbid(results, track=track)


def _has_recording_mbid(results: Sequence[ProviderResult], *, track: Track) -> bool:
    if track.mb_recording_id and str(track.mb_recording_id).strip():
        return True
    for result in results:
        value = _field_value(result, "mb_recording_id")
        if isinstance(value, str) and value.strip():
            return True
    return False


def _identity_is_strong(results: Sequence[ProviderResult], threshold: float) -> bool:
    """Artist + title + album all present at or above the auto-approve gate."""
    winners: dict[str, float] = {}
    for result in results:
        for field in result.fields:
            if field.field not in _CORE_FIELDS:
                continue
            if field.value is None or field.value == "":
                continue
            prev = winners.get(field.field)
            if prev is None or field.confidence > prev:
                winners[field.field] = field.confidence
    if not {"artist", "title", "album"}.issubset(winners):
        return False
    return min(winners.values()) >= threshold


def _core_overall(fields: dict[str, FieldConfidence]) -> float:
    core = [fields[name].confidence for name in _CORE_FIELDS if name in fields]
    if core:
        return min(core)
    return min(item.confidence for item in fields.values())


def _query_from_track(track: Track) -> MetadataQuery:
    return MetadataQuery(
        file_path=track.file_path,
        file_name=track.file_name,
        title=track.title,
        year=track.year,
        track_number=track.track_number,
        duration_ms=track.duration_ms,
    )


def _enrich_query(query: MetadataQuery, result: ProviderResult) -> MetadataQuery:
    """Fill empty query slots from a provider hit (local tags → MB search)."""
    updates: dict[str, object] = {}
    for field in result.fields:
        if field.value is None or field.value == "":
            continue
        if field.field == "artist" and not query.artist and isinstance(field.value, str):
            updates["artist"] = field.value
        elif field.field == "album" and not query.album and isinstance(field.value, str):
            updates["album"] = field.value
        elif field.field == "title" and not query.title and isinstance(field.value, str):
            updates["title"] = field.value
        elif field.field == "year" and query.year is None and isinstance(field.value, int):
            updates["year"] = field.value
        elif (
            field.field == "track_number"
            and query.track_number is None
            and isinstance(field.value, int)
        ):
            updates["track_number"] = field.value
    return replace(query, **updates) if updates else query  # type: ignore[arg-type]


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

"""Unit tests for MetadataArbitrator."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.track import LibraryZone, Track
from musicvault.models.interfaces.metadata import (
    FingerprintData,
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)
from musicvault.services.metadata_arbitrator import MetadataArbitrator

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


class _FakeProvider:
    def __init__(
        self,
        provider_id: str,
        priority: int,
        *,
        fingerprint: ProviderResult | None = None,
        by_id: ProviderResult | None = None,
        by_tags: ProviderResult | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.priority = priority
        self._fingerprint = fingerprint
        self._by_id = by_id
        self._by_tags = by_tags

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        return self._fingerprint

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        return self._by_tags

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None:
        return self._by_id

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]:
        return []


def _track(**overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": generate_uuid7(),
        "zone": LibraryZone.INCOMING,
        "file_path": "C:/music/Artist - Title.flac",
        "file_name": "Artist - Title.flac",
        "file_size": 1,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def test_resolve_picks_highest_confidence_per_field() -> None:
    low = ProviderResult(
        provider_id="filename_parser",
        fields=[ProviderFieldResult("title", "From File", 0.45)],
        overall_confidence=0.45,
        lookup_method="filename",
        priority=90,
    )
    high = ProviderResult(
        provider_id="local_tags",
        fields=[ProviderFieldResult("title", "From Tags", 0.80)],
        overall_confidence=0.80,
        lookup_method="tags",
        priority=50,
    )
    arbitrator = MetadataArbitrator(
        [
            _FakeProvider("filename_parser", 90, by_tags=low),
            _FakeProvider("local_tags", 50, by_tags=high),
        ]
    )

    result = arbitrator.resolve(_track())

    assert result.fields["title"].value == "From Tags"
    assert result.fields["title"].source == "local_tags"
    assert result.overall_confidence == 0.80
    assert result.needs_review is True


def test_resolve_ties_break_by_provider_priority() -> None:
    a = ProviderResult(
        provider_id="musicbrainz",
        fields=[ProviderFieldResult("title", "MB", 0.90)],
        overall_confidence=0.90,
        lookup_method="tags",
        priority=10,
    )
    b = ProviderResult(
        provider_id="local_tags",
        fields=[ProviderFieldResult("title", "Tags", 0.90)],
        overall_confidence=0.90,
        lookup_method="tags",
        priority=50,
    )
    arbitrator = MetadataArbitrator(
        [
            _FakeProvider("musicbrainz", 10, by_tags=a),
            _FakeProvider("local_tags", 50, by_tags=b),
        ],
        confidence_threshold=0.85,
    )

    result = arbitrator.resolve(_track())

    assert result.fields["title"].value == "MB"
    assert result.needs_review is False


def test_resolve_uses_acoustid_then_musicbrainz_by_id() -> None:
    mbid = str(generate_uuid7())
    acoustid = ProviderResult(
        provider_id="acoustid",
        fields=[
            ProviderFieldResult("mb_recording_id", mbid, 0.98),
            ProviderFieldResult("acoustid_id", "aid", 0.97),
        ],
        overall_confidence=0.97,
        lookup_method="fingerprint",
        priority=5,
    )
    by_id = ProviderResult(
        provider_id="musicbrainz",
        fields=[ProviderFieldResult("title", "Resolved", 0.95)],
        overall_confidence=0.95,
        lookup_method="id",
        priority=10,
    )
    arbitrator = MetadataArbitrator(
        [
            _FakeProvider("acoustid", 5, fingerprint=acoustid),
            _FakeProvider("musicbrainz", 10, by_id=by_id),
        ],
        confidence_threshold=0.90,
    )
    fingerprint = FingerprintData(fingerprint_data=b"fp", duration_seconds=120.0)

    result = arbitrator.resolve(_track(), fingerprint)

    assert result.fields["title"].value == "Resolved"
    assert result.fields["mb_recording_id"].value == mbid
    assert result.needs_review is False


def test_resolve_empty_providers_marks_needs_review() -> None:
    arbitrator = MetadataArbitrator([])
    track = _track()

    result = arbitrator.resolve(track)

    assert result.fields == {}
    assert result.overall_confidence == 0.0
    assert result.needs_review is True
    assert result.track_id == track.id


def test_resolve_overall_confidence_is_min_of_winners() -> None:
    tags = ProviderResult(
        provider_id="local_tags",
        fields=[
            ProviderFieldResult("title", "T", 0.95),
            ProviderFieldResult("year", 2001, 0.70),
        ],
        overall_confidence=0.70,
        lookup_method="tags",
        priority=50,
    )
    arbitrator = MetadataArbitrator([_FakeProvider("local_tags", 50, by_tags=tags)])

    result = arbitrator.resolve(_track())

    assert result.overall_confidence == 0.70
    assert isinstance(result.track_id, UUID)


def test_resolve_enrichment_looks_up_existing_mbid() -> None:
    mbid = str(generate_uuid7())
    by_id = ProviderResult(
        provider_id="musicbrainz",
        fields=[ProviderFieldResult("title", "By Id", 0.95)],
        overall_confidence=0.95,
        lookup_method="id",
        priority=10,
    )
    arbitrator = MetadataArbitrator(
        [_FakeProvider("musicbrainz", 10, by_id=by_id)],
        confidence_threshold=0.90,
    )

    result = arbitrator.resolve(_track(mb_recording_id=mbid))

    assert result.fields["title"].value == "By Id"
    assert result.needs_review is False

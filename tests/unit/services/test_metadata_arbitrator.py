"""Unit tests for MetadataArbitrator."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.interfaces.metadata import (
    FingerprintData,
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)
from vaultseek.services.metadata_arbitrator import MetadataArbitrator

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
        fields=[
            ProviderFieldResult("artist", "A", 0.90),
            ProviderFieldResult("album", "Alb", 0.90),
            ProviderFieldResult("title", "MB", 0.90),
        ],
        overall_confidence=0.90,
        lookup_method="tags",
        priority=10,
    )
    b = ProviderResult(
        provider_id="local_tags",
        fields=[
            ProviderFieldResult("artist", "A", 0.90),
            ProviderFieldResult("album", "Alb", 0.90),
            ProviderFieldResult("title", "Tags", 0.90),
        ],
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


def test_resolve_skips_acoustid_when_mb_recording_already_linked() -> None:
    """Strong tags + MB recording ID → no AcoustID (quota saved)."""
    local = ProviderResult(
        provider_id="local_tags",
        fields=[
            ProviderFieldResult("artist", "Radiohead", 0.92),
            ProviderFieldResult("album", "OK Computer", 0.92),
            ProviderFieldResult("title", "Karma Police", 0.92),
            ProviderFieldResult("mb_recording_id", "mbid-already", 0.95),
        ],
        overall_confidence=0.92,
        lookup_method="tags",
        priority=50,
    )
    calls = {"fp": 0}

    class _Acoustid:
        provider_id = "acoustid"
        priority = 5

        def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> None:
            calls["fp"] += 1
            return None

        def lookup_by_tags(self, query: MetadataQuery) -> None:
            return None

        def lookup_by_id(self, external_id: str, id_type: str) -> None:
            return None

        def search(
            self,
            query: str,
            entity_type: Literal["artist", "album", "recording"],
            limit: int = 10,
        ) -> list[ProviderResult]:
            return []

    arbitrator = MetadataArbitrator(
        [
            _FakeProvider("local_tags", 50, by_tags=local),
            _FakeProvider(
                "musicbrainz",
                10,
                by_tags=ProviderResult(
                    provider_id="musicbrainz",
                    fields=[ProviderFieldResult("mb_recording_id", "mbid-already", 0.95)],
                    overall_confidence=0.95,
                    lookup_method="tags",
                    priority=10,
                ),
            ),
            _Acoustid(),
        ],
        confidence_threshold=0.90,
    )
    fingerprint = FingerprintData(fingerprint_data=b"fp", duration_seconds=120.0)

    result = arbitrator.resolve(_track(), fingerprint)

    assert calls["fp"] == 0
    assert result.needs_review is False
    assert result.fields["artist"].value == "Radiohead"


def test_resolve_uses_acoustid_when_tags_strong_but_no_mbid() -> None:
    """Strong tags without MusicBrainz ID still run AcoustID for linkage."""
    local = ProviderResult(
        provider_id="local_tags",
        fields=[
            ProviderFieldResult("artist", "Radiohead", 0.92),
            ProviderFieldResult("album", "OK Computer", 0.92),
            ProviderFieldResult("title", "Karma Police", 0.92),
        ],
        overall_confidence=0.92,
        lookup_method="tags",
        priority=50,
    )
    calls = {"fp": 0}

    class _Acoustid:
        provider_id = "acoustid"
        priority = 5

        def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult:
            calls["fp"] += 1
            return ProviderResult(
                provider_id="acoustid",
                fields=[ProviderFieldResult("mb_recording_id", "from-acoustid", 0.97)],
                overall_confidence=0.97,
                lookup_method="fingerprint",
                priority=5,
            )

        def lookup_by_tags(self, query: MetadataQuery) -> None:
            return None

        def lookup_by_id(self, external_id: str, id_type: str) -> None:
            return None

        def search(
            self,
            query: str,
            entity_type: Literal["artist", "album", "recording"],
            limit: int = 10,
        ) -> list[ProviderResult]:
            return []

    arbitrator = MetadataArbitrator(
        [_FakeProvider("local_tags", 50, by_tags=local), _Acoustid()],
        confidence_threshold=0.90,
    )
    fingerprint = FingerprintData(fingerprint_data=b"fp", duration_seconds=120.0)

    result = arbitrator.resolve(_track(), fingerprint)

    assert calls["fp"] == 1
    assert result.fields["mb_recording_id"].value == "from-acoustid"


def test_resolve_uses_acoustid_when_tags_are_weak() -> None:
    weak = ProviderResult(
        provider_id="local_tags",
        fields=[ProviderFieldResult("title", "Maybe", 0.40)],
        overall_confidence=0.40,
        lookup_method="tags",
        priority=50,
    )
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
        fields=[
            ProviderFieldResult("artist", "Resolved Artist", 0.95),
            ProviderFieldResult("album", "Resolved Album", 0.95),
            ProviderFieldResult("title", "Resolved", 0.95),
        ],
        overall_confidence=0.95,
        lookup_method="id",
        priority=10,
    )
    arbitrator = MetadataArbitrator(
        [
            _FakeProvider("local_tags", 50, by_tags=weak),
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


def test_resolve_falls_back_to_shazamio_when_acoustid_misses() -> None:
    weak = ProviderResult(
        provider_id="local_tags",
        fields=[ProviderFieldResult("title", "Maybe", 0.40)],
        overall_confidence=0.40,
        lookup_method="tags",
        priority=50,
    )
    shazam_hit = ProviderResult(
        provider_id="shazamio",
        fields=[
            ProviderFieldResult("artist", "Shazam Artist", 0.93),
            ProviderFieldResult("album", "Shazam Album", 0.93),
            ProviderFieldResult("title", "Shazam Title", 0.93),
        ],
        overall_confidence=0.93,
        lookup_method="audio",
        priority=6,
    )
    calls = {"shazam": 0, "acoustid": 0}

    class _Acoustid:
        provider_id = "acoustid"
        priority = 5

        def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> None:
            calls["acoustid"] += 1
            return None

        def lookup_by_tags(self, query: MetadataQuery) -> None:
            return None

        def lookup_by_id(self, external_id: str, id_type: str) -> None:
            return None

        def search(
            self,
            query: str,
            entity_type: Literal["artist", "album", "recording"],
            limit: int = 10,
        ) -> list[ProviderResult]:
            return []

    class _Shazam:
        provider_id = "shazamio"
        priority = 6

        def recognize_file(self, file_path: str) -> ProviderResult:
            calls["shazam"] += 1
            assert file_path
            return shazam_hit

        def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> None:
            return None

        def lookup_by_tags(self, query: MetadataQuery) -> None:
            return None

        def lookup_by_id(self, external_id: str, id_type: str) -> None:
            return None

        def search(
            self,
            query: str,
            entity_type: Literal["artist", "album", "recording"],
            limit: int = 10,
        ) -> list[ProviderResult]:
            return []

    arbitrator = MetadataArbitrator(
        [
            _FakeProvider("local_tags", 50, by_tags=weak),
            _Acoustid(),
            _Shazam(),
        ],
        confidence_threshold=0.90,
    )
    fingerprint = FingerprintData(fingerprint_data=b"fp", duration_seconds=120.0)

    result = arbitrator.resolve(_track(), fingerprint)

    assert calls["acoustid"] == 1
    assert calls["shazam"] == 1
    assert result.fields["title"].value == "Shazam Title"
    assert result.fields["title"].source == "shazamio"
    assert result.needs_review is False


def test_resolve_skips_shazamio_when_acoustid_hits() -> None:
    weak = ProviderResult(
        provider_id="local_tags",
        fields=[ProviderFieldResult("title", "Maybe", 0.40)],
        overall_confidence=0.40,
        lookup_method="tags",
        priority=50,
    )
    acoustid = ProviderResult(
        provider_id="acoustid",
        fields=[
            ProviderFieldResult("artist", "A", 0.95),
            ProviderFieldResult("album", "B", 0.95),
            ProviderFieldResult("title", "From AcoustID", 0.95),
        ],
        overall_confidence=0.95,
        lookup_method="fingerprint",
        priority=5,
    )
    calls = {"shazam": 0}

    class _Shazam:
        provider_id = "shazamio"
        priority = 6

        def recognize_file(self, file_path: str) -> ProviderResult | None:
            calls["shazam"] += 1
            return None

        def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> None:
            return None

        def lookup_by_tags(self, query: MetadataQuery) -> None:
            return None

        def lookup_by_id(self, external_id: str, id_type: str) -> None:
            return None

        def search(
            self,
            query: str,
            entity_type: Literal["artist", "album", "recording"],
            limit: int = 10,
        ) -> list[ProviderResult]:
            return []

    arbitrator = MetadataArbitrator(
        [
            _FakeProvider("local_tags", 50, by_tags=weak),
            _FakeProvider("acoustid", 5, fingerprint=acoustid),
            _Shazam(),
        ],
        confidence_threshold=0.90,
    )
    fingerprint = FingerprintData(fingerprint_data=b"fp", duration_seconds=120.0)

    result = arbitrator.resolve(_track(), fingerprint)

    assert calls["shazam"] == 0
    assert result.fields["title"].value == "From AcoustID"


def test_resolve_empty_providers_marks_needs_review() -> None:
    arbitrator = MetadataArbitrator([])
    track = _track()

    result = arbitrator.resolve(track)

    assert result.fields == {}
    assert result.overall_confidence == 0.0
    assert result.needs_review is True
    assert result.track_id == track.id


def test_resolve_overall_confidence_uses_core_fields_only() -> None:
    tags = ProviderResult(
        provider_id="local_tags",
        fields=[
            ProviderFieldResult("artist", "A", 0.92),
            ProviderFieldResult("album", "B", 0.92),
            ProviderFieldResult("title", "T", 0.95),
            ProviderFieldResult("year", 2001, 0.70),
            ProviderFieldResult("composer", "C", 0.65),
        ],
        overall_confidence=0.65,
        lookup_method="tags",
        priority=50,
    )
    arbitrator = MetadataArbitrator(
        [_FakeProvider("local_tags", 50, by_tags=tags)],
        confidence_threshold=0.90,
    )

    result = arbitrator.resolve(_track())

    assert result.overall_confidence == 0.92
    assert result.needs_review is False
    assert isinstance(result.track_id, UUID)


def test_resolve_seeds_musicbrainz_from_local_tags() -> None:
    local = ProviderResult(
        provider_id="local_tags",
        fields=[
            ProviderFieldResult("artist", "Radiohead", 0.92),
            ProviderFieldResult("title", "Karma Police", 0.92),
            ProviderFieldResult("album", "OK Computer", 0.92),
        ],
        overall_confidence=0.92,
        lookup_method="tags",
        priority=50,
    )
    mb_queries: list[MetadataQuery] = []

    class _MB:
        provider_id = "musicbrainz"
        priority = 10

        def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> None:
            return None

        def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
            mb_queries.append(query)
            return ProviderResult(
                provider_id="musicbrainz",
                fields=[ProviderFieldResult("mb_recording_id", "mbid-1", 0.95)],
                overall_confidence=0.95,
                lookup_method="tags",
                priority=10,
            )

        def lookup_by_id(self, external_id: str, id_type: str) -> None:
            return None

        def search(
            self,
            query: str,
            entity_type: Literal["artist", "album", "recording"],
            limit: int = 10,
        ) -> list[ProviderResult]:
            return []

    arbitrator = MetadataArbitrator(
        [_FakeProvider("local_tags", 50, by_tags=local), _MB()],
        confidence_threshold=0.90,
    )

    result = arbitrator.resolve(_track())

    assert mb_queries
    assert mb_queries[0].artist == "Radiohead"
    assert mb_queries[0].title == "Karma Police"
    assert result.fields["mb_recording_id"].value == "mbid-1"
    assert result.needs_review is False


def test_resolve_enrichment_looks_up_existing_mbid() -> None:
    mbid = str(generate_uuid7())
    by_id = ProviderResult(
        provider_id="musicbrainz",
        fields=[
            ProviderFieldResult("artist", "By Id Artist", 0.95),
            ProviderFieldResult("album", "By Id Album", 0.95),
            ProviderFieldResult("title", "By Id", 0.95),
        ],
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

"""Metadata provider protocol — multi-source track identification.

See docs/architecture/05-plugin-api.md ("Metadata Provider Protocol") and
docs/architecture/04-service-layer.md ("MetadataArbitrator"). AcoustID HTTP
lookup is a metadata provider here (Phase 6); Chromaprint generation stays
on :class:`~musicvault.models.interfaces.fingerprint.FingerprintProvider`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from musicvault.models.value_objects.field_confidence import FieldConfidence


@dataclass(frozen=True, slots=True)
class FingerprintData:
    """Chromaprint snapshot passed into fingerprint-based lookups."""

    fingerprint_data: bytes
    duration_seconds: float
    fingerprint_hash: str | None = None
    acoustid_id: str | None = None
    acoustid_score: float | None = None


@dataclass(frozen=True, slots=True)
class MetadataQuery:
    """Tag / path-based lookup input built from a :class:`Track`."""

    file_path: str | None = None
    file_name: str | None = None
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    year: int | None = None
    track_number: int | None = None
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderFieldResult:
    """One field proposed by a single metadata provider."""

    field: str
    value: str | int | float | None
    confidence: float


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Full result from one provider lookup attempt."""

    provider_id: str
    fields: list[ProviderFieldResult]
    overall_confidence: float
    lookup_method: str
    raw_response: dict[str, Any] | None = None
    priority: int = 100


@dataclass(frozen=True, slots=True)
class ArbitrationResult:
    """Per-field winners after multi-provider arbitration."""

    track_id: UUID
    fields: dict[str, FieldConfidence]
    overall_confidence: float
    needs_review: bool
    provider_results: list[ProviderResult] = field(default_factory=list)


class MetadataProvider(Protocol):
    """A pluggable source of track metadata with per-field confidence."""

    provider_id: str
    priority: int

    def lookup_by_fingerprint(
        self, fingerprint: bytes, duration: float
    ) -> ProviderResult | None: ...

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None: ...

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None: ...

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]: ...

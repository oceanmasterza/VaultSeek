"""FieldConfidence value object — a single metadata field's arbitrated value.

Mirrors the shape documented in docs/architecture/04-service-layer.md
("MetadataArbitrator") and the `metadata_confidence` table (see
docs/architecture/03-database-schema.md). Pulled forward into Phase 3
as a pure value object because it is one of the domain layer's
documented building blocks (docs/architecture/01-overview.md, "Layer
3: Domain"); the :class:`~musicvault.models.services.MetadataArbitrator`
that actually produces these, and the repository that persists them to
`metadata_confidence`, are Phase 6 scope (no consumer exists yet).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldConfidence:
    """A single field's value, as resolved by one metadata provider,
    with the arbitrator's confidence that it is correct."""

    field: str
    value: str | int | None
    confidence: float
    source: str

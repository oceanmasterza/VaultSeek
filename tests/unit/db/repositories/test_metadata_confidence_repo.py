"""Unit tests for MetadataConfidenceRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.db.repositories.metadata_confidence_repo import MetadataConfidenceRepository
from vaultseek.models.value_objects.field_confidence import FieldConfidence

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def test_upsert_fields_and_list_for_track_round_trip(engine: Engine, track_id: UUID) -> None:
    repo = MetadataConfidenceRepository(engine)
    fields = [
        FieldConfidence("title", "Song", 0.95, "musicbrainz"),
        FieldConfidence("year", 1999, 0.80, "local_tags"),
    ]

    assert repo.upsert_fields(track_id, fields, now=_NOW) == 2

    loaded = {item.field: item for item in repo.list_for_track(track_id)}
    assert loaded["title"] == FieldConfidence("title", "Song", 0.95, "musicbrainz")
    assert loaded["year"] == FieldConfidence("year", 1999, 0.80, "local_tags")


def test_upsert_fields_replaces_previous_winners(engine: Engine, track_id: UUID) -> None:
    repo = MetadataConfidenceRepository(engine)
    repo.upsert_fields(
        track_id,
        [FieldConfidence("title", "Old", 0.5, "filename_parser")],
        now=_NOW,
    )

    repo.upsert_fields(
        track_id,
        [FieldConfidence("title", "New", 0.9, "musicbrainz")],
        now=_NOW,
    )

    loaded = repo.list_for_track(track_id)
    assert loaded == [FieldConfidence("title", "New", 0.9, "musicbrainz")]


def test_upsert_fields_with_empty_list_clears_rows(engine: Engine, track_id: UUID) -> None:
    repo = MetadataConfidenceRepository(engine)
    repo.upsert_fields(
        track_id,
        [FieldConfidence("title", "Gone", 0.5, "filename_parser")],
        now=_NOW,
    )

    assert repo.upsert_fields(track_id, [], now=_NOW) == 0
    assert repo.list_for_track(track_id) == []

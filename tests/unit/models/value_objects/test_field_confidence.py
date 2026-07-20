"""Unit tests for vaultseek.models.value_objects.field_confidence."""

from __future__ import annotations

import dataclasses

import pytest

from vaultseek.models.value_objects.field_confidence import FieldConfidence


def test_field_confidence_stores_all_fields() -> None:
    confidence = FieldConfidence(
        field="artist", value="Allen Watts", confidence=0.95, source="musicbrainz"
    )

    assert confidence.field == "artist"
    assert confidence.value == "Allen Watts"
    assert confidence.confidence == 0.95
    assert confidence.source == "musicbrainz"


def test_field_confidence_accepts_none_value_for_unresolved_field() -> None:
    confidence = FieldConfidence(field="year", value=None, confidence=0.0, source="local_tags")

    assert confidence.value is None


def test_field_confidence_is_immutable() -> None:
    confidence = FieldConfidence(field="title", value="Indicator", confidence=1.0, source="mbid")

    with pytest.raises(dataclasses.FrozenInstanceError):
        confidence.confidence = 0.5  # type: ignore[misc]

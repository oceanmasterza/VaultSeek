"""Unit tests for vaultseek.models.entities.rule."""

from __future__ import annotations

from datetime import UTC, datetime

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.rule import Rule

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_rule(**overrides: object) -> Rule:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": generate_uuid7(),
        "name": "Archive MP3 when FLAC exists",
        "conditions": {"all": [{"field": "codec", "op": "eq", "value": "mp3"}]},
        "actions": [{"type": "move_to_zone", "params": {"zone": "archive"}}],
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Rule(**defaults)  # type: ignore[arg-type]


def test_rule_applies_documented_defaults() -> None:
    rule = _make_rule()

    assert rule.enabled is True
    assert rule.priority == 100
    assert rule.requires_approval is False


def test_rule_conditions_and_actions_are_arbitrary_json_like_structures() -> None:
    rule = _make_rule()

    assert rule.conditions["all"][0]["field"] == "codec"
    assert rule.actions[0]["type"] == "move_to_zone"


def test_rule_can_require_approval() -> None:
    rule = _make_rule(requires_approval=True, enabled=False)

    assert rule.requires_approval is True
    assert rule.enabled is False

"""Unit tests for musicvault.db.repositories.rule_repo.RuleRepository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from musicvault.db.repositories.rule_repo import RuleRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.rule import Rule

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_rule(library_id: UUID, **overrides: object) -> Rule:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": library_id,
        "name": "Move classical to archive",
        "conditions": {"genre": "Classical"},
        "actions": [{"type": "move", "target_zone": "archive"}],
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Rule(**defaults)  # type: ignore[arg-type]


def test_create_and_get_round_trips_every_field(engine: Engine, library_id: UUID) -> None:
    repo = RuleRepository(engine)
    rule = _make_rule(library_id, priority=10, requires_approval=True)

    repo.create(rule)
    loaded = repo.get(rule.id)

    assert loaded == rule


def test_get_returns_none_for_missing_rule(engine: Engine) -> None:
    repo = RuleRepository(engine)

    assert repo.get(generate_uuid7()) is None


def test_list_enabled_excludes_disabled_rules(engine: Engine, library_id: UUID) -> None:
    repo = RuleRepository(engine)
    enabled = _make_rule(library_id, name="enabled", enabled=True)
    disabled = _make_rule(library_id, name="disabled", enabled=False)
    repo.create(enabled)
    repo.create(disabled)

    results = repo.list_enabled(library_id)

    assert {rule.id for rule in results} == {enabled.id}


def test_list_enabled_orders_by_priority_ascending(engine: Engine, library_id: UUID) -> None:
    repo = RuleRepository(engine)
    low_priority = _make_rule(library_id, name="low", priority=200)
    high_priority = _make_rule(library_id, name="high", priority=10)
    repo.create(low_priority)
    repo.create(high_priority)

    results = repo.list_enabled(library_id)

    assert [rule.id for rule in results] == [high_priority.id, low_priority.id]


def test_update_persists_changes(engine: Engine, library_id: UUID) -> None:
    repo = RuleRepository(engine)
    rule = _make_rule(library_id, enabled=True)
    repo.create(rule)

    updated = replace(rule, enabled=False, name="renamed")
    repo.update(updated)

    loaded = repo.get(rule.id)
    assert loaded is not None
    assert loaded.enabled is False
    assert loaded.name == "renamed"

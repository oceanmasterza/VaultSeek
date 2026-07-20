"""Unit tests for vaultseek.models.value_objects.rule_action."""

from __future__ import annotations

import dataclasses

import pytest

from vaultseek.models.value_objects.rule_action import RuleAction


def test_rule_action_defaults_to_empty_parameters() -> None:
    action = RuleAction(action_type="flag_review")

    assert action.parameters == {}


def test_rule_action_stores_arbitrary_parameters() -> None:
    action = RuleAction(action_type="move_to_zone", parameters={"zone": "archive"})

    assert action.parameters == {"zone": "archive"}


def test_rule_action_is_immutable() -> None:
    action = RuleAction(action_type="flag_review")

    with pytest.raises(dataclasses.FrozenInstanceError):
        action.action_type = "set_genre"  # type: ignore[misc]


def test_each_rule_action_gets_an_independent_parameters_dict() -> None:
    first = RuleAction(action_type="flag_review")
    second = RuleAction(action_type="flag_review")

    first.parameters["reason"] = "test"

    assert second.parameters == {}

"""Unit tests for musicvault.models.value_objects.rule_condition."""

from __future__ import annotations

import pytest

from musicvault.models.value_objects.rule_condition import (
    AndNode,
    ConditionLeaf,
    OrNode,
    RuleNode,
    parse_conditions,
)


class TestConditionLeafOperators:
    def test_eq_matches_equal_values(self) -> None:
        leaf = ConditionLeaf(field="codec", operator="eq", value="mp3")

        assert leaf.evaluate({"codec": "mp3"}) is True
        assert leaf.evaluate({"codec": "flac"}) is False

    def test_ne_matches_unequal_values(self) -> None:
        leaf = ConditionLeaf(field="codec", operator="ne", value="mp3")

        assert leaf.evaluate({"codec": "flac"}) is True
        assert leaf.evaluate({"codec": "mp3"}) is False

    def test_lt_matches_smaller_values(self) -> None:
        leaf = ConditionLeaf(field="bitrate", operator="lt", value=192)

        assert leaf.evaluate({"bitrate": 128}) is True
        assert leaf.evaluate({"bitrate": 256}) is False

    def test_lt_is_false_when_field_missing(self) -> None:
        leaf = ConditionLeaf(field="bitrate", operator="lt", value=192)

        assert leaf.evaluate({}) is False

    def test_gt_matches_larger_values(self) -> None:
        leaf = ConditionLeaf(field="bitrate", operator="gt", value=192)

        assert leaf.evaluate({"bitrate": 256}) is True
        assert leaf.evaluate({"bitrate": 128}) is False

    def test_gt_is_false_when_field_missing(self) -> None:
        leaf = ConditionLeaf(field="bitrate", operator="gt", value=192)

        assert leaf.evaluate({}) is False

    def test_contains_matches_substring(self) -> None:
        leaf = ConditionLeaf(field="filename", operator="contains", value="VA")

        assert leaf.evaluate({"filename": "VA - Compilation"}) is True
        assert leaf.evaluate({"filename": "Solo Artist"}) is False

    def test_contains_is_false_when_field_missing(self) -> None:
        leaf = ConditionLeaf(field="filename", operator="contains", value="VA")

        assert leaf.evaluate({}) is False

    def test_matches_evaluates_regex_against_field(self) -> None:
        leaf = ConditionLeaf(field="title", operator="matches", value=r"^\d+ -")

        assert leaf.evaluate({"title": "01 - Track Name"}) is True
        assert leaf.evaluate({"title": "Track Name"}) is False

    def test_matches_is_false_when_field_missing(self) -> None:
        leaf = ConditionLeaf(field="title", operator="matches", value=r"^\d+")

        assert leaf.evaluate({}) is False

    def test_unknown_operator_raises_value_error(self) -> None:
        leaf = ConditionLeaf(field="codec", operator="fuzzy_match", value="mp3")

        with pytest.raises(ValueError, match="fuzzy_match"):
            leaf.evaluate({"codec": "mp3"})


class TestAndOrNodes:
    def test_and_node_true_only_if_all_children_true(self) -> None:
        node = AndNode(
            children=[
                ConditionLeaf(field="codec", operator="eq", value="mp3"),
                ConditionLeaf(field="has_lossless_duplicate", operator="eq", value=True),
            ]
        )

        assert node.evaluate({"codec": "mp3", "has_lossless_duplicate": True}) is True
        assert node.evaluate({"codec": "mp3", "has_lossless_duplicate": False}) is False

    def test_or_node_true_if_any_child_true(self) -> None:
        node = OrNode(
            children=[
                ConditionLeaf(field="codec", operator="eq", value="mp3"),
                ConditionLeaf(field="codec", operator="eq", value="aac"),
            ]
        )

        assert node.evaluate({"codec": "aac"}) is True
        assert node.evaluate({"codec": "flac"}) is False

    def test_and_node_with_no_children_is_vacuously_true(self) -> None:
        assert AndNode(children=[]).evaluate({}) is True

    def test_or_node_with_no_children_is_vacuously_false(self) -> None:
        assert OrNode(children=[]).evaluate({}) is False

    def test_nodes_nest_arbitrarily(self) -> None:
        tree = AndNode(
            children=[
                ConditionLeaf(field="zone", operator="eq", value="staging"),
                OrNode(
                    children=[
                        ConditionLeaf(field="codec", operator="eq", value="mp3"),
                        ConditionLeaf(field="codec", operator="eq", value="aac"),
                    ]
                ),
            ]
        )

        assert tree.evaluate({"zone": "staging", "codec": "aac"}) is True
        assert tree.evaluate({"zone": "library", "codec": "aac"}) is False


class TestRuleNodeBase:
    def test_base_class_evaluate_is_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            RuleNode().evaluate({})


class TestParseConditions:
    def test_parses_a_single_leaf(self) -> None:
        node = parse_conditions({"field": "codec", "operator": "eq", "value": "mp3"})

        assert node == ConditionLeaf(field="codec", operator="eq", value="mp3")

    def test_parses_an_all_group_into_and_node(self) -> None:
        node = parse_conditions(
            {
                "all": [
                    {"field": "codec", "operator": "eq", "value": "mp3"},
                    {"field": "has_lossless_duplicate", "operator": "eq", "value": True},
                ]
            }
        )

        assert isinstance(node, AndNode)
        assert len(node.children) == 2

    def test_parses_an_any_group_into_or_node(self) -> None:
        node = parse_conditions(
            {
                "any": [
                    {"field": "codec", "operator": "eq", "value": "mp3"},
                    {"field": "codec", "operator": "eq", "value": "aac"},
                ]
            }
        )

        assert isinstance(node, OrNode)
        assert len(node.children) == 2

    def test_parses_nested_groups_recursively(self) -> None:
        node = parse_conditions(
            {
                "all": [
                    {"field": "zone", "operator": "eq", "value": "staging"},
                    {
                        "any": [
                            {"field": "codec", "operator": "eq", "value": "mp3"},
                            {"field": "codec", "operator": "eq", "value": "aac"},
                        ]
                    },
                ]
            }
        )

        assert isinstance(node, AndNode)
        assert isinstance(node.children[1], OrNode)

    def test_malformed_leaf_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Malformed rule condition"):
            parse_conditions({"field": "codec"})  # missing operator/value

    def test_end_to_end_example_from_docs_evaluates_correctly(self) -> None:
        """See docs/architecture/12-pipeline-engine-v3.md, "Rules Engine —
        AST Evaluation" for the source rule this mirrors."""
        node = parse_conditions(
            {
                "all": [
                    {"field": "codec", "operator": "eq", "value": "mp3"},
                    {"field": "has_lossless_duplicate", "operator": "eq", "value": True},
                ]
            }
        )

        assert node.evaluate({"codec": "mp3", "has_lossless_duplicate": True}) is True
        assert node.evaluate({"codec": "flac", "has_lossless_duplicate": True}) is False

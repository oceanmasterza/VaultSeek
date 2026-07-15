"""Rule condition AST — parses and evaluates a rule's condition tree.

Implements the AST evaluation approach specified in
docs/architecture/12-pipeline-engine-v3.md ("Rules Engine — AST
Evaluation"), which supersedes v2's flat JSON condition list. Field
names (``field``, ``operator``, ``value``) follow the `RuleCondition`
dataclass in docs/architecture/10-revision-v2.md — see the correction
note in 12-pipeline-engine-v3.md for why ``operator`` (not ``op``) is
canonical.

This module is pure, dependency-free logic: :func:`parse_conditions`
turns the JSON-like dict already stored in
:attr:`~musicvault.models.entities.rule.Rule.conditions` into a typed
tree, and each node's :meth:`RuleNode.evaluate` walks that tree against
a plain context mapping. Building the actual context from a `Track`
(including duplicate-detection flags like `has_lossless_duplicate`,
which don't exist until Phase 9) and loading/running rules from
`RuleRepository` is `RulesEngine`'s job — Phase 8 scope.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuleNode:
    """Base class for a node in a rule's condition tree.

    Subclasses override :meth:`evaluate`; this base implementation
    exists only so :class:`AndNode`/:class:`OrNode` can hold a
    heterogeneous ``children: list[RuleNode]`` without a separate
    marker/protocol type.
    """

    def evaluate(self, context: Mapping[str, Any]) -> bool:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ConditionLeaf(RuleNode):
    """A single field/operator/value comparison — a leaf of the tree."""

    field: str
    operator: str
    value: Any

    def evaluate(self, context: Mapping[str, Any]) -> bool:
        try:
            compare = _OPERATORS[self.operator]
        except KeyError:
            raise ValueError(f"Unknown rule operator: {self.operator!r}") from None
        return compare(context.get(self.field), self.value)


@dataclass(frozen=True, slots=True)
class AndNode(RuleNode):
    """True only if every child node evaluates to True."""

    children: list[RuleNode] = field(default_factory=list)

    def evaluate(self, context: Mapping[str, Any]) -> bool:
        return all(child.evaluate(context) for child in self.children)


@dataclass(frozen=True, slots=True)
class OrNode(RuleNode):
    """True if any child node evaluates to True."""

    children: list[RuleNode] = field(default_factory=list)

    def evaluate(self, context: Mapping[str, Any]) -> bool:
        return any(child.evaluate(context) for child in self.children)


def _op_eq(actual: Any, expected: Any) -> bool:
    return bool(actual == expected)


def _op_ne(actual: Any, expected: Any) -> bool:
    return bool(actual != expected)


def _op_lt(actual: Any, expected: Any) -> bool:
    return actual is not None and bool(actual < expected)


def _op_gt(actual: Any, expected: Any) -> bool:
    return actual is not None and bool(actual > expected)


def _op_contains(actual: Any, expected: Any) -> bool:
    return actual is not None and bool(expected in actual)


def _op_matches(actual: Any, expected: Any) -> bool:
    return actual is not None and re.search(str(expected), str(actual)) is not None


_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": _op_eq,
    "ne": _op_ne,
    "lt": _op_lt,
    "gt": _op_gt,
    "contains": _op_contains,
    "matches": _op_matches,
}


def parse_conditions(raw: Mapping[str, Any]) -> RuleNode:
    """Parse a JSON-like dict (as stored in `Rule.conditions`) into a `RuleNode` tree.

    Accepts three shapes, matching the documented rule YAML:
        - ``{"all": [...]}`` — an :class:`AndNode` of parsed children
        - ``{"any": [...]}`` — an :class:`OrNode` of parsed children
        - ``{"field": ..., "operator": ..., "value": ...}`` — a :class:`ConditionLeaf`

    Raises:
        ValueError: if ``raw`` matches none of the above shapes.
    """
    if "all" in raw:
        return AndNode(children=[parse_conditions(child) for child in raw["all"]])
    if "any" in raw:
        return OrNode(children=[parse_conditions(child) for child in raw["any"]])
    try:
        return ConditionLeaf(field=raw["field"], operator=raw["operator"], value=raw["value"])
    except KeyError as exc:
        raise ValueError(f"Malformed rule condition: {raw!r}") from exc

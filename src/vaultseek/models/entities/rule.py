"""Rule entity — a single user-configurable automation rule.

Mirrors the `rules` table (see docs/architecture/03-database-schema.md,
"Rules Engine"). Pulled forward from Phase 3 for the same reason as
:class:`~vaultseek.models.entities.job.Job`. `conditions` and `actions`
are kept as plain parsed JSON here rather than the typed AST — that AST
now exists as a Phase 3 pure value object
(:mod:`vaultseek.models.value_objects.rule_condition`,
:mod:`vaultseek.models.value_objects.rule_action`), but *loading* rules
from this repository and running them through that AST against real
tracks is `RulesEngine`'s job (Phase 8; see
docs/architecture/12-pipeline-engine-v3.md, "Rules Engine — AST
Evaluation"). This entity only needs to persist and retrieve whatever
JSON a future rules editor produces — `Rule.conditions` is exactly the
shape :func:`~vaultseek.models.value_objects.rule_condition.parse_conditions`
expects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Rule:
    """A single automation rule, persisted in the `rules` table."""

    id: UUID
    library_id: UUID
    name: str
    conditions: dict[str, Any]
    actions: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    enabled: bool = True
    priority: int = 100
    requires_approval: bool = False

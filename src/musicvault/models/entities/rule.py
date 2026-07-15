"""Rule entity — a single user-configurable automation rule.

Mirrors the `rules` table (see docs/architecture/03-database-schema.md,
"Rules Engine"). Pulled forward from Phase 3 for the same reason as
:class:`~musicvault.models.entities.job.Job`. `conditions` and `actions`
are kept as plain parsed JSON here rather than a typed AST — designing
that AST is explicitly Phase 8 scope (see
docs/architecture/12-pipeline-engine-v3.md, "Rules Engine — AST
Evaluation"); this entity only needs to persist and retrieve whatever
JSON a future rules editor produces.
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

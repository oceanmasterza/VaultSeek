"""RuleRepository — persistence for the `rules` table."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, delete, insert, select, update

from vaultseek.db.tables import rules as rules_table
from vaultseek.db.uuid_utils import blob_to_uuid, uuid_to_blob
from vaultseek.models.entities.rule import Rule


class RuleRepository:
    """Reads and writes `Rule` entities against the `rules` table."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, rule: Rule) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(rules_table).values(**_to_row(rule)))

    def get(self, rule_id: UUID) -> Rule | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(rules_table).where(rules_table.c.id == uuid_to_blob(rule_id))
            ).first()
        return _from_row(row) if row is not None else None

    def list_enabled(self, library_id: UUID) -> list[Rule]:
        """All enabled rules for a library, highest priority (lowest number) first."""
        statement = (
            select(rules_table)
            .where(rules_table.c.library_id == uuid_to_blob(library_id))
            .where(rules_table.c.enabled.is_(True))
            .order_by(rules_table.c.priority.asc())
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def list_by_library(self, library_id: UUID) -> list[Rule]:
        """All rules for a library (enabled and disabled), priority ascending."""
        statement = (
            select(rules_table)
            .where(rules_table.c.library_id == uuid_to_blob(library_id))
            .order_by(rules_table.c.priority.asc())
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def find_by_name(self, library_id: UUID, name: str) -> Rule | None:
        statement = (
            select(rules_table)
            .where(rules_table.c.library_id == uuid_to_blob(library_id))
            .where(rules_table.c.name == name)
        )
        with self._engine.connect() as conn:
            row = conn.execute(statement).first()
        return _from_row(row) if row is not None else None

    def update(self, rule: Rule) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(rules_table)
                .where(rules_table.c.id == uuid_to_blob(rule.id))
                .values(**_to_row(rule))
            )

    def delete(self, rule_id: UUID) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(rules_table).where(rules_table.c.id == uuid_to_blob(rule_id)))


def _to_row(rule: Rule) -> dict[str, object]:
    return {
        "id": uuid_to_blob(rule.id),
        "library_id": uuid_to_blob(rule.library_id),
        "name": rule.name,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "conditions": json.dumps(rule.conditions),
        "actions": json.dumps(rule.actions),
        "requires_approval": rule.requires_approval,
        "created_at": rule.created_at.isoformat(),
        "updated_at": rule.updated_at.isoformat(),
    }


def _from_row(row: Row[Any]) -> Rule:
    return Rule(
        id=blob_to_uuid(row.id),
        library_id=blob_to_uuid(row.library_id),
        name=row.name,
        conditions=json.loads(row.conditions),
        actions=json.loads(row.actions),
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
        enabled=bool(row.enabled),
        priority=row.priority,
        requires_approval=bool(row.requires_approval),
    )

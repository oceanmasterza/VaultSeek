"""RuleAction value object — a single effect a matched rule triggers.

Mirrors the shape documented in docs/architecture/10-revision-v2.md
("Rules Engine" → Rule Model) — unchanged by the v3 AST revision in
docs/architecture/12-pipeline-engine-v3.md, which only replaces how
*conditions* are represented (see
:mod:`musicvault.models.value_objects.rule_condition`); actions stay a
flat `action_type` + `parameters` shape both before and after that
revision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuleAction:
    """One action to take when a rule's conditions match a track.

    ``action_type`` is an open vocabulary (e.g. ``"move_to_zone"``,
    ``"flag_review"``, ``"set_genre"``) rather than an enum, since the
    set of supported actions is defined by whichever worker actually
    executes them (`RuleWorker`, Phase 8) — that worker is the natural
    place to validate/reject an unrecognized `action_type`, not this
    value object.
    """

    action_type: str
    parameters: dict[str, Any] = field(default_factory=dict)

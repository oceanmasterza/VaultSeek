"""Shipped default automation rules (Phase 8).

YAML shapes match docs/architecture/10-revision-v2.md. The archive-MP3
rule depends on ``has_lossless_duplicate`` (Phase 9) and ``move_to_zone``
(Phase 10); it is seeded so evaluate/CRUD work, but will not match or
move files until those phases land.
"""

from __future__ import annotations

from typing import Any

# Priority: lower number = higher priority (RuleRepository.list_enabled).
DEFAULT_RULE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "Archive MP3 when FLAC exists",
        "priority": 10,
        "requires_approval": True,
        "conditions": {
            "all": [
                {"field": "codec", "operator": "eq", "value": "mp3"},
                {"field": "has_lossless_duplicate", "operator": "eq", "value": True},
            ]
        },
        "actions": [
            {
                "action_type": "move_to_zone",
                "parameters": {"zone": "archive"},
            }
        ],
    },
    {
        "name": "Detect Various Artists",
        "priority": 20,
        "requires_approval": False,
        "conditions": {
            "all": [
                {"field": "artist", "operator": "eq", "value": ""},
                {"field": "filename", "operator": "contains", "value": "VA"},
            ]
        },
        "actions": [
            {
                "action_type": "set_artist",
                "parameters": {"artist": "Various Artists"},
            },
            {
                "action_type": "flag_review",
                "parameters": {
                    "reason": "Detected VA from filename",
                    "review_type": "rule_action",
                },
            },
        ],
    },
    {
        "name": "Flag low bitrate",
        "priority": 30,
        "requires_approval": False,
        "conditions": {
            "all": [
                {"field": "bitrate", "operator": "lt", "value": 192},
            ]
        },
        "actions": [
            {
                "action_type": "flag_review",
                "parameters": {
                    "reason": "Bitrate below 192 kbps",
                    "review_type": "low_quality",
                },
            }
        ],
    },
)

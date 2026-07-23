"""Tests for the Ctrl+K jump palette helpers."""

from __future__ import annotations

from vaultseek.gui.main_window import _NAV_HUBS
from vaultseek.gui.widgets.jump_palette import jump_destinations_from_hubs


def test_jump_destinations_cover_all_hub_leaves() -> None:
    rows = jump_destinations_from_hubs(_NAV_HUBS)
    keys = [key for _label, key in rows]
    assert "dashboard" in keys
    assert "find" in keys
    assert "acquisition" in keys
    assert "activity" in keys
    assert "settings" in keys
    assert len(keys) == len(set(keys))
    assert any(label.startswith("Find & get ·") for label, _ in rows)
    assert any(label == "System · Activity" for label, _ in rows)

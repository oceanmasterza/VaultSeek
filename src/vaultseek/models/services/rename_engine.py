"""RenameEngine — cleans scene-release-style filenames.

Implements exactly the three documented examples from
docs/architecture/09-testing-strategy.md ("Domain Layer",
`TestRenameEngine`). Scene-release naming conventions append a
dash-prefixed group/tag block (`-(KR147)-SINGLE-16BIT-WEB-FLAC-2024-FMC`,
`-[AFO]-WEB-FLAC`) after the real "Artist - Title" content; this class
strips everything from the first such block onward.

No other cleanup heuristics (e.g. handling scene tags with no leading
bracket, or normalizing case) are documented anywhere, so this
implementation deliberately does *not* guess at them — it only
satisfies the documented cases. Extend it with new test cases first if
real-world filenames need more.

The "configurable folder structures" half of the README's "Organize &
rename" feature is `OrganizeEngine` (Phase 10) — this class only
handles the filename-cleaning half.
"""

from __future__ import annotations

import re

_SCENE_TAG_BLOCK = re.compile(r"-[([]")


class RenameEngine:
    """Strips scene-release tag blocks from a filename (extension-less)."""

    def clean_filename(self, name: str) -> str:
        """Replace underscores with spaces, then drop everything from the
        first `-(` or `-[` scene-tag block onward."""
        cleaned = name.replace("_", " ")
        match = _SCENE_TAG_BLOCK.search(cleaned)
        if match is not None:
            cleaned = cleaned[: match.start()]
        return cleaned.strip()

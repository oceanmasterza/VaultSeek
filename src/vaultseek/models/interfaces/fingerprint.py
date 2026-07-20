"""Fingerprint provider protocol — Chromaprint generation.

See docs/architecture/05-plugin-api.md ("Fingerprint Provider") and
docs/architecture/12-pipeline-engine-v3.md (Tier 1 ProcessPool). AcoustID
*HTTP* lookup (turning a fingerprint into MusicBrainz IDs) is a metadata
provider concern and lives in Phase 6 — this protocol is only about
producing Chromaprint bytes from an audio file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FingerprintResult:
    """Chromaprint output for one audio file."""

    duration_seconds: float
    fingerprint_data: bytes
    fingerprint_hash: str


class FingerprintProvider(Protocol):
    """Generates a Chromaprint fingerprint for a local audio file."""

    def fingerprint_file(self, path: Path) -> FingerprintResult:
        """Compute a Chromaprint for ``path``.

        Raises:
            OSError: if the file cannot be read.
            RuntimeError: if the Chromaprint backend (fpcalc / chromaprint)
                is missing or fails to produce a fingerprint.
        """
        ...

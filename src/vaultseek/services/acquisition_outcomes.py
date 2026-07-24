"""Acquisition outcome codes — machine-readable reasons for automation.

These codes segment every acquisition attempt so the background loop can
retry the right way and only escalate to human review when the song is
genuinely unavailable on the network after repeated empty searches.

Categories the UI / automation care about:

1. **Acquired** — downloaded (or already owned in the library).
2. **Found but blocked** — hits exist; peer offline / not sharing / timeout /
   quality below threshold / verify hiccup. Keep trying other peers/results.
3. **Not found (this attempt)** — empty search. Keep trying; do **not** park
   in Review until exhausted.
4. **Exhausted** — only then Review: song appears absent from Soulseek.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from vaultseek.models.entities.acquisition_job import AcquisitionJob


class AcquisitionOutcomeCode(StrEnum):
    """Stable codes stored on ``AcquisitionJob.extra['outcome_code']``."""

    ACQUIRED = "acquired"
    ALREADY_OWNED = "already_owned"

    SEARCH_EMPTY = "search_empty"
    SEARCH_DEFERRED = "search_deferred"
    PROVIDER_OFFLINE = "provider_offline"
    PROVIDER_ERROR = "provider_error"

    FOUND_NOT_SHARED = "found_not_shared"
    FOUND_USER_OFFLINE = "found_user_offline"
    FOUND_TIMEOUT = "found_timeout"
    FOUND_DOWNLOAD_FAILED = "found_download_failed"
    FOUND_BELOW_THRESHOLD = "found_below_threshold"

    VERIFY_MISSING_FILE = "verify_missing_file"
    VERIFY_FAILED = "verify_failed"
    IMPORT_FAILED = "import_failed"

    EXHAUSTED_NOT_ON_NETWORK = "exhausted_not_on_network"


# Transient / expected — automation keeps working; never Review by itself.
_RETRYABLE: frozenset[AcquisitionOutcomeCode] = frozenset(
    {
        AcquisitionOutcomeCode.SEARCH_EMPTY,
        AcquisitionOutcomeCode.SEARCH_DEFERRED,
        AcquisitionOutcomeCode.PROVIDER_OFFLINE,
        AcquisitionOutcomeCode.PROVIDER_ERROR,
        AcquisitionOutcomeCode.FOUND_NOT_SHARED,
        AcquisitionOutcomeCode.FOUND_USER_OFFLINE,
        AcquisitionOutcomeCode.FOUND_TIMEOUT,
        AcquisitionOutcomeCode.FOUND_DOWNLOAD_FAILED,
        AcquisitionOutcomeCode.FOUND_BELOW_THRESHOLD,
        AcquisitionOutcomeCode.VERIFY_MISSING_FILE,
        AcquisitionOutcomeCode.VERIFY_FAILED,
        AcquisitionOutcomeCode.IMPORT_FAILED,
    }
)

# Only these belong under Review for acquisition (human truly needed).
_REVIEWABLE: frozenset[AcquisitionOutcomeCode] = frozenset(
    {
        AcquisitionOutcomeCode.EXHAUSTED_NOT_ON_NETWORK,
    }
)

_HUMAN_LABELS: dict[AcquisitionOutcomeCode, str] = {
    AcquisitionOutcomeCode.ACQUIRED: "Downloaded and imported",
    AcquisitionOutcomeCode.ALREADY_OWNED: "Already in library (duplicate match)",
    AcquisitionOutcomeCode.SEARCH_EMPTY: "No Soulseek hits this attempt — will retry",
    AcquisitionOutcomeCode.SEARCH_DEFERRED: "Search deferred (Soulseek rate limit)",
    AcquisitionOutcomeCode.PROVIDER_OFFLINE: "Nicotine+ / Soulseek offline — will retry",
    AcquisitionOutcomeCode.PROVIDER_ERROR: "Nicotine+ API error — will retry",
    AcquisitionOutcomeCode.FOUND_NOT_SHARED: "Found, but peer is not sharing the file",
    AcquisitionOutcomeCode.FOUND_USER_OFFLINE: "Found, but peer went offline",
    AcquisitionOutcomeCode.FOUND_TIMEOUT: "Found, but transfer timed out",
    AcquisitionOutcomeCode.FOUND_DOWNLOAD_FAILED: "Found, but download failed",
    AcquisitionOutcomeCode.FOUND_BELOW_THRESHOLD: "Found hits below auto-acquire quality threshold",
    AcquisitionOutcomeCode.VERIFY_MISSING_FILE: "Download reported complete but file missing",
    AcquisitionOutcomeCode.VERIFY_FAILED: "Downloaded file failed verification",
    AcquisitionOutcomeCode.IMPORT_FAILED: "Verified but import into Incoming failed",
    AcquisitionOutcomeCode.EXHAUSTED_NOT_ON_NETWORK: "Not found on Soulseek after repeated searches",
}


def outcome_label(code: AcquisitionOutcomeCode | str | None) -> str:
    if code is None:
        return ""
    try:
        parsed = AcquisitionOutcomeCode(str(code))
    except ValueError:
        return str(code)
    return _HUMAN_LABELS.get(parsed, parsed.value)


def is_retryable(code: AcquisitionOutcomeCode | str | None) -> bool:
    parsed = _parse(code)
    return parsed in _RETRYABLE if parsed else False


def should_park_in_review(code: AcquisitionOutcomeCode | str | None) -> bool:
    """True only for outcomes that need a human (song appears unavailable)."""
    parsed = _parse(code)
    return parsed in _REVIEWABLE if parsed else False


def job_outcome_code(job: AcquisitionJob) -> AcquisitionOutcomeCode | None:
    return _parse(job.extra.get("outcome_code"))


def outcome_extra(
    code: AcquisitionOutcomeCode,
    *,
    detail: str = "",
    **fields: Any,
) -> dict[str, Any]:
    """Build an ``update_extra`` payload for an outcome."""
    payload: dict[str, Any] = {
        "outcome_code": code.value,
        "outcome_label": outcome_label(code),
    }
    if detail:
        payload["outcome_detail"] = detail
    payload.update(fields)
    return payload


def classify_download_message(message: str | None) -> AcquisitionOutcomeCode:
    text = (message or "").casefold().strip()
    if "not shared" in text:
        return AcquisitionOutcomeCode.FOUND_NOT_SHARED
    if "logged off" in text or "user offline" in text:
        return AcquisitionOutcomeCode.FOUND_USER_OFFLINE
    if "timeout" in text:
        return AcquisitionOutcomeCode.FOUND_TIMEOUT
    if "connection closed" in text:
        return AcquisitionOutcomeCode.FOUND_USER_OFFLINE
    return AcquisitionOutcomeCode.FOUND_DOWNLOAD_FAILED


def classify_verification_failures(
    failures: tuple[str, ...] | list[str],
) -> AcquisitionOutcomeCode:
    if not failures:
        return AcquisitionOutcomeCode.VERIFY_FAILED
    if all(f.startswith("duplicate_") for f in failures):
        return AcquisitionOutcomeCode.ALREADY_OWNED
    if any(f.startswith("missing_file") or f == "no_local_paths" for f in failures):
        if all(
            f.startswith("missing_file")
            or f == "no_local_paths"
            or f.startswith("duplicate_")
            for f in failures
        ):
            # Only missing (+ optional dups on other paths) → treat as missing.
            if any(f.startswith("missing_file") or f == "no_local_paths" for f in failures):
                present_unique = [
                    f
                    for f in failures
                    if not f.startswith("missing_file")
                    and f != "no_local_paths"
                    and not f.startswith("duplicate_")
                ]
                if not present_unique and any(f.startswith("duplicate_") for f in failures):
                    # Mix of missing + duplicate: prefer already-owned when any dup hit.
                    return AcquisitionOutcomeCode.ALREADY_OWNED
                return AcquisitionOutcomeCode.VERIFY_MISSING_FILE
        return AcquisitionOutcomeCode.VERIFY_MISSING_FILE
    return AcquisitionOutcomeCode.VERIFY_FAILED


def _parse(code: AcquisitionOutcomeCode | str | None) -> AcquisitionOutcomeCode | None:
    if code is None:
        return None
    if isinstance(code, AcquisitionOutcomeCode):
        return code
    try:
        return AcquisitionOutcomeCode(str(code))
    except ValueError:
        return None

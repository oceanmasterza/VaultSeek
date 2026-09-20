"""Acquisition search source ids, labels, and order helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

# User-facing search waterfall tiers (reorderable in Settings).
SEARCH_SOURCE_LABELS: dict[str, str] = {
    "nicotine_plus": "1. Nicotine+ (Soulseek)",
    "usenet": "2. Usenet / news servers (Prowlarr → SABnzbd or NZBGet)",
    "prowlarr_public": "3a. Prowlarr public trackers (→ qBittorrent)",
    "prowlarr_private": "3b. Prowlarr private trackers (→ qBittorrent)",
}

# Canonical default order matching the product waterfall.
DEFAULT_SEARCH_PROVIDER_ORDER: tuple[str, ...] = (
    "nicotine_plus",
    "usenet",
    "prowlarr_public",
    "prowlarr_private",
    "stub",
)

_PROWLARR_SPLIT: tuple[str, ...] = ("usenet", "prowlarr_public", "prowlarr_private")
_LEGACY_PROWLARR = frozenset({"prowlarr", "prowlarr_qbit"})


def normalize_provider_id(provider_id: str) -> str:
    """Map legacy ids onto the current split set (identity for known ids)."""
    if provider_id in _LEGACY_PROWLARR:
        return "prowlarr"  # expanded by expand_legacy_prowlarr
    return provider_id


def expand_legacy_prowlarr(order: Sequence[str]) -> list[str]:
    """Replace a single ``prowlarr`` / ``prowlarr_qbit`` entry with the three tiers."""
    out: list[str] = []
    for pid in order:
        if pid in _LEGACY_PROWLARR:
            for split in _PROWLARR_SPLIT:
                if split not in out:
                    out.append(split)
        elif pid not in out:
            out.append(pid)
    return out


def ensure_search_sources(order: Iterable[str]) -> list[str]:
    """Return order with every search-source id present once, then stub last if needed."""
    expanded = expand_legacy_prowlarr(list(order))
    known = [pid for pid in expanded if pid in SEARCH_SOURCE_LABELS or pid == "stub"]
    for pid in DEFAULT_SEARCH_PROVIDER_ORDER:
        if pid not in known:
            # Insert real sources before stub.
            if pid == "stub":
                known.append(pid)
            else:
                stub_at = known.index("stub") if "stub" in known else len(known)
                known.insert(stub_at, pid)
    return known


def label_for(provider_id: str) -> str:
    return SEARCH_SOURCE_LABELS.get(provider_id, provider_id)

"""Named library-quality presets mapped onto acquisition prefs.

Presets only set ``prefer_lossless``, ``preferred_codec``, and
``min_bitrate_kbps`` — the same fields orange traffic lights and upgrade
scans already read. ``custom`` means the user edited values by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

PRESET_COMPLETIST: Final = "completist"
PRESET_COLLECTOR: Final = "collector"
PRESET_LOSSY_OK: Final = "lossy_ok"
PRESET_CUSTOM: Final = "custom"

VALID_PRESETS: Final[frozenset[str]] = frozenset(
    {PRESET_COMPLETIST, PRESET_COLLECTOR, PRESET_LOSSY_OK, PRESET_CUSTOM}
)


@dataclass(frozen=True)
class QualityValues:
    prefer_lossless: bool
    preferred_codec: str
    min_bitrate_kbps: int


# (id, label, short description)
PRESET_CHOICES: Final[tuple[tuple[str, str, str], ...]] = (
    (
        PRESET_COMPLETIST,
        "Completist",
        "Prefer lossless (FLAC). No minimum bitrate for lossy files.",
    ),
    (
        PRESET_COLLECTOR,
        "Collector",
        "Prefer lossless; lossy must be at least 320 kbps.",
    ),
    (
        PRESET_LOSSY_OK,
        "Lossy OK",
        "Accept good MP3 (prefer MP3, min 192 kbps).",
    ),
    (
        PRESET_CUSTOM,
        "Custom",
        "Set prefer-lossless, codec, and bitrate yourself.",
    ),
)


_PRESET_VALUES: Final[dict[str, QualityValues]] = {
    PRESET_COMPLETIST: QualityValues(
        prefer_lossless=True,
        preferred_codec="",
        min_bitrate_kbps=0,
    ),
    PRESET_COLLECTOR: QualityValues(
        prefer_lossless=True,
        preferred_codec="",
        min_bitrate_kbps=320,
    ),
    PRESET_LOSSY_OK: QualityValues(
        prefer_lossless=False,
        preferred_codec="MP3",
        min_bitrate_kbps=192,
    ),
}


def normalize_preset_id(preset: str | None) -> str:
    key = (preset or "").strip().lower()
    return key if key in VALID_PRESETS else PRESET_CUSTOM


def values_for_preset(preset: str) -> QualityValues | None:
    """Return field values for a named preset, or None for Custom."""
    key = normalize_preset_id(preset)
    if key == PRESET_CUSTOM:
        return None
    return _PRESET_VALUES[key]


def infer_preset(
    *,
    prefer_lossless: bool,
    preferred_codec: str,
    min_bitrate_kbps: int,
) -> str:
    """Match current fields to a named preset, else Custom."""
    codec = (preferred_codec or "").strip()
    current = QualityValues(
        prefer_lossless=prefer_lossless,
        preferred_codec=codec,
        min_bitrate_kbps=int(min_bitrate_kbps),
    )
    for preset_id, values in _PRESET_VALUES.items():
        if (
            values.prefer_lossless == current.prefer_lossless
            and values.preferred_codec.lower() == current.preferred_codec.lower()
            and values.min_bitrate_kbps == current.min_bitrate_kbps
        ):
            return preset_id
    return PRESET_CUSTOM

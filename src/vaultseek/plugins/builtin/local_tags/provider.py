"""Local embedded-tags metadata provider (Mutagen)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from mutagen import File as MutagenFile

from vaultseek.models.interfaces.metadata import (
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)


class LocalTagsProvider:
    """Read ID3 / Vorbis / MP4 tags already embedded in the audio file."""

    provider_id = "local_tags"
    priority = 50
    plugin_id = "local_tags"

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        return None

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        if not query.file_path:
            return None
        path = Path(query.file_path)
        if not path.is_file():
            return None
        try:
            audio = MutagenFile(path, easy=True)
        except Exception:
            return None
        if audio is None:
            return None

        fields: list[ProviderFieldResult] = []
        # Core identity tags must clear the default 0.90 auto-approve gate.
        # Secondary tags stay lower and are excluded from overall confidence.
        mapping = {
            "title": ("title", 0.92),
            "artist": ("artist", 0.92),
            "album": ("album", 0.92),
            "genre": ("genre", 0.70),
            "composer": ("composer", 0.65),
        }
        for field_name, (tag_key, confidence) in mapping.items():
            value = _first(audio, tag_key)
            if value:
                fields.append(ProviderFieldResult(field_name, value, confidence))

        year = _parse_year(_first(audio, "date") or _first(audio, "year"))
        if year is not None:
            fields.append(ProviderFieldResult("year", year, 0.85))

        track_number = _parse_int(_first(audio, "tracknumber"))
        if track_number is not None:
            fields.append(ProviderFieldResult("track_number", track_number, 0.90))

        if not fields:
            return None
        return ProviderResult(
            provider_id=self.provider_id,
            fields=fields,
            overall_confidence=min(f.confidence for f in fields),
            lookup_method="tags",
            priority=self.priority,
        )

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None:
        return None

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]:
        return []


def _first(audio: Any, key: str) -> str | None:
    try:
        values = audio.get(key)
    except Exception:
        return None
    if not values:
        return None
    return str(values[0]).strip() or None


def _parse_year(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = "".join(ch for ch in raw[:4] if ch.isdigit())
    if len(digits) == 4:
        return int(digits)
    return None


def _parse_int(raw: str | None) -> int | None:
    if not raw:
        return None
    head = raw.split("/")[0].strip()
    return int(head) if head.isdigit() else None

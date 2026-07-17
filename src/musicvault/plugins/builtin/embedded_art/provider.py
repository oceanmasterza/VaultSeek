"""Embedded artwork provider — extracts pictures already inside the file.

Priority 50 per docs/architecture/05-plugin-api.md ("Artwork Providers":
Cover Art Archive 10 > Discogs 20 > Embedded 50) — a network fetch of
canonical release art is preferred over whatever a ripper embedded, but
embedded art needs no network and is the fallback for unidentified
tracks. Handles the three container families Mutagen exposes pictures
through: FLAC ``pictures``, ID3 ``APIC`` frames, and MP4 ``covr`` atoms.
Front covers (picture type 3) are preferred when the file carries
several images.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile

from musicvault.models.interfaces.artwork import ArtworkQuery, ArtworkResult
from musicvault.plugins.imaging import image_dimensions

_FRONT_COVER_TYPE = 3
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class EmbeddedArtProvider:
    """Read cover art embedded in the audio file's own tags."""

    provider_id = "embedded_art"
    priority = 50
    plugin_id = "embedded_art"

    def fetch(self, query: ArtworkQuery) -> ArtworkResult | None:
        if not query.file_path:
            return None
        path = Path(query.file_path)
        if not path.is_file():
            return None
        try:
            audio = MutagenFile(path)
        except Exception:
            return None
        if audio is None:
            return None

        extracted = _extract_picture(audio)
        if extracted is None:
            return None
        data, mime = extracted
        dimensions = image_dimensions(data)
        if dimensions is None:
            return None
        width, height = dimensions
        return ArtworkResult(
            source=self.provider_id,
            data=data,
            mime_type=mime,
            width=width,
            height=height,
            # Embedded art is byte-exact for *this* file but of unknown
            # provenance/quality — below any canonical archive match.
            confidence=0.70,
            source_id=None,
        )


def _extract_picture(audio: Any) -> tuple[bytes, str] | None:
    """Return ``(data, mime_type)`` for the best embedded picture."""
    pictures = getattr(audio, "pictures", None)
    if pictures:
        front = next((pic for pic in pictures if int(pic.type) == _FRONT_COVER_TYPE), pictures[0])
        return bytes(front.data), str(front.mime)

    tags = getattr(audio, "tags", None)
    if tags is None:
        return None

    getall = getattr(tags, "getall", None)
    if callable(getall):
        frames = getall("APIC")
        if frames:
            front = next(
                (frame for frame in frames if int(frame.type) == _FRONT_COVER_TYPE),
                frames[0],
            )
            return bytes(front.data), str(front.mime)

    try:
        covers = tags.get("covr")
    except Exception:
        return None
    if covers:
        data = bytes(covers[0])
        mime = "image/png" if data.startswith(_PNG_MAGIC) else "image/jpeg"
        return data, mime
    return None

"""Shared Pillow helpers for artwork plugins."""

from __future__ import annotations

import io

from PIL import Image


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return ``(width, height)`` for encoded image bytes, or ``None``
    when Pillow cannot decode them (truncated download, junk APIC frame)."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.width, image.height
    except Exception:
        return None

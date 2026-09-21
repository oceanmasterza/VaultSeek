"""Artwork browsing lives on the Albums page.

``ArtworkPage`` remains so older imports still construct the combined Albums
destination (covers, problems filter, tracks, archive, and delete).
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from vaultseek.core.container import Container
from vaultseek.gui.views.albums_page import AlbumsPage, _thumbnail

__all__ = ["ArtworkPage", "_thumbnail"]


class ArtworkPage(AlbumsPage):
    """Combined Albums view. The separate Artwork destination is an alias."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(container, parent)
        self.focus_artwork()

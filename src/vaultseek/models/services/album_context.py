"""Album-sameness helpers for duplicate detection.

Same recording on *different* albums (singles vs LPs, soundtracks,
compilations, remasters with distinct release titles) is a normal
collection pattern — not a duplicate. Identical file bytes remain a
duplicate regardless of tags.
"""

from __future__ import annotations

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.track import Track


def same_album_context(
    left: Track,
    right: Track,
    albums: AlbumRepository | None,
) -> bool:
    """True when both tracks belong to the same album release context.

    Comparison order:
    1. Same ``album_id`` foreign key
    2. Matching release / release-group MBIDs on the album rows
    3. Same album artist + normalized title (when MBIDs are absent)
    """
    if left.album_id is None or right.album_id is None:
        return False
    if left.album_id == right.album_id:
        return True
    if albums is None:
        return False
    album_left = albums.get(left.album_id)
    album_right = albums.get(right.album_id)
    if album_left is None or album_right is None:
        return False
    return albums_equivalent(album_left, album_right)


def albums_equivalent(left: Album, right: Album) -> bool:
    if left.mbid and right.mbid and left.mbid == right.mbid:
        return True
    if (
        left.release_group_mbid
        and right.release_group_mbid
        and left.release_group_mbid == right.release_group_mbid
    ):
        return True
    if _normalize_title(left.title) != _normalize_title(right.title):
        return False
    # Title alone is too weak ("Greatest Hits"); require the same album artist.
    if left.album_artist_id is None or right.album_artist_id is None:
        return False
    return left.album_artist_id == right.album_artist_id


def _normalize_title(title: str) -> str:
    return " ".join(title.casefold().split())

"""Hard gates for library tracklist matching / auto-approve."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.artist import Artist
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.interfaces.metadata import MetadataQuery
from vaultseek.services.library_tracklist_matcher import (
    AcquisitionProvenance,
    LibraryTracklistMatcher,
)

_NOW = datetime(2026, 9, 22, tzinfo=UTC)
_LIB = UUID("00000000-0000-7000-8000-000000000099")
_SALVATION_MBID = "2167db99-6fe0-4af8-8ae1-4fbe699008bf"


class _Tracks:
    def __init__(self, tracks: list[Track]) -> None:
        self._tracks = tracks

    def find_title_candidates(
        self, library_id: UUID, title_hint: str, *, limit: int = 80
    ) -> list[Track]:
        return [t for t in self._tracks if t.library_id == library_id][:limit]

    def list_by_album(self, library_id: UUID, album_id: UUID, *, limit: int = 500) -> list[Track]:
        return [t for t in self._tracks if t.library_id == library_id and t.album_id == album_id][
            :limit
        ]

    def list_by_path_prefix(
        self, library_id: UUID, path_prefix: str, *, limit: int = 500
    ) -> list[Track]:
        return [
            t
            for t in self._tracks
            if t.library_id == library_id and t.file_path.startswith(path_prefix)
        ][:limit]


class _Albums:
    def __init__(self, albums: list[Album]) -> None:
        self._by_id = {a.id: a for a in albums}

    def get(self, album_id: UUID) -> Album | None:
        return self._by_id.get(album_id)


class _Artists:
    def __init__(self, artists: list[Artist]) -> None:
        self._by_id = {a.id: a for a in artists}

    def get(self, artist_id: UUID) -> Artist | None:
        return self._by_id.get(artist_id)


def _track(**overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": _LIB,
        "zone": LibraryZone.LIBRARY,
        "file_path": r"C:\lib\a.flac",
        "file_name": "a.flac",
        "file_size": 1,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
        "disc_number": 1,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def _matcher(
    incoming: Track, library: list[Track], albums: list[Album], artists: list[Artist]
) -> LibraryTracklistMatcher:
    return LibraryTracklistMatcher(
        track_repo=_Tracks([incoming, *library]),  # type: ignore[arg-type]
        album_repo=_Albums(albums),  # type: ignore[arg-type]
        artist_repo=_Artists(artists),  # type: ignore[arg-type]
        confidence_threshold=0.90,
    )


def _alphaville() -> tuple[Artist, Album]:
    artist = Artist(
        id=generate_uuid7(),
        name="Alphaville",
        sort_name="Alphaville",
        created_at=_NOW,
        updated_at=_NOW,
    )
    album = Album(
        id=generate_uuid7(),
        title="Salvation",
        sort_title="Salvation",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
        mbid=_SALVATION_MBID,
    )
    return artist, album


def test_title_only_never_auto_approves() -> None:
    artist, album = _alphaville()
    existing = _track(
        title="Soul Messiah",
        file_name="10 - Soul Messiah.flac",
        album_id=album.id,
        artist_id=artist.id,
        track_number=10,
        duration_ms=295000,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="01a090ad",
        file_name="10 - Soul Messiah.mp3",
        file_path=r"C:\in\01a090ad-7dbc-7000-b76e-66601cf1998b\10 - Soul Messiah.mp3",
        duration_ms=None,
    )
    result = _matcher(incoming, [existing], [album], [artist]).match(
        incoming, MetadataQuery(title="Soul Messiah", file_name=incoming.file_name)
    )
    assert result.unique is None
    assert result.recommendations


def test_named_mix_does_not_match_studio_as_unique() -> None:
    artist, album = _alphaville()
    mix = _track(
        title="Soul Messiah (Spike Drake mix)",
        file_name="23 - Soul Messiah (Spike Drake mix).mp3",
        album_id=album.id,
        artist_id=artist.id,
        track_number=23,
        duration_ms=263000,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="Soul Messiah",
        file_name="10 - Soul Messiah.mp3",
        file_path=r"C:\in\x\10 - Soul Messiah.mp3",
        duration_ms=292000,
        track_number=10,
    )
    result = _matcher(incoming, [mix], [album], [artist]).match(
        incoming,
        MetadataQuery(
            title="Soul Messiah", track_number=10, duration_ms=292000, artist="Alphaville"
        ),
    )
    assert result.unique is None
    assert all(item.version_conflict or item.score < 0.9 for item in result.recommendations)


def test_duration_mismatch_blocks_unique_even_with_corroboration() -> None:
    artist, album = _alphaville()
    existing = _track(
        title="Soul Messiah",
        file_name="10 - Soul Messiah.flac",
        album_id=album.id,
        artist_id=artist.id,
        track_number=10,
        duration_ms=295000,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="Soul Messiah",
        file_name="10 - Soul Messiah.mp3",
        file_path=r"C:\in\x\10 - Soul Messiah.mp3",
        duration_ms=200000,
        track_number=10,
    )
    result = _matcher(incoming, [existing], [album], [artist]).match(
        incoming,
        MetadataQuery(
            title="Soul Messiah",
            artist="Alphaville",
            track_number=10,
            duration_ms=200000,
        ),
        provenance=AcquisitionProvenance(
            artist="Alphaville",
            album="Salvation",
            mb_release_id=_SALVATION_MBID,
        ),
    )
    assert result.unique is None


def test_unique_when_existing_is_better_identity_still_wins() -> None:
    """Better LIBRARY copy must not block identity — quality is post-identify."""
    artist, album = _alphaville()
    existing = _track(
        title="Pandora's Lullaby",
        file_name="12 - Pandora's Lullaby.flac",
        album_id=album.id,
        artist_id=artist.id,
        track_number=12,
        duration_ms=268000,
        is_lossless=True,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="Pandora's Lullaby",
        file_name="12 - Pandora's Lullaby.mp3",
        file_path=r"C:\in\x\12 - Pandora's Lullaby.mp3",
        duration_ms=268200,
        track_number=12,
        bitrate=320000,
    )
    result = _matcher(incoming, [existing], [album], [artist]).match(
        incoming,
        MetadataQuery(
            title="Pandora's Lullaby",
            artist="Alphaville",
            track_number=12,
            duration_ms=268200,
        ),
        provenance=AcquisitionProvenance(
            artist="Alphaville",
            album="Salvation",
            mb_release_id=_SALVATION_MBID,
        ),
    )
    assert result.unique is not None
    assert result.unique.album_id == album.id
    assert result.unique.existing_is_better is True
    assert result.provider_result is not None


def test_archived_copy_does_not_count_as_better_library() -> None:
    artist, album = _alphaville()
    archived = _track(
        zone=LibraryZone.ARCHIVE,
        title="Soul Messiah",
        file_name="10 - Soul Messiah.flac",
        album_id=album.id,
        artist_id=artist.id,
        track_number=10,
        duration_ms=292000,
        is_lossless=True,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="Soul Messiah",
        file_name="10 - Soul Messiah.mp3",
        file_path=r"C:\in\x\10 - Soul Messiah.mp3",
        duration_ms=292100,
        track_number=10,
        bitrate=320000,
    )
    result = _matcher(incoming, [archived], [album], [artist]).match(
        incoming,
        MetadataQuery(
            title="Soul Messiah", artist="Alphaville", track_number=10, duration_ms=292100
        ),
        provenance=AcquisitionProvenance(
            artist="Alphaville",
            album="Salvation",
            mb_release_id=_SALVATION_MBID,
        ),
    )
    assert result.unique is not None
    assert result.unique.existing_is_better is False


def test_unique_with_song_corroboration_when_not_worse() -> None:
    artist, album = _alphaville()
    existing = _track(
        title="Pandora's Lullaby",
        file_name="12 - Pandora's Lullaby.mp3",
        album_id=album.id,
        artist_id=artist.id,
        track_number=12,
        duration_ms=268000,
        bitrate=192000,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="Pandora's Lullaby",
        file_name="12 - Pandora's Lullaby.mp3",
        file_path=r"C:\in\x\12 - Pandora's Lullaby.mp3",
        duration_ms=268200,
        track_number=12,
        bitrate=320000,
    )
    result = _matcher(incoming, [existing], [album], [artist]).match(
        incoming,
        MetadataQuery(
            title="Pandora's Lullaby",
            artist="Alphaville",
            track_number=12,
            duration_ms=268200,
        ),
        provenance=AcquisitionProvenance(
            artist="Alphaville",
            album="Salvation",
            mb_release_id=_SALVATION_MBID,
        ),
    )
    assert result.unique is not None
    assert result.unique.album_id == album.id


def test_release_mbid_mismatch_never_unique() -> None:
    artist, album_a = _alphaville()
    album_a = Album(
        id=album_a.id,
        title="Salvation",
        sort_title="Salvation",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
        mbid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    existing = _track(
        title="Soul Messiah",
        file_name="10 - Soul Messiah.mp3",
        album_id=album_a.id,
        artist_id=artist.id,
        track_number=10,
        duration_ms=292000,
        bitrate=128000,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="Soul Messiah",
        file_name="10 - Soul Messiah.mp3",
        file_path=r"C:\in\x\10 - Soul Messiah.mp3",
        duration_ms=292100,
        track_number=10,
        bitrate=320000,
    )
    result = _matcher(incoming, [existing], [album_a], [artist]).match(
        incoming,
        MetadataQuery(
            title="Soul Messiah", artist="Alphaville", track_number=10, duration_ms=292100
        ),
        provenance=AcquisitionProvenance(
            artist="Alphaville",
            album="Salvation",
            mb_release_id=_SALVATION_MBID,
        ),
    )
    assert result.unique is None
    assert any(item.release_mismatch for item in result.recommendations)


def test_invalid_demo_candidate_does_not_shadow_eligible_studio() -> None:
    artist, album = _alphaville()
    demo_album = Album(
        id=generate_uuid7(),
        title="Salvation (Demo)",
        sort_title="Salvation (Demo)",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
        mbid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    demo = _track(
        title="Soul Messiah (demo)",
        file_name="10 - Soul Messiah (demo).flac",
        album_id=demo_album.id,
        artist_id=artist.id,
        track_number=10,
        duration_ms=292000,
        is_lossless=True,
    )
    studio = _track(
        title="Soul Messiah",
        file_name="10 - Soul Messiah.flac",
        album_id=album.id,
        artist_id=artist.id,
        track_number=10,
        duration_ms=292000,
        is_lossless=True,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="Soul Messiah",
        file_name="10 - Soul Messiah.mp3",
        file_path=r"C:\in\x\10 - Soul Messiah.mp3",
        duration_ms=292050,
        track_number=10,
        bitrate=320000,
    )
    result = _matcher(incoming, [demo, studio], [album, demo_album], [artist]).match(
        incoming,
        MetadataQuery(
            title="Soul Messiah", artist="Alphaville", track_number=10, duration_ms=292050
        ),
        provenance=AcquisitionProvenance(
            artist="Alphaville",
            album="Salvation",
            mb_release_id=_SALVATION_MBID,
        ),
    )
    assert result.unique is not None
    assert result.unique.album_id == album.id
    assert result.unique.exact_release is True
    # Demo may still appear in recommendations but must not be first among eligible.
    assert result.recommendations[0].album_id == album.id


def test_same_slot_physical_copies_collapse_to_one_identity() -> None:
    artist, album = _alphaville()
    flac = _track(
        title="Soul Messiah",
        file_name="10 - Soul Messiah.flac",
        album_id=album.id,
        artist_id=artist.id,
        track_number=10,
        duration_ms=292000,
        is_lossless=True,
    )
    mp3 = _track(
        title="Soul Messiah",
        file_name="10 - Soul Messiah.mp3",
        album_id=album.id,
        artist_id=artist.id,
        track_number=10,
        duration_ms=292000,
        bitrate=192000,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="Soul Messiah",
        file_name="10 - Soul Messiah.mp3",
        file_path=r"C:\in\x\10 - Soul Messiah.mp3",
        duration_ms=292100,
        track_number=10,
        bitrate=128000,
    )
    result = _matcher(incoming, [flac, mp3], [album], [artist]).match(
        incoming,
        MetadataQuery(
            title="Soul Messiah", artist="Alphaville", track_number=10, duration_ms=292100
        ),
        provenance=AcquisitionProvenance(
            artist="Alphaville",
            album="Salvation",
            mb_release_id=_SALVATION_MBID,
        ),
    )
    same_slot = [
        r for r in result.recommendations if r.album_id == album.id and r.track_number == 10
    ]
    assert len(same_slot) == 1
    assert result.unique is not None
    assert result.unique.existing_is_better is True


def test_studio_and_demo_on_same_album_do_not_frankenstein() -> None:
    """Demo duration mismatch must not poison the studio identity on the same album."""
    artist, album = _alphaville()
    studio = _track(
        title="Soul Messiah",
        file_name="10 - Soul Messiah.flac",
        album_id=album.id,
        artist_id=artist.id,
        track_number=10,
        duration_ms=292000,
        is_lossless=True,
    )
    demo = _track(
        title="Soul Messiah (demo)",
        file_name="10 - Soul Messiah (demo).flac",
        album_id=album.id,
        artist_id=artist.id,
        track_number=10,
        duration_ms=180000,
        is_lossless=True,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="Soul Messiah",
        file_name="10 - Soul Messiah.mp3",
        file_path=r"C:\in\x\10 - Soul Messiah.mp3",
        duration_ms=292050,
        track_number=10,
        bitrate=320000,
    )
    result = _matcher(incoming, [studio, demo], [album], [artist]).match(
        incoming,
        MetadataQuery(
            title="Soul Messiah", artist="Alphaville", track_number=10, duration_ms=292050
        ),
        provenance=AcquisitionProvenance(
            artist="Alphaville",
            album="Salvation",
            mb_release_id=_SALVATION_MBID,
        ),
    )
    assert result.unique is not None
    assert result.unique.slot_title == "Soul Messiah"
    assert result.unique.duration_ok is True
    assert result.unique.exact_release is True
    # Demo remains a separate recommendation, not collapsed into studio.
    demo_recs = [r for r in result.recommendations if "demo" in r.slot_title.casefold()]
    assert demo_recs
    assert all(r.version_conflict or not r.duration_ok for r in demo_recs)


def test_exact_mbid_beats_deluxe_without_mbid() -> None:
    artist, album = _alphaville()
    deluxe = Album(
        id=generate_uuid7(),
        title="Salvation (Deluxe Remastered Edition)",
        sort_title="Salvation (Deluxe Remastered Edition)",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
        mbid=None,
    )
    studio = _track(
        title="Control",
        file_name="07 - Control.flac",
        album_id=album.id,
        artist_id=artist.id,
        track_number=7,
        duration_ms=230000,
        is_lossless=True,
    )
    deluxe_track = _track(
        title="Control",
        file_name="07 - Control.flac",
        album_id=deluxe.id,
        artist_id=artist.id,
        track_number=7,
        duration_ms=230000,
        is_lossless=True,
    )
    incoming = _track(
        zone=LibraryZone.INCOMING,
        title="Control",
        file_name="07 - Control.mp3",
        file_path=r"C:\in\x\07 - Control.mp3",
        duration_ms=230100,
        track_number=7,
        bitrate=320000,
    )
    result = _matcher(incoming, [deluxe_track, studio], [album, deluxe], [artist]).match(
        incoming,
        MetadataQuery(
            title="Control",
            artist="Alphaville",
            track_number=7,
            duration_ms=230100,
        ),
        provenance=AcquisitionProvenance(
            artist="Alphaville",
            album="Salvation",
            mb_release_id=_SALVATION_MBID,
        ),
    )
    assert result.unique is not None
    assert result.unique.album_id == album.id
    assert result.unique.album_title == "Salvation"
    assert result.unique.exact_release is True

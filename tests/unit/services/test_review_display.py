"""Playable Review rows must name a song and point at a real audio file."""

from datetime import UTC, datetime
from uuid import UUID

from vaultseek.models.entities.review_item import ReviewItem, ReviewStatus, ReviewType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.review_display import (
    human_song_label,
    looks_like_opaque_id,
    select_playable_reviews,
)

_LIBRARY = UUID("00000000-0000-7000-8000-000000000099")


def test_filename_beats_uuid_fragment_and_keeps_a_real_tag() -> None:
    assert looks_like_opaque_id("01a090ad")
    assert (
        human_song_label(
            file_name="06 - Point Of Know Return.mp3",
            tag_title="01a090ad",
            stored_title="01a090ad",
        )
        == "Point Of Know Return"
    )
    assert (
        human_song_label(
            file_name="track.mp3",
            tag_title="Control",
            tag_artist="Kansas",
        )
        == "Kansas — Control"
    )


def test_unplayable_reviews_are_omitted() -> None:
    playable_track = UUID("00000000-0000-7000-8000-000000000001")
    missing_track = UUID("00000000-0000-7000-8000-000000000002")
    playable_item = UUID("00000000-0000-7000-8000-000000000011")
    tracks = {
        playable_track: _track(
            playable_track, r"C:\music\06 - Point Of Know Return.mp3", "01a090ad"
        ),
        missing_track: _track(missing_track, r"C:\missing\gone.mp3", "Gone"),
    }

    rows = select_playable_reviews(
        [
            _item(playable_item, ReviewType.UNKNOWN_ARTIST, "01a090ad", playable_track),
            _item(
                UUID("00000000-0000-7000-8000-000000000012"),
                ReviewType.ARTWORK_MISSING,
                "No artwork found",
                missing_track,
            ),
            _item(
                UUID("00000000-0000-7000-8000-000000000013"),
                ReviewType.ACQUISITION_NO_RESULTS,
                "Not on Soulseek: Alice",
                None,
            ),
        ],
        track_for=tracks.get,
        artist_name=lambda _artist_id: None,
        duplicate_track_ids=lambda _group_id: (),
        file_exists=lambda path: path.startswith(r"C:\music"),
        read_tags=lambda _path: (None, None),
    )
    assert [row.item_id for row in rows] == [playable_item]
    assert rows[0].label == "Point Of Know Return"
    assert rows[0].audio_path.startswith(r"C:\music")
    assert rows[0].reason == "needs a person"


def _item(item_id: UUID, review_type: ReviewType, title: str, track_id: UUID | None) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        library_id=_LIBRARY,
        review_type=review_type,
        status=ReviewStatus.PENDING,
        title=title,
        created_at=datetime.now(UTC),
        track_id=track_id,
        description="needs a person",
        confidence=0.3,
    )


def _track(track_id: UUID, path: str, title: str) -> Track:
    now = datetime.now(UTC)
    return Track(
        id=track_id,
        library_id=_LIBRARY,
        zone=LibraryZone.INCOMING,
        file_path=path,
        file_name=path.rsplit("\\", 1)[-1],
        file_size=1,
        file_modified=now,
        created_at=now,
        updated_at=now,
        title=title,
    )

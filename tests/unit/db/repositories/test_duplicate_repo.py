"""Unit tests for vaultseek.db.repositories.duplicate_repo."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, insert

from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.tables import file_identity, tracks
from vaultseek.db.uuid_utils import generate_uuid7, uuid_to_blob
from vaultseek.models.entities.duplicate_group import (
    DuplicateGroup,
    DuplicateMember,
    GroupResolution,
    GroupStatus,
    MatchType,
)

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


@pytest.fixture
def repo(engine: Engine) -> DuplicateRepository:
    return DuplicateRepository(engine)


def _insert_track(
    engine: Engine,
    library_id: UUID,
    *,
    is_lossless: bool = False,
    mb_recording_id: str | None = None,
) -> UUID:
    trk_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(tracks).values(
                id=uuid_to_blob(trk_id),
                library_id=uuid_to_blob(library_id),
                zone="incoming",
                file_path=f"C:/incoming/{trk_id}.mp3",
                file_name=f"{trk_id}.mp3",
                file_size=1024,
                file_modified="2026-07-17T00:00:00",
                is_lossless=is_lossless,
                mb_recording_id=mb_recording_id,
                created_at="2026-07-17T00:00:00",
                updated_at="2026-07-17T00:00:00",
            )
        )
    return trk_id


def _insert_identity(
    engine: Engine,
    track_id: UUID,
    *,
    content_hash: str = "hash-a",
    fingerprint_hash: str | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(file_identity).values(
                track_id=uuid_to_blob(track_id),
                content_hash_sha256=content_hash,
                fingerprint_hash=fingerprint_hash,
                file_size=1024,
                file_modified="2026-07-17T00:00:00",
            )
        )


def _group(
    library_id: UUID,
    track_ids: list[UUID],
    *,
    group_id: UUID | None = None,
    match_type: MatchType = MatchType.HASH,
    status: GroupStatus = GroupStatus.OPEN,
) -> tuple[DuplicateGroup, list[DuplicateMember]]:
    gid = group_id or generate_uuid7()
    group = DuplicateGroup(
        id=gid,
        library_id=library_id,
        match_type=match_type,
        match_confidence=1.0,
        best_track_id=track_ids[0],
        track_count=len(track_ids),
        detected_at=_NOW,
        status=status,
    )
    members = [
        DuplicateMember(
            group_id=gid,
            track_id=track_id,
            quality_score=95 if index == 0 else 50,
            is_best=index == 0,
            zone="incoming",
        )
        for index, track_id in enumerate(track_ids)
    ]
    return group, members


def test_save_group_round_trips_group_and_members(
    repo: DuplicateRepository, engine: Engine, library_id: UUID
) -> None:
    track_a = _insert_track(engine, library_id)
    track_b = _insert_track(engine, library_id)
    group, members = _group(library_id, [track_a, track_b])

    repo.save_group(group, members)

    loaded = repo.get_group(group.id)
    assert loaded == group
    loaded_members = repo.get_members(group.id)
    assert len(loaded_members) == 2
    assert loaded_members[0].is_best is True
    assert loaded_members[0].track_id == track_a


def test_save_group_replaces_existing_members(
    repo: DuplicateRepository, engine: Engine, library_id: UUID
) -> None:
    track_a = _insert_track(engine, library_id)
    track_b = _insert_track(engine, library_id)
    track_c = _insert_track(engine, library_id)
    group, members = _group(library_id, [track_a, track_b])
    repo.save_group(group, members)

    regrouped, new_members = _group(library_id, [track_a, track_b, track_c], group_id=group.id)
    repo.save_group(regrouped, new_members)

    assert {m.track_id for m in repo.get_members(group.id)} == {track_a, track_b, track_c}
    loaded = repo.get_group(group.id)
    assert loaded is not None
    assert loaded.track_count == 3


def test_list_open_by_library_excludes_resolved_groups(
    repo: DuplicateRepository, engine: Engine, library_id: UUID
) -> None:
    track_a = _insert_track(engine, library_id)
    track_b = _insert_track(engine, library_id)
    open_group, open_members = _group(library_id, [track_a, track_b])
    repo.save_group(open_group, open_members)
    resolved_group, resolved_members = _group(library_id, [track_a, track_b])
    repo.save_group(resolved_group, resolved_members)
    repo.set_status(resolved_group.id, GroupStatus.RESOLVED, resolution=GroupResolution.KEPT_BEST)

    open_ids = {g.id for g in repo.list_open_by_library(library_id)}

    assert open_ids == {open_group.id}
    reloaded = repo.get_group(resolved_group.id)
    assert reloaded is not None
    assert reloaded.status is GroupStatus.RESOLVED
    assert reloaded.resolution is GroupResolution.KEPT_BEST


def test_find_open_group_for_track_matches_on_type_and_status(
    repo: DuplicateRepository, engine: Engine, library_id: UUID
) -> None:
    track_a = _insert_track(engine, library_id)
    track_b = _insert_track(engine, library_id)
    group, members = _group(library_id, [track_a, track_b], match_type=MatchType.FINGERPRINT)
    repo.save_group(group, members)

    found = repo.find_open_group_for_track(track_a, MatchType.FINGERPRINT)
    assert found is not None
    assert found.id == group.id
    assert repo.find_open_group_for_track(track_a, MatchType.HASH) is None

    repo.set_status(group.id, GroupStatus.IGNORED)
    assert repo.find_open_group_for_track(track_a, MatchType.FINGERPRINT) is None


def test_has_lossless_duplicate_requires_a_lossless_other_member(
    repo: DuplicateRepository, engine: Engine, library_id: UUID
) -> None:
    mp3 = _insert_track(engine, library_id, is_lossless=False)
    flac = _insert_track(engine, library_id, is_lossless=True)
    other_mp3 = _insert_track(engine, library_id, is_lossless=False)

    lossless_group, lossless_members = _group(library_id, [flac, mp3])
    repo.save_group(lossless_group, lossless_members)
    lossy_group, lossy_members = _group(library_id, [mp3, other_mp3])
    repo.save_group(lossy_group, lossy_members)

    assert repo.has_lossless_duplicate(mp3) is True
    # The FLAC itself has no *lossless* duplicate (its peer is the MP3).
    assert repo.has_lossless_duplicate(flac) is False
    assert repo.has_lossless_duplicate(other_mp3) is False


def test_has_lossless_duplicate_ignores_closed_groups(
    repo: DuplicateRepository, engine: Engine, library_id: UUID
) -> None:
    mp3 = _insert_track(engine, library_id, is_lossless=False)
    flac = _insert_track(engine, library_id, is_lossless=True)
    group, members = _group(library_id, [flac, mp3])
    repo.save_group(group, members)
    repo.set_status(group.id, GroupStatus.RESOLVED, resolution=GroupResolution.ARCHIVED)

    assert repo.has_lossless_duplicate(mp3) is False


def test_find_matching_track_ids_matches_each_exact_key_tier(
    repo: DuplicateRepository, engine: Engine, library_id: UUID
) -> None:
    subject = _insert_track(engine, library_id, mb_recording_id="mbid-1")
    _insert_identity(engine, subject, content_hash="hash-1", fingerprint_hash="fp-1")
    same_hash = _insert_track(engine, library_id)
    _insert_identity(engine, same_hash, content_hash="hash-1", fingerprint_hash="fp-other")
    same_fp = _insert_track(engine, library_id)
    _insert_identity(engine, same_fp, content_hash="hash-other", fingerprint_hash="fp-1")
    same_mbid = _insert_track(engine, library_id, mb_recording_id="mbid-1")
    unrelated = _insert_track(engine, library_id, mb_recording_id="mbid-2")
    _insert_identity(engine, unrelated, content_hash="hash-x", fingerprint_hash="fp-x")

    matches = repo.find_matching_track_ids(
        library_id,
        subject,
        content_hash="hash-1",
        fingerprint_hash="fp-1",
        mb_recording_id="mbid-1",
    )

    assert matches == {
        MatchType.HASH: [same_hash],
        MatchType.FINGERPRINT: [same_fp],
        MatchType.MBID: [same_mbid],
    }


def test_find_matching_track_ids_returns_empty_when_no_keys_or_matches(
    repo: DuplicateRepository, engine: Engine, library_id: UUID
) -> None:
    subject = _insert_track(engine, library_id)
    _insert_identity(engine, subject, content_hash="only-copy")

    assert repo.find_matching_track_ids(library_id, subject) == {}
    assert repo.find_matching_track_ids(library_id, subject, content_hash="only-copy") == {}

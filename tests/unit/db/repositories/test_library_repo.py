"""Unit tests for vaultseek.db.repositories.library_repo."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine

from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


@pytest.fixture
def repo(engine: Engine) -> LibraryRepository:
    return LibraryRepository(engine)


def _library(**overrides: object) -> Library:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "name": "Main",
        "incoming_path": "C:/vault/Incoming",
        "staging_path": "C:/vault/Staging",
        "library_path": "C:/vault/Music",
        "archive_path": "C:/vault/Archive",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Library(**defaults)  # type: ignore[arg-type]


def test_upsert_and_get_round_trip(repo: LibraryRepository) -> None:
    library = _library(watch_enabled=True, auto_approve_threshold=0.85)

    repo.upsert(library)

    assert repo.get(library.id) == library


def test_get_returns_none_for_unknown_id(repo: LibraryRepository) -> None:
    assert repo.get(generate_uuid7()) is None


def test_upsert_overwrites_existing_row(repo: LibraryRepository) -> None:
    library = _library()
    repo.upsert(library)

    repo.upsert(replace(library, name="Renamed", watch_enabled=True))

    loaded = repo.get(library.id)
    assert loaded is not None
    assert loaded.name == "Renamed"
    assert loaded.watch_enabled is True


def test_list_watch_enabled_filters(repo: LibraryRepository) -> None:
    watched = _library(watch_enabled=True)
    unwatched = _library(watch_enabled=False)
    repo.upsert(watched)
    repo.upsert(unwatched)

    watch_ids = {library.id for library in repo.list_watch_enabled()}
    all_ids = {library.id for library in repo.list_all()}

    assert watch_ids == {watched.id}
    assert {watched.id, unwatched.id}.issubset(all_ids)


def test_zone_root_maps_every_zone(repo: LibraryRepository) -> None:
    library = _library()

    assert library.zone_root(LibraryZone.INCOMING) == "C:/vault/Incoming"
    assert library.zone_root(LibraryZone.STAGING) == "C:/vault/Staging"
    assert library.zone_root(LibraryZone.LIBRARY) == "C:/vault/Music"
    assert library.zone_root(LibraryZone.ARCHIVE) == "C:/vault/Archive"

"""Deletion safety using disposable media and the real SQLite schema."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from vaultseek.core.exceptions import OperationError
from vaultseek.db import tables
from vaultseek.db.uuid_utils import uuid_to_blob
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone, Track


@pytest.fixture
def album_files(container, tmp_path):
    now = datetime.now(UTC)
    library = Library(
        uuid4(),
        "Test",
        str(tmp_path / "incoming"),
        str(tmp_path / "staging"),
        str(tmp_path / "music"),
        str(tmp_path / "archive"),
        now,
        now,
    )
    container.library_repo.upsert(library)
    album = Album(uuid4(), "Album", "Album", now, now)
    container.album_repo.create(album)
    tracks = []
    for n, zone in enumerate((LibraryZone.LIBRARY, LibraryZone.ARCHIVE)):
        path = Path(library.zone_root(zone)) / "Album" / f"{n}.flac"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"disposable test media")
        track = Track(
            uuid4(),
            library.id,
            zone,
            str(path),
            path.name,
            path.stat().st_size,
            now,
            now,
            now,
            album_id=album.id,
        )
        container.track_repo.upsert(track)
        tracks.append(track)
    return library, album, tracks


def test_deletes_album_and_archived_files_preserves_unrelated(container, album_files, monkeypatch):
    library, album, tracks = album_files
    unrelated = Path(tracks[0].file_path).parent / "notes.txt"
    unrelated.write_text("keep")
    monkeypatch.setattr(
        "vaultseek.services.album_deletion.send2trash", lambda path: Path(path).unlink()
    )
    assert container.album_deletion.delete(library.id, album.id) == 2
    assert not container.album_repo.list_for_library(library.id)
    assert container.album_repo.get(album.id) is None
    assert all(container.track_repo.get_by_id(t.id) is None for t in tracks)
    assert all(not Path(t.file_path).exists() for t in tracks)
    assert unrelated.read_text() == "keep"
    assert not Path(tracks[1].file_path).parent.exists()


def test_failure_keeps_metadata_and_allows_retry(container, album_files, monkeypatch):
    library, album, tracks = album_files

    def fail(path):
        raise PermissionError("locked")

    monkeypatch.setattr("vaultseek.services.album_deletion.send2trash", fail)
    with pytest.raises(OperationError, match="records were kept"):
        container.album_deletion.delete(library.id, album.id)
    assert container.album_repo.get(album.id)
    assert all(Path(t.file_path).exists() for t in tracks)


def test_outside_library_preflight_removes_nothing(container, album_files, tmp_path, monkeypatch):
    library, album, tracks = album_files
    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"keep")
    container.track_repo.upsert(replace(tracks[1], file_path=str(outside)))
    calls = []
    monkeypatch.setattr("vaultseek.services.album_deletion.send2trash", calls.append)
    with pytest.raises(OperationError, match="outside"):
        container.album_deletion.delete(library.id, album.id)
    assert calls == []
    assert outside.exists()


def test_busy_library_removes_nothing(container, album_files, monkeypatch):
    library, album, tracks = album_files
    container.job_queue.enqueue(JobType.ORGANIZE_FILE, library.id, {"track_id": str(tracks[0].id)})
    calls = []
    monkeypatch.setattr("vaultseek.services.album_deletion.send2trash", calls.append)
    with pytest.raises(OperationError, match="processing"):
        container.album_deletion.delete(library.id, album.id)
    assert calls == []


def test_shared_album_remains_in_other_library(container, album_files, tmp_path, monkeypatch):
    library, album, tracks = album_files
    other = replace(library, id=uuid4(), name="Other")
    container.library_repo.upsert(other)
    other_track = replace(
        tracks[0], id=uuid4(), library_id=other.id, file_path=str(tmp_path / "other.flac")
    )
    container.track_repo.upsert(other_track)
    monkeypatch.setattr(
        "vaultseek.services.album_deletion.send2trash", lambda path: Path(path).unlink()
    )
    container.album_deletion.delete(library.id, album.id)
    assert container.album_repo.get(album.id)
    assert container.track_repo.get_by_id(other_track.id)
    assert not container.album_repo.list_for_library(library.id)


def test_related_identity_rows_are_removed(container, album_files, monkeypatch):
    library, album, tracks = album_files
    with container.engine.begin() as conn:
        for track in tracks:
            conn.execute(
                tables.file_identity.insert().values(
                    track_id=uuid_to_blob(track.id),
                    content_hash_sha256="test-hash",
                    file_size=track.file_size,
                    file_modified=track.file_modified.isoformat(),
                )
            )
    monkeypatch.setattr(
        "vaultseek.services.album_deletion.send2trash", lambda path: Path(path).unlink()
    )
    container.album_deletion.delete(library.id, album.id)
    with container.engine.connect() as conn:
        assert conn.execute(select(tables.file_identity)).all() == []


def test_partial_failure_retains_records_for_retry(container, album_files, monkeypatch):
    library, album, tracks = album_files
    calls = []

    def partial(path):
        calls.append(path)
        if len(calls) == 2:
            raise PermissionError("locked second file")
        Path(path).unlink()

    monkeypatch.setattr("vaultseek.services.album_deletion.send2trash", partial)
    with pytest.raises(OperationError):
        container.album_deletion.delete(library.id, album.id)
    assert container.album_repo.get(album.id)
    assert all(container.track_repo.get_by_id(t.id) for t in tracks)
    monkeypatch.setattr(
        "vaultseek.services.album_deletion.send2trash", lambda path: Path(path).unlink()
    )
    assert container.album_deletion.delete(library.id, album.id) == 2
    assert container.album_repo.get(album.id) is None


def test_real_recycle_bin_with_disposable_files(container, album_files):
    library, album, tracks = album_files
    assert container.album_deletion.delete(library.id, album.id) == 2
    assert all(not Path(t.file_path).exists() for t in tracks)
    assert container.album_repo.list_for_library(library.id) == []


def test_shell_noop_keeps_album_records(container, album_files, monkeypatch):
    library, album, tracks = album_files
    monkeypatch.setattr("vaultseek.services.album_deletion.send2trash", lambda path: None)
    with pytest.raises(OperationError, match="did not remove"):
        container.album_deletion.delete(library.id, album.id)
    assert container.album_repo.get(album.id)
    assert all(Path(t.file_path).exists() for t in tracks)

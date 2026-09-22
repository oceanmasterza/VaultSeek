"""Provenance lookup must use known download paths, not JSON substring scans."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)
from vaultseek.services.acquisition_provenance import provenance_for_track_path

_NOW = datetime(2026, 9, 22, tzinfo=UTC)
_LIB = UUID("00000000-0000-7000-8000-000000000011")
_FOLDER = "01a090ad-7dbc-7000-b76e-66601cf1998b"


class _Jobs:
    def __init__(self, jobs: list[AcquisitionJob]) -> None:
        self._jobs = jobs

    def list_by_library(
        self,
        library_id: UUID | None = None,
        *,
        state: AcquisitionJobState | None = None,
        limit: int | None = None,
    ) -> list[AcquisitionJob]:
        rows = [
            job
            for job in self._jobs
            if (library_id is None or job.library_id == library_id)
            and (state is None or job.state is state)
        ]
        if limit is not None:
            return rows[:limit]
        return rows


def _job(**overrides: object) -> AcquisitionJob:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": _LIB,
        "job_type": AcquisitionJobType.MISSING_ALBUM,
        "state": AcquisitionJobState.COMPLETED,
        "created_at": _NOW,
        "updated_at": _NOW,
        "artist": "Alphaville",
        "album": "Salvation",
        "title": "Wanted Title Must Never Be Used",
        "mb_release_id": "2167db99-6fe0-4af8-8ae1-4fbe699008bf",
        "extra": {},
    }
    defaults.update(overrides)
    return AcquisitionJob(**defaults)  # type: ignore[arg-type]


def test_matches_nicotine_download_folder_path(tmp_path: Path) -> None:
    folder = tmp_path / _FOLDER
    folder.mkdir()
    audio = folder / "10 - Soul Messiah.mp3"
    audio.write_bytes(b"x")
    jobs = _Jobs(
        [
            _job(
                extra={"nicotine_download_folder": str(folder)},
            )
        ]
    )
    hit = provenance_for_track_path(jobs, _LIB, str(audio))  # type: ignore[arg-type]
    assert hit is not None
    assert hit.artist == "Alphaville"
    assert hit.album == "Salvation"
    assert hit.mb_release_id == "2167db99-6fe0-4af8-8ae1-4fbe699008bf"


def test_matches_local_paths_parent_folder(tmp_path: Path) -> None:
    folder = tmp_path / _FOLDER
    folder.mkdir()
    audio = folder / "12 - Pandora's Lullaby.mp3"
    audio.write_bytes(b"x")
    jobs = _Jobs(
        [
            _job(
                extra={"local_paths": [str(audio)]},
            )
        ]
    )
    hit = provenance_for_track_path(jobs, _LIB, str(audio))  # type: ignore[arg-type]
    assert hit is not None
    assert hit.album == "Salvation"


def test_ignores_non_completed_and_other_library(tmp_path: Path) -> None:
    folder = tmp_path / _FOLDER
    folder.mkdir()
    audio = folder / "10 - Soul Messiah.mp3"
    audio.write_bytes(b"x")
    other_lib = UUID("00000000-0000-7000-8000-000000000099")
    jobs = _Jobs(
        [
            _job(
                state=AcquisitionJobState.DOWNLOADING,
                extra={"nicotine_download_folder": str(folder)},
            ),
            _job(
                library_id=other_lib,
                extra={"nicotine_download_folder": str(folder)},
            ),
        ]
    )
    assert provenance_for_track_path(jobs, _LIB, str(audio)) is None  # type: ignore[arg-type]


def test_does_not_match_uuid_buried_in_unrelated_extra_json(tmp_path: Path) -> None:
    folder = tmp_path / _FOLDER
    folder.mkdir()
    audio = folder / "10 - Soul Messiah.mp3"
    audio.write_bytes(b"x")
    jobs = _Jobs(
        [
            _job(
                artist="Wrong Artist",
                album="Wrong Album",
                extra={"notes": f"mentioned {_FOLDER} in free text only"},
            )
        ]
    )
    assert provenance_for_track_path(jobs, _LIB, str(audio)) is None  # type: ignore[arg-type]

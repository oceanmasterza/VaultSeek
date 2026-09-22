"""Resolve acquisition folder provenance without inheriting job titles."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJob, AcquisitionJobState
from vaultseek.services.library_tracklist_matcher import AcquisitionProvenance
from vaultseek.services.review_display import looks_like_opaque_id


def provenance_for_track_path(
    jobs: AcquisitionJobRepository,
    library_id: UUID,
    file_path: str,
    *,
    limit: int | None = None,
) -> AcquisitionProvenance | None:
    """Find artist/album/MBID for a Nicotine UUID download folder.

    Same-library **completed** jobs only. Matches the known download folder
    path (``nicotine_download_folder`` / ``local_paths``), never a loose
    substring scan of arbitrary JSON. Never returns the job's desired title.
    """
    parent = Path(file_path).parent
    folder_name = parent.name
    if not folder_name or not looks_like_opaque_id(folder_name):
        return None
    folder_key = _normalize_path(str(parent))
    folder_name_key = folder_name.casefold()

    completed = jobs.list_by_library(
        library_id,
        state=AcquisitionJobState.COMPLETED,
        limit=limit,
    )
    for job in completed:
        if _job_matches_download_folder(job, folder_key, folder_name_key):
            return AcquisitionProvenance(
                artist=job.artist,
                album=job.album,
                mb_release_id=job.mb_release_id,
            )
    return None


def _job_matches_download_folder(
    job: AcquisitionJob,
    folder_key: str,
    folder_name_key: str,
) -> bool:
    extra = job.extra or {}
    explicit = str(extra.get("nicotine_download_folder") or "").strip()
    if explicit and _path_is_same_folder(explicit, folder_key, folder_name_key):
        return True
    for raw in _iter_path_values(extra.get("local_paths")):
        path = Path(str(raw))
        for candidate in (path.parent, path):
            if _path_is_same_folder(str(candidate), folder_key, folder_name_key):
                return True
    return False


def _path_is_same_folder(candidate: str, folder_key: str, folder_name_key: str) -> bool:
    normalized = _normalize_path(candidate)
    if not normalized:
        return False
    if normalized == folder_key:
        return True
    if normalized.endswith("/" + folder_name_key):
        return True
    return normalized == folder_name_key


def _normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/").rstrip("/").casefold()


def _iter_path_values(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw if item]
    return []

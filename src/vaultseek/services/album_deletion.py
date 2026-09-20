"""Confirmed album removal from media folders and the active library."""

from contextlib import suppress
from pathlib import Path
from uuid import UUID

from send2trash import send2trash
from sqlalchemy.exc import SQLAlchemyError

from vaultseek.core.exceptions import OperationError
from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.models.entities.track import LibraryZone


class AlbumDeletionService:
    def __init__(self, albums: AlbumRepository, libraries: LibraryRepository) -> None:
        self._albums = albums
        self._libraries = libraries

    def delete(self, library_id: UUID, album_id: UUID) -> int:
        library = self._libraries.get(library_id)
        if library is None:
            raise OperationError("The selected library no longer exists.")
        roots = [
            Path(library.zone_root(zone)).resolve()
            for zone in LibraryZone
            if library.zone_root(zone)
        ]
        paths: list[Path] = []
        try:
            with self._albums.removal(library_id, album_id) as filenames:
                for filename in filenames:
                    path = Path(filename)
                    resolved = path.resolve()
                    if path.is_symlink() or not any(
                        resolved != root and resolved.is_relative_to(root) for root in roots
                    ):
                        raise OperationError(
                            f"File is outside the configured library folders: {path}"
                        )
                    if path.exists() and not path.is_file():
                        raise OperationError(f"Expected a music file, not a directory: {path}")
                    if not path.parent.is_dir():
                        raise OperationError(f"Media folder is unavailable: {path.parent}")
                    paths.append(path)
                for path in dict.fromkeys(paths):
                    if path.exists():
                        send2trash(str(path))
                        if path.exists():
                            raise OSError(f"Windows did not remove the file: {path}")
        except (OSError, SQLAlchemyError) as exc:
            raise OperationError(
                "Deletion could not finish. Album records were kept; files already removed "
                f"may be in the Recycle Bin. Check access and retry. Details: {exc}"
            ) from exc
        for parent in {path.parent for path in paths}:
            if parent.resolve() not in roots:
                with suppress(OSError):
                    parent.rmdir()  # Only empty leaf folders; never recurse through media.
        return len(paths)

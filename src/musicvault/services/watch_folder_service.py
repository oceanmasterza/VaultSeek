"""WatchFolderService — periodic incoming-folder scans for watch-enabled libraries.

The architecture docs assume native filesystem events
(ReadDirectoryChangesW); this MVP deliberately *polls* instead: a
daemon thread (same start/stop + ``threading.Event`` pattern as
:class:`~musicvault.services.job_dispatcher.JobDispatcher`) enqueues a
`scan_directory` job for each ``watch_enabled`` library's incoming
folder. Polling exploits two existing properties — the scanner skips
unchanged files via size/mtime, and enqueues are skipped while a scan
for that library is already pending/running — so repeated polls are
cheap, and the poll interval doubles as the debounce the risk register
asks for (files still being written change size between polls and get
picked up on a later scan). Swapping in native events later only
changes this service's internals.

Watch scans use priority 50 (lower value = claimed first) so a newly
downloaded file is processed ahead of bulk backlog jobs, per
docs/architecture/04-service-layer.md.
"""

from __future__ import annotations

import threading
from datetime import datetime

from loguru import logger

from musicvault.db.repositories.library_repo import LibraryRepository
from musicvault.models.entities.job import JobType
from musicvault.models.entities.track import LibraryZone
from musicvault.services.job_queue_service import JobQueueService

_WATCH_SCAN_PRIORITY = 50


class WatchFolderService:
    def __init__(
        self,
        library_repository: LibraryRepository,
        job_queue: JobQueueService,
        *,
        poll_interval_seconds: float = 30.0,
    ) -> None:
        self._libraries = library_repository
        self._job_queue = job_queue
        self._poll_interval = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the polling thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, name="watch-folder", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the polling thread to exit and wait for it."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def poll_once(self, *, now: datetime | None = None) -> int:
        """Enqueue incoming scans for watch-enabled libraries.

        Skips a library while it already has a `scan_directory` job
        pending or running. Returns the number of scans enqueued.
        """
        enqueued = 0
        for library in self._libraries.list_watch_enabled():
            stats = self._job_queue.get_stats(library.id, now=now)
            if stats.by_type.get(JobType.SCAN_DIRECTORY.value, 0) > 0:
                continue
            self._job_queue.enqueue(
                JobType.SCAN_DIRECTORY,
                library.id,
                {
                    "directory": library.incoming_path,
                    "zone": LibraryZone.INCOMING.value,
                },
                priority=_WATCH_SCAN_PRIORITY,
                now=now,
            )
            enqueued += 1
        return enqueued

    def _poll_loop(self) -> None:
        while not self._stop_event.wait(self._poll_interval):
            try:
                self.poll_once()
            except Exception:
                logger.exception("Watch-folder poll cycle failed; continuing")

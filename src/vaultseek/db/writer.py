"""DatabaseWriter — the single thread allowed to write to SQLite.

Implements the "Tier 3: Database Writer Thread" design from
docs/architecture/12-pipeline-engine-v3.md. Every worker (Phase 4+)
computes results and hands them to this writer via :meth:`submit`
instead of calling a repository directly — with 8+ concurrent workers,
having each one write independently causes constant SQLite
`database is locked` contention (see that doc's "Risk: SQLite Write
Contention"); one thread doing large batched transactions does not.

``JobDispatcher``'s own job-claiming query (`pending` → `running`) is
the one exception: it is not part of this write path. Only one thread
(the dispatcher's poll loop) ever calls it, so it is not the
many-writers contention problem this class solves — see
:mod:`vaultseek.services.job_queue_service` for that boundary.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from loguru import logger
from sqlalchemy import Connection, Engine

from vaultseek.db.repositories.base import batch_upsert
from vaultseek.db.tables import metadata

WriteOperation = Literal["upsert", "insert", "update", "delete"]

_SUPPORTED_OPERATIONS: frozenset[WriteOperation] = frozenset({"upsert"})
"""Only `upsert` has a real consumer so far (Phase 4's Scanner/Hash
workers). `insert`/`update`/`delete` are kept in :data:`WriteOperation`
because the architecture doc documents all four, but are intentionally
unimplemented until a later phase actually needs one — see
:meth:`DatabaseWriter._apply`."""


@dataclass(frozen=True, slots=True)
class WriteDTO:
    """A batch of rows for one table, handed off by a worker for the
    writer thread to persist."""

    table: str
    operation: WriteOperation
    rows: list[dict[str, Any]]
    job_id: UUID | None = None
    conflict_columns: tuple[str, ...] = ("id",)


class DatabaseWriter:
    """Batches `WriteDTO`s from a thread-safe queue and applies them in
    large transactions on a single dedicated background thread."""

    def __init__(
        self,
        engine: Engine,
        *,
        batch_size: int = 5_000,
        flush_interval_ms: int = 500,
    ) -> None:
        self._engine = engine
        self._batch_size = batch_size
        self._flush_interval_seconds = flush_interval_ms / 1000
        self._inbound: queue.Queue[WriteDTO] = queue.Queue()
        self._buffer: list[WriteDTO] = []
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background writer thread. Safe to call once per instance."""
        self._thread = threading.Thread(target=self._run, name="vaultseek-db-writer", daemon=True)
        self._thread.start()

    def submit(self, dto: WriteDTO) -> None:
        """Queue a write for the background thread to apply. Never blocks
        the caller on the database."""
        self._inbound.put(dto)

    def stop(self, *, timeout: float | None = 5.0) -> None:
        """Signal the writer to drain its queue, flush, and exit, then
        wait for it to finish (so a caller can be sure every write
        submitted before this call has landed)."""
        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._shutdown.is_set():
            try:
                dto = self._inbound.get(timeout=self._flush_interval_seconds)
            except queue.Empty:
                self._flush_if_pending()
                continue
            self._buffer.append(dto)
            if self._buffered_row_count() >= self._batch_size:
                self._flush_if_pending()
        self._drain_remaining()

    def _drain_remaining(self) -> None:
        """Apply everything still sitting in the inbound queue plus
        whatever is already buffered — called once on shutdown so a
        `stop()` caller never loses a write that was already `submit()`-ted."""
        while True:
            try:
                self._buffer.append(self._inbound.get_nowait())
            except queue.Empty:
                break
        self._flush_if_pending()

    def _buffered_row_count(self) -> int:
        return sum(len(dto.rows) for dto in self._buffer)

    def _flush_if_pending(self) -> None:
        if not self._buffer:
            return
        try:
            with self._engine.begin() as conn:
                for dto in self._buffer:
                    self._apply(conn, dto)
        except Exception:
            # A malformed DTO or a transient SQLite error must not kill this
            # thread — it runs unattended for the app's whole lifetime, and
            # every worker's writes depend on it staying alive. The batch is
            # dropped (the transaction already rolled back); the caller that
            # built the bad DTO is a bug to fix, not something this thread
            # can retry its way out of.
            logger.exception(
                "DatabaseWriter failed to flush a batch of {} DTO(s); dropping this batch.",
                len(self._buffer),
            )
        self._buffer.clear()

    def _apply(self, conn: Connection, dto: WriteDTO) -> None:
        if dto.operation not in _SUPPORTED_OPERATIONS:
            raise ValueError(
                f"DatabaseWriter does not yet support operation {dto.operation!r} "
                f"(only {sorted(_SUPPORTED_OPERATIONS)} are implemented)"
            )
        table = metadata.tables[dto.table]
        batch_upsert(conn, table, dto.rows, conflict_columns=_as_list(dto.conflict_columns))


def _as_list(columns: Sequence[str]) -> list[str]:
    return list(columns)

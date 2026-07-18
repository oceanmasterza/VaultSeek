"""Job monitor page — queue backlog and recent failures."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from musicvault.core.container import Container
from musicvault.models.entities.job import JobStatus


class JobsPage(QWidget):
    """Render-farm style view of the persistent job queue."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._job_ids: list[UUID] = []

        layout = QVBoxLayout(self)
        heading = QLabel("Jobs")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        self._stats = QLabel("")
        layout.addWidget(self._stats)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Type", "Status", "Attempts", "Error", "Created"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        retry_btn = QPushButton("Retry failed")
        cancel_btn.setProperty("secondary", True)
        cancel_btn.clicked.connect(self._cancel_selected)
        retry_btn.clicked.connect(self._retry_selected)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(retry_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._table.setRowCount(0)
        self._job_ids = []
        if self._library_id is None:
            self._stats.setText("No library selected.")
            return

        stats = self._container.job_queue.get_stats(self._library_id)
        by_type = ", ".join(f"{k}={v}" for k, v in sorted(stats.by_type.items())) or "none"
        self._stats.setText(
            f"Pending {stats.pending} · Running {stats.running} · "
            f"Failed {stats.failed} · Completed today {stats.completed_today} · "
            f"Backlog by type: {by_type}"
        )

        rows: list[tuple[UUID, str, str, str, str, str]] = []
        for job_status in (
            JobStatus.RUNNING,
            JobStatus.PENDING,
            JobStatus.RETRY,
            JobStatus.FAILED,
        ):
            for job in self._container.job_repo.list_by_status(
                job_status, library_id=self._library_id
            ):
                rows.append(
                    (
                        job.id,
                        job.job_type.value,
                        job.status.value,
                        str(job.attempt_count),
                        job.error_message or "",
                        job.created_at.isoformat(timespec="seconds"),
                    )
                )

        self._table.setRowCount(len(rows))
        for row_index, (job_id, job_type, status, attempts, error, created) in enumerate(rows):
            self._job_ids.append(job_id)
            self._table.setItem(row_index, 0, QTableWidgetItem(job_type))
            self._table.setItem(row_index, 1, QTableWidgetItem(status))
            self._table.setItem(row_index, 2, QTableWidgetItem(attempts))
            self._table.setItem(row_index, 3, QTableWidgetItem(error))
            self._table.setItem(row_index, 4, QTableWidgetItem(created))

    def _selected_ids(self) -> list[UUID]:
        rows = {index.row() for index in self._table.selectedIndexes()}
        return [self._job_ids[row] for row in sorted(rows) if 0 <= row < len(self._job_ids)]

    def _cancel_selected(self) -> None:
        for job_id in self._selected_ids():
            self._container.job_queue.cancel(job_id)
        self.refresh()

    def _retry_selected(self) -> None:
        for job_id in self._selected_ids():
            self._container.job_queue.retry_failed(job_id)
        self.refresh()

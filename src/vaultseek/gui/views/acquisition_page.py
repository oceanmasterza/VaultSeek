"""Acquisition page — wishlist, job progress, and manual controls."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.models.entities.acquisition_job import AcquisitionJobState


class AcquisitionPage(QWidget):
    """Wishlist of AcquisitionJobs with search / auto-acquire actions."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._job_ids: list[UUID] = []

        layout = QVBoxLayout(self)
        heading = QLabel("Acquisition")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Artist", "Album", "Title", "State", "Score", "Updated"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        row1 = QHBoxLayout()
        scan_btn = QPushButton("Scan for missing")
        run_btn = QPushButton("Auto-acquire selected")
        acquire_btn = QPushButton("Acquire top result")
        cancel_btn = QPushButton("Cancel selected")
        refresh_btn = QPushButton("Refresh")
        for btn in (cancel_btn, refresh_btn):
            btn.setProperty("secondary", True)
        scan_btn.setToolTip("Create AcquisitionJobs from MusicBrainz release gaps.")
        run_btn.setToolTip(
            "Search providers, score hits, and download when score meets the "
            "auto-acquire threshold in Settings."
        )
        acquire_btn.setToolTip("Download the highest-scored result for the selected job.")
        scan_btn.clicked.connect(self._scan_missing)
        run_btn.clicked.connect(self._auto_acquire_selected)
        acquire_btn.clicked.connect(self._acquire_top_selected)
        cancel_btn.clicked.connect(self._cancel_selected)
        refresh_btn.clicked.connect(self.refresh)
        row1.addWidget(scan_btn)
        row1.addWidget(run_btn)
        row1.addWidget(acquire_btn)
        row1.addWidget(cancel_btn)
        row1.addWidget(refresh_btn)
        row1.addStretch(1)
        layout.addLayout(row1)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._table.setRowCount(0)
        self._job_ids = []
        threshold = self._container.config.acquisition.auto_acquire_threshold
        if self._library_id is None:
            self._summary.setText("No library selected.")
            return

        jobs = self._container.acquisition_engine.list_jobs(library_id=self._library_id)
        active = sum(1 for job in jobs if not job.is_terminal)
        waiting = sum(1 for job in jobs if job.state is AcquisitionJobState.WAITING_FOR_USER)
        self._summary.setText(
            f"{len(jobs)} job(s) · {active} active · {waiting} awaiting choice · "
            f"auto-acquire ≥ {threshold:.0%}"
        )

        rows: list[tuple[UUID, str, str, str, str, str, str]] = []
        for job in jobs:
            score = job.extra.get("selected_score")
            if score is None and job.extra.get("scored_results"):
                first = job.extra["scored_results"][0]
                if isinstance(first, dict):
                    score = first.get("score")
            score_text = f"{float(score):.0%}" if score is not None else ""
            rows.append(
                (
                    job.id,
                    job.artist or "",
                    job.album or "",
                    job.title or "",
                    job.state.value,
                    score_text,
                    job.updated_at.isoformat(timespec="seconds"),
                )
            )

        self._table.setRowCount(len(rows))
        for row_index, (job_id, artist, album, title, state, score, updated) in enumerate(rows):
            self._job_ids.append(job_id)
            self._table.setItem(row_index, 0, QTableWidgetItem(artist))
            self._table.setItem(row_index, 1, QTableWidgetItem(album))
            self._table.setItem(row_index, 2, QTableWidgetItem(title))
            self._table.setItem(row_index, 3, QTableWidgetItem(state))
            self._table.setItem(row_index, 4, QTableWidgetItem(score))
            self._table.setItem(row_index, 5, QTableWidgetItem(updated))

    def poll_downloads(self) -> None:
        """Called from the main window timer while this page may be visible."""
        if self._library_id is None:
            return
        if self._container.acquisition_runner.poll_active_jobs(self._library_id) > 0:
            self.refresh()

    def _selected_ids(self) -> list[UUID]:
        rows = {index.row() for index in self._table.selectedIndexes()}
        return [self._job_ids[row] for row in sorted(rows) if 0 <= row < len(self._job_ids)]

    def _scan_missing(self) -> None:
        if self._library_id is None:
            QMessageBox.warning(self, "Acquisition", "Select a library first.")
            return
        analyzer = self._container.missing_media_analyzer
        if analyzer is None:
            QMessageBox.warning(
                self,
                "Acquisition",
                "Missing Media Analyzer is unavailable (MusicBrainz provider required).",
            )
            return
        created = analyzer.create_jobs_for_library(
            self._container.acquisition_engine,
            self._library_id,
            auto_queue=self._container.config.acquisition.auto_queue_jobs,
        )
        QMessageBox.information(
            self,
            "Acquisition",
            f"Created {len(created)} missing-track job(s).",
        )
        self.refresh()

    def _auto_acquire_selected(self) -> None:
        selected = self._selected_ids()
        if not selected:
            QMessageBox.information(self, "Acquisition", "Select one or more jobs first.")
            return
        outcomes: list[str] = []
        for job_id in selected:
            try:
                outcome = self._container.acquisition_runner.try_auto_acquire(job_id)
                outcomes.append(f"{job_id}: {outcome.state.value}")
            except (KeyError, ValueError) as exc:
                outcomes.append(f"{job_id}: error — {exc}")
        QMessageBox.information(self, "Acquisition", "\n".join(outcomes[:12]))
        self.refresh()

    def _acquire_top_selected(self) -> None:
        selected = self._selected_ids()
        if len(selected) != 1:
            QMessageBox.information(self, "Acquisition", "Select exactly one job.")
            return
        job_id = selected[0]
        job = self._container.acquisition_engine.get(job_id)
        if job is None:
            return
        scored = job.extra.get("scored_results") or []
        if not scored:
            outcome = self._container.acquisition_runner.search_and_score(job_id)
            if outcome.scored_count == 0:
                QMessageBox.warning(self, "Acquisition", "No search results to acquire.")
                self.refresh()
                return
            job = self._container.acquisition_engine.get(job_id)
            assert job is not None
            scored = job.extra.get("scored_results") or []
        top = scored[0]
        if not isinstance(top, dict) or not top.get("result_id"):
            QMessageBox.warning(self, "Acquisition", "No scored result available.")
            return
        try:
            outcome = self._container.acquisition_runner.start_download_by_result_id(
                job_id, str(top["result_id"])
            )
            QMessageBox.information(self, "Acquisition", outcome.message or outcome.state.value)
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, "Acquisition", str(exc))
        self.refresh()

    def _cancel_selected(self) -> None:
        for job_id in self._selected_ids():
            job = self._container.acquisition_engine.get(job_id)
            if job is None:
                continue
            if job.state is AcquisitionJobState.DOWNLOADING:
                self._container.download_manager.cancel(job_id)
            else:
                self._container.acquisition_engine.cancel(job_id)
        self.refresh()

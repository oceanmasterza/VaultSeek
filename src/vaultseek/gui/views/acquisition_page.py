"""Acquisition page — wishlist, job progress, and manual controls."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
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

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["Artist", "Album", "Title", "State", "Score", "Retries", "Updated", "Last note"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        row1 = QHBoxLayout()
        scan_btn = QPushButton("Scan for missing")
        run_btn = QPushButton("Auto-acquire selected")
        acquire_btn = QPushButton("Acquire top result")
        pick_btn = QPushButton("Pick result…")
        cancel_btn = QPushButton("Cancel selected")
        refresh_btn = QPushButton("Refresh")
        for btn in (cancel_btn, refresh_btn, pick_btn):
            btn.setProperty("secondary", True)
        scan_btn.setToolTip("Create AcquisitionJobs from MusicBrainz release gaps.")
        run_btn.setToolTip(
            "Search providers, score hits, and download when score meets the "
            "auto-acquire threshold in Settings."
        )
        acquire_btn.setToolTip("Download the highest-scored result for the selected job.")
        pick_btn.setToolTip(
            "For jobs waiting on user confirmation: open a picker and download a result."
        )
        scan_btn.clicked.connect(self._scan_missing)
        run_btn.clicked.connect(self._auto_acquire_selected)
        acquire_btn.clicked.connect(self._acquire_top_selected)
        pick_btn.clicked.connect(self._pick_result_for_selected_job)
        cancel_btn.clicked.connect(self._cancel_selected)
        refresh_btn.clicked.connect(self.refresh)
        row1.addWidget(scan_btn)
        row1.addWidget(run_btn)
        row1.addWidget(acquire_btn)
        row1.addWidget(pick_btn)
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

        rows: list[tuple[UUID, str, str, str, str, str, str, str, str]] = []
        for job in jobs:
            score = job.extra.get("selected_score")
            if score is None and job.extra.get("scored_results"):
                first = job.extra["scored_results"][0]
                if isinstance(first, dict):
                    score = first.get("score")
            score_text = f"{float(score):.0%}" if score is not None else ""
            retries = str(job.retry_count)
            last_note = ""
            if job.error_message:
                last_note = job.error_message
            elif job.history:
                last_note = job.history[-1]
            rows.append(
                (
                    job.id,
                    job.artist or "",
                    job.album or "",
                    job.title or "",
                    job.state.value,
                    score_text,
                    retries,
                    job.updated_at.isoformat(timespec="seconds"),
                    last_note,
                )
            )

        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            (
                job_id,
                artist,
                album,
                title,
                state,
                score,
                retries,
                updated,
                last_note,
            ) = row
            self._job_ids.append(job_id)
            item_artist = QTableWidgetItem(artist)
            item_artist.setToolTip(last_note)
            self._table.setItem(row_index, 0, item_artist)
            self._table.setItem(row_index, 1, QTableWidgetItem(album))
            self._table.setItem(row_index, 2, QTableWidgetItem(title))
            item_state = QTableWidgetItem(state)
            item_state.setToolTip(last_note)
            self._table.setItem(row_index, 3, item_state)
            self._table.setItem(row_index, 4, QTableWidgetItem(score))
            self._table.setItem(row_index, 5, QTableWidgetItem(retries))
            self._table.setItem(row_index, 6, QTableWidgetItem(updated))
            note_item = QTableWidgetItem(last_note)
            note_item.setToolTip(last_note)
            self._table.setItem(row_index, 7, note_item)

    def poll_downloads(self) -> None:
        """Refresh job rows; download polling is handled by automation service."""
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

    def _pick_result_for_selected_job(self) -> None:
        selected = self._selected_ids()
        if len(selected) != 1:
            QMessageBox.information(self, "Acquisition", "Select exactly one job.")
            return

        job_id = selected[0]
        job = self._container.acquisition_engine.get(job_id)
        if job is None:
            return
        if job.state is not AcquisitionJobState.WAITING_FOR_USER:
            QMessageBox.information(
                self,
                "Acquisition",
                "Result picker is meant for jobs waiting for user confirmation.",
            )
            return

        if not job.extra.get("scored_results") or not job.extra.get("search_results"):
            self._container.acquisition_runner.search_and_score(job_id)
            job = self._container.acquisition_engine.get(job_id)
            if job is None:
                return

        search_results_raw = job.extra.get("search_results") or []
        scored_raw = job.extra.get("scored_results") or []

        # Build score lookup.
        score_by_result_id: dict[str, float] = {}
        for row in scored_raw:
            if isinstance(row, dict) and row.get("result_id") is not None:
                score_by_result_id[str(row["result_id"])] = float(row.get("score") or 0.0)

        dialog = _ResultPickerDialog(self)
        dialog.setWindowTitle("Pick acquisition result")

        item_by_result_id: dict[str, dict] = {}
        for item in search_results_raw:
            if not isinstance(item, dict):
                continue
            rid = item.get("result_id")
            if rid is None:
                continue
            rid_s = str(rid)
            item_by_result_id[rid_s] = item

        # Populate rows sorted by score (best first).
        for rid_s, score in sorted(score_by_result_id.items(), key=lambda kv: kv[1], reverse=True):
            item = item_by_result_id.get(rid_s)
            if not item:
                continue
            dialog.add_row(
                result_id=rid_s,
                score=score,
                display_name=str(item.get("display_name") or rid_s),
                provider_id=str(item.get("provider_id") or ""),
                format=str(item.get("format") or ""),
                bit_depth=item.get("bit_depth"),
                track_count=item.get("track_count"),
            )

        if dialog.row_count() == 0:
            QMessageBox.warning(self, "Acquisition", "No scored results available to pick.")
            return

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        picked_result_id = dialog.selected_result_id()
        if not picked_result_id:
            return

        try:
            outcome = self._container.acquisition_runner.start_download_by_result_id(
                job_id, picked_result_id
            )
            QMessageBox.information(
                self, "Acquisition", outcome.message or outcome.state.value
            )
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


class _ResultPickerDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected_result_id: str | None = None

        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Score", "Result", "Provider", "Format", "BitDepth", "TrackCount"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Download selected")
        cancel_btn = QPushButton("Cancel")
        ok_btn.setDefault(True)
        cancel_btn.setProperty("secondary", True)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        ok_btn.clicked.connect(self._on_ok)
        cancel_btn.clicked.connect(self.reject)

    def add_row(
        self,
        *,
        result_id: str,
        score: float,
        display_name: str,
        provider_id: str,
        format: str,
        bit_depth: object,
        track_count: object,
    ) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(f"{score:.2f}"))
        self._table.setItem(row, 1, QTableWidgetItem(display_name))
        self._table.setItem(row, 2, QTableWidgetItem(provider_id))
        self._table.setItem(row, 3, QTableWidgetItem(format))
        depth_text = str(bit_depth) if bit_depth is not None else ""
        count_text = str(track_count) if track_count is not None else ""
        self._table.setItem(row, 4, QTableWidgetItem(depth_text))
        self._table.setItem(row, 5, QTableWidgetItem(count_text))
        self._table.setRowHeight(row, 22)
        # Store result id on the "Result" cell.
        self._table.item(row, 1).setData(256, result_id)  # Qt.UserRole

    def row_count(self) -> int:
        return self._table.rowCount()

    def selected_result_id(self) -> str | None:
        return self._selected_result_id

    def _on_ok(self) -> None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        if not rows:
            self._selected_result_id = None
            self.accept()
            return
        row_index = sorted(rows)[0]
        item = self._table.item(row_index, 1)
        rid = item.data(256) if item is not None else None  # Qt.UserRole
        self._selected_result_id = str(rid) if rid is not None else None
        self.accept()

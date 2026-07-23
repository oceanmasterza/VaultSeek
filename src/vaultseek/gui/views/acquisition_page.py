"""Acquisition page — wishlist, job progress, and manual controls."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
from vaultseek.gui.async_task import run_in_background
from vaultseek.gui.datetime_format import format_local_datetime
from vaultseek.gui.widgets.empty_state import EmptyState
from vaultseek.models.entities.acquisition_job import AcquisitionJobState
from vaultseek.services.wanted import is_parked


class AcquisitionPage(QWidget):
    """Wishlist of AcquisitionJobs with search / auto-acquire actions."""

    navigate_requested = Signal(str)

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._job_ids: list[UUID] = []

        layout = QVBoxLayout(self)
        heading = QLabel("Wishlist")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        help_lbl = QLabel(
            "Download queue for missing albums and upgrades. Queue jobs from Find music, "
            "then auto-acquire or pick results here."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addWidget(help_lbl)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._show_wanted = QCheckBox("Show Wanted (parked)")
        self._show_wanted.setToolTip(
            "Wanted items are parked Discogs picks that do not search until you Start download. "
            "Hidden from this list by default."
        )
        self._show_wanted.toggled.connect(self.refresh)
        layout.addWidget(self._show_wanted)

        self._empty = EmptyState(
            "Wishlist is empty",
            "Find missing songs or browse Discogs, then come back here to download.",
            primary_label="Find music",
            on_primary=lambda: self.navigate_requested.emit("find"),
            secondary_label="Scan for missing",
            on_secondary=self._scan_missing,
        )
        layout.addWidget(self._empty)

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
        find_btn = QPushButton("Find music…")
        for btn in (cancel_btn, refresh_btn, pick_btn, find_btn):
            btn.setProperty("secondary", True)
        scan_btn.setToolTip("Create AcquisitionJobs from MusicBrainz release gaps.")
        run_btn.setToolTip(
            "Search providers, score hits, and download when score meets the "
            "auto-acquire threshold in Settings. Uses the selected row(s), or the "
            "top row when nothing is selected."
        )
        acquire_btn.setToolTip(
            "Download the highest-scored result for the selected job "
            "(or the top row when nothing is selected)."
        )
        pick_btn.setToolTip(
            "For jobs waiting on user confirmation: open a picker and download a result."
        )
        scan_btn.clicked.connect(self._scan_missing)
        run_btn.clicked.connect(self._auto_acquire_selected)
        acquire_btn.clicked.connect(self._acquire_top_selected)
        pick_btn.clicked.connect(self._pick_result_for_selected_job)
        cancel_btn.clicked.connect(self._cancel_selected)
        refresh_btn.clicked.connect(self.refresh)
        find_btn.clicked.connect(lambda: self.navigate_requested.emit("find"))
        row1.addWidget(scan_btn)
        row1.addWidget(run_btn)
        row1.addWidget(acquire_btn)
        row1.addWidget(pick_btn)
        row1.addWidget(cancel_btn)
        row1.addWidget(refresh_btn)
        row1.addWidget(find_btn)
        row1.addStretch(1)
        layout.addLayout(row1)
        self._empty.setVisible(False)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        selected_rows = {index.row() for index in self._table.selectedIndexes()}
        previous_ids = {
            self._job_ids[row]
            for row in selected_rows
            if 0 <= row < len(self._job_ids)
        }

        self._table.setRowCount(0)
        self._job_ids = []
        threshold = self._container.config.acquisition.auto_acquire_threshold
        if self._library_id is None:
            self._summary.setText("No library selected.")
            self._empty.setVisible(True)
            self._table.setVisible(False)
            return

        jobs = self._container.acquisition_engine.list_jobs(library_id=self._library_id)
        wanted_count = sum(1 for job in jobs if is_parked(job))
        if not self._show_wanted.isChecked():
            jobs = [job for job in jobs if not is_parked(job)]
        active = sum(1 for job in jobs if not job.is_terminal)
        waiting = sum(1 for job in jobs if job.state is AcquisitionJobState.WAITING_FOR_USER)
        wanted_note = f" · {wanted_count} wanted (hidden)" if wanted_count and not self._show_wanted.isChecked() else (
            f" · {wanted_count} wanted" if wanted_count else ""
        )
        self._summary.setText(
            f"{len(jobs)} shown{wanted_note} · {active} active · {waiting} awaiting choice · "
            f"auto-acquire ≥ {threshold:.0%}"
        )

        empty = len(jobs) == 0
        self._empty.setVisible(empty)
        self._table.setVisible(not empty)
        if empty:
            return

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
                    format_local_datetime(job.updated_at),
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

        restored = False
        for row_index, job_id in enumerate(self._job_ids):
            if job_id in previous_ids:
                self._table.selectRow(row_index)
                restored = True
                break
        if not restored and self._job_ids:
            self._table.selectRow(0)
            self._table.setCurrentCell(0, 0)

    def poll_downloads(self) -> None:
        """Refresh job rows; download polling is handled by automation service."""
        self.refresh()

    def _selected_ids(self) -> list[UUID]:
        rows = {index.row() for index in self._table.selectedIndexes()}
        ids = [self._job_ids[row] for row in sorted(rows) if 0 <= row < len(self._job_ids)]
        if ids:
            return ids
        if self._job_ids:
            self._table.selectRow(0)
            return [self._job_ids[0]]
        return []

    def _auto_acquire_selected(self) -> None:
        selected = self._selected_ids()
        if not selected:
            QMessageBox.information(self, "Acquisition", "No jobs available.")
            return
        connected = self._container.provider_manager.connected_provider_ids()
        if not connected:
            QMessageBox.warning(
                self,
                "Acquisition",
                "No acquisition providers are connected.\n\n"
                "Enable Nicotine+ in Settings → Acquisition and confirm Nicotine+ "
                "(and its API / proxy) is running. Failures also appear under "
                "Dashboard → Attention needed.",
            )
        runner = self._container.acquisition_runner
        self._summary.setText("Running auto-acquire in the background…")

        def work() -> list[str]:
            outcomes: list[str] = []
            for job_id in selected:
                try:
                    job = self._container.acquisition_engine.get(job_id)
                    if is_parked(job):
                        outcomes.append("skipped — parked on Wanted (use Start download)")
                        continue
                    outcome = runner.try_auto_acquire(job_id)
                    detail = outcome.message or outcome.state.value
                    outcomes.append(f"{outcome.state.value}: {detail}")
                except (KeyError, ValueError) as exc:
                    outcomes.append(f"error — {exc}")
            return outcomes

        def done(outcomes: object) -> None:
            lines = outcomes if isinstance(outcomes, list) else [str(outcomes)]
            QMessageBox.information(self, "Acquisition", "\n".join(lines[:12]))
            self.refresh()

        run_in_background(
            work,
            on_finished=done,
            on_failed=lambda msg: QMessageBox.warning(self, "Acquisition", msg),
        )

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
        library_id = self._library_id
        auto_queue = self._container.config.acquisition.auto_queue_jobs
        engine = self._container.acquisition_engine
        providers = self._container.provider_manager
        self._summary.setText("Scanning for missing tracks (this may take a minute)…")

        def work() -> tuple[int, tuple[str, ...], bool]:
            created = analyzer.create_jobs_for_library(
                engine,
                library_id,
                auto_queue=auto_queue,
            )
            connected = providers.connected_provider_ids()
            return len(created), connected, auto_queue

        def done(result: object) -> None:
            created_count, connected, queued = result  # type: ignore[misc]
            from loguru import logger

            if created_count:
                logger.info(
                    "Missing-media scan created {} wishlist job(s); connected providers: {}",
                    created_count,
                    ", ".join(connected) if connected else "(none)",
                )
            extra = ""
            if created_count and not connected:
                extra = (
                    "\n\nWarning: no acquisition providers are connected — "
                    "searches will fail until Nicotine+ is online. "
                    "Check Dashboard → Attention needed after auto-acquire runs."
                )
            elif created_count and queued:
                extra = "\n\nJobs were queued; background automation will search shortly."
            elif created_count:
                extra = (
                    "\n\nJobs are created but not queued "
                    "(enable auto_queue_jobs in Settings, or use Auto-acquire selected)."
                )
            QMessageBox.information(
                self,
                "Acquisition",
                f"Created {created_count} missing-track job(s).{extra}",
            )
            self.refresh()

        run_in_background(
            work,
            on_finished=done,
            on_failed=lambda msg: QMessageBox.warning(self, "Acquisition", msg),
        )

    def _acquire_top_selected(self) -> None:
        selected = self._selected_ids()
        if not selected:
            QMessageBox.information(self, "Acquisition", "No jobs available.")
            return
        if len(selected) > 1:
            QMessageBox.information(
                self,
                "Acquisition",
                "Select a single job (or clear selection to use the top row).",
            )
            return
        job_id = selected[0]
        runner = self._container.acquisition_runner
        engine = self._container.acquisition_engine
        self._summary.setText("Acquiring best match in the background…")

        def work() -> str:
            job = engine.get(job_id)
            if job is None:
                return "Job not found."
            scored = job.extra.get("scored_results") or []
            if not scored:
                outcome = runner.search_and_score(job_id)
                if outcome.state is AcquisitionJobState.QUEUED:
                    return outcome.message or "Search deferred (rate limit)."
                if outcome.scored_count == 0:
                    return "No search results to acquire."
                job = engine.get(job_id)
                assert job is not None
                scored = job.extra.get("scored_results") or []
            top = scored[0]
            if not isinstance(top, dict) or not top.get("result_id"):
                return "No scored result available."
            outcome = runner.start_download_by_result_id(job_id, str(top["result_id"]))
            return outcome.message or outcome.state.value

        def done(message: object) -> None:
            text = str(message)
            if text.startswith("No ") or text.endswith("not found."):
                QMessageBox.warning(self, "Acquisition", text)
            else:
                QMessageBox.information(self, "Acquisition", text)
            self.refresh()

        run_in_background(
            work,
            on_finished=done,
            on_failed=lambda msg: QMessageBox.warning(self, "Acquisition", msg),
        )

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

"""Dashboard — collection health, pipeline transparency, live work."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.core.logging import get_live_log_buffer
from vaultseek.gui.widgets.pipeline_flow import PipelineFlowWidget
from vaultseek.models.entities.track import LibraryZone
from vaultseek.services.dashboard import DashboardSnapshot, build_dashboard_snapshot


class _KpiCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("kpiCard", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        self._value = QLabel("—")
        self._value.setProperty("kpiValue", True)
        self._title = QLabel(title)
        self._title.setProperty("muted", True)
        layout.addWidget(self._value)
        layout.addWidget(self._title)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class DashboardPage(QWidget):
    """Operations dashboard: where the collection is, and where work is."""

    navigate_requested = Signal(str)  # nav key: review, jobs, library, settings

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll)

        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(14)

        header = QHBoxLayout()
        self._heading = QLabel("Dashboard")
        self._heading.setProperty("heading", True)
        header.addWidget(self._heading)
        header.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.setProperty("secondary", True)
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        layout.addLayout(header)

        self._insight = QLabel("")
        self._insight.setWordWrap(True)
        self._insight.setProperty("insight", True)
        layout.addWidget(self._insight)

        # KPI row
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self._kpi_tracks = _KpiCard("Tracks in collection")
        self._kpi_tracks.setToolTip(
            "Cumulative catalog size for this library. New scans add tracks; "
            "they do not replace earlier totals."
        )
        self._kpi_pending = _KpiCard("Jobs pending")
        self._kpi_pending.setToolTip("Work waiting in the queue right now (current backlog).")
        self._kpi_running = _KpiCard("Jobs running")
        self._kpi_failed = _KpiCard("Jobs failed")
        self._kpi_review = _KpiCard("Awaiting review")
        self._kpi_done = _KpiCard("Completed today")
        self._kpi_done.setToolTip("Jobs finished since midnight (rolling day counter).")
        for card in (
            self._kpi_tracks,
            self._kpi_pending,
            self._kpi_running,
            self._kpi_failed,
            self._kpi_review,
            self._kpi_done,
        ):
            kpi_row.addWidget(card)
        layout.addLayout(kpi_row)

        # Quick actions
        actions = QHBoxLayout()
        self._btn_review = QPushButton("Open Review")
        self._btn_jobs = QPushButton("Open Jobs")
        self._btn_acquisition = QPushButton("Open Acquisition")
        self._btn_library = QPushButton("Open Library")
        self._btn_scan = QPushButton("Scan Incoming")
        self._btn_force_scan = QPushButton("Force rescan")
        for btn in (
            self._btn_jobs,
            self._btn_acquisition,
            self._btn_library,
            self._btn_scan,
            self._btn_force_scan,
        ):
            btn.setProperty("secondary", True)
        self._btn_scan.setToolTip(
            "Scan Incoming and only process new or changed files (size/mtime)."
        )
        self._btn_force_scan.setToolTip(
            "Re-queue every audio file in Incoming through hash → identify → artwork, "
            "even if it was already scanned."
        )
        self._btn_review.clicked.connect(lambda: self.navigate_requested.emit("review"))
        self._btn_jobs.clicked.connect(lambda: self.navigate_requested.emit("jobs"))
        self._btn_acquisition.clicked.connect(lambda: self.navigate_requested.emit("acquisition"))
        self._btn_library.clicked.connect(lambda: self.navigate_requested.emit("library"))
        self._btn_scan.clicked.connect(lambda: self.navigate_requested.emit("scan"))
        self._btn_force_scan.clicked.connect(lambda: self.navigate_requested.emit("force_scan"))
        actions.addWidget(self._btn_review)
        actions.addWidget(self._btn_jobs)
        actions.addWidget(self._btn_acquisition)
        actions.addWidget(self._btn_library)
        actions.addWidget(self._btn_scan)
        actions.addWidget(self._btn_force_scan)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._last_scan = QLabel("")
        self._last_scan.setWordWrap(True)
        self._last_scan.setProperty("muted", True)
        layout.addWidget(self._last_scan)

        self._processing_report = QLabel("")
        self._processing_report.setWordWrap(True)
        self._processing_report.setProperty("muted", True)
        layout.addWidget(self._processing_report)

        acq_box = QFrame()
        acq_box.setProperty("dashPanel", True)
        acq_layout = QVBoxLayout(acq_box)
        acq_layout.addWidget(self._panel_title("Acquisition"))
        acq_help = QLabel(
            "Wishlist jobs from missing-media scans. Auto-acquire runs in the background "
            "when scores meet the threshold in Settings."
        )
        acq_help.setWordWrap(True)
        acq_help.setProperty("muted", True)
        acq_layout.addWidget(acq_help)
        self._acquisition_summary = QLabel("No acquisition jobs yet.")
        self._acquisition_summary.setWordWrap(True)
        acq_layout.addWidget(self._acquisition_summary)
        layout.addWidget(acq_box)

        # Pipeline
        pipe_box = QFrame()
        pipe_box.setProperty("dashPanel", True)
        pipe_layout = QVBoxLayout(pipe_box)
        pipe_title = QLabel("Processing pipeline")
        pipe_title.setProperty("panelTitle", True)
        pipe_help = QLabel(
            "Left → right: Acquiring (wishlist / missing media) → Discover → Hash → "
            "Fingerprint → Identify → Review → Duplicates / Rules → Organize → Artwork → Sync. "
            "Acquiring counts come from acquisition jobs, not the library job queue."
        )
        pipe_help.setWordWrap(True)
        pipe_help.setProperty("muted", True)
        self._pipeline = PipelineFlowWidget()
        pipe_layout.addWidget(pipe_title)
        pipe_layout.addWidget(pipe_help)
        pipe_layout.addWidget(self._pipeline)
        layout.addWidget(pipe_box)

        # Collection + confidence side by side
        mid = QHBoxLayout()
        mid.setSpacing(12)

        zone_box = QFrame()
        zone_box.setProperty("dashPanel", True)
        zone_layout = QVBoxLayout(zone_box)
        zone_layout.addWidget(self._panel_title("Collection by zone"))
        zone_help = QLabel(
            "Totals for the whole library — each new Incoming scan adds to these, "
            "it does not reset them. Use Settings → Reset processing to clear queues "
            "(or catalog records) without creating a new library."
        )
        zone_help.setWordWrap(True)
        zone_help.setProperty("muted", True)
        zone_layout.addWidget(zone_help)
        self._zone_bars: dict[str, tuple[QLabel, QProgressBar, QLabel]] = {}
        for zone in LibraryZone:
            row = QHBoxLayout()
            label = QLabel(zone.value.title())
            label.setMinimumWidth(80)
            bar = QProgressBar()
            bar.setTextVisible(False)
            count = QLabel("0")
            count.setMinimumWidth(40)
            count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(label)
            row.addWidget(bar, stretch=1)
            row.addWidget(count)
            zone_layout.addLayout(row)
            self._zone_bars[zone.value] = (label, bar, count)
        mid.addWidget(zone_box, stretch=1)

        conf_box = QFrame()
        conf_box.setProperty("dashPanel", True)
        conf_layout = QVBoxLayout(conf_box)
        conf_layout.addWidget(self._panel_title("Identification confidence"))
        self._avg_conf = QLabel("Average: —")
        self._avg_conf.setProperty("muted", True)
        conf_layout.addWidget(self._avg_conf)
        self._conf_bars: dict[str, tuple[QLabel, QProgressBar, QLabel]] = {}
        for key, title in (
            ("unscored", "Not identified yet"),
            ("low", "Low (< 50%)"),
            ("fair", "Fair (50–90%)"),
            ("high", "High (≥ 90%)"),
            ("flagged", "Flagged for review"),
        ):
            row = QHBoxLayout()
            label = QLabel(title)
            label.setMinimumWidth(140)
            bar = QProgressBar()
            bar.setTextVisible(False)
            count = QLabel("0")
            count.setMinimumWidth(40)
            count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(label)
            row.addWidget(bar, stretch=1)
            row.addWidget(count)
            conf_layout.addLayout(row)
            self._conf_bars[key] = (label, bar, count)
        conf_note = QLabel(
            "High ≥ auto-approve threshold. Flagged tracks need a human decision "
            "even if some fields look strong."
        )
        conf_note.setWordWrap(True)
        conf_note.setProperty("muted", True)
        conf_layout.addWidget(conf_note)
        mid.addWidget(conf_box, stretch=1)
        layout.addLayout(mid)

        # Review breakdown + duplicates
        review_box = QFrame()
        review_box.setProperty("dashPanel", True)
        review_layout = QVBoxLayout(review_box)
        review_layout.addWidget(self._panel_title("Attention needed"))
        self._review_detail = QLabel("No pending review items.")
        self._review_detail.setWordWrap(True)
        review_layout.addWidget(self._review_detail)
        layout.addWidget(review_box)

        fail_box = QFrame()
        fail_box.setProperty("dashPanel", True)
        fail_layout = QVBoxLayout(fail_box)
        fail_layout.addWidget(self._panel_title("Common failures"))
        fail_help = QLabel(
            "Grouped from failed jobs — the pattern that is blocking the most work."
        )
        fail_help.setWordWrap(True)
        fail_help.setProperty("muted", True)
        fail_layout.addWidget(fail_help)
        self._failure_summary = QLabel("No failed jobs.")
        self._failure_summary.setWordWrap(True)
        fail_layout.addWidget(self._failure_summary)
        layout.addWidget(fail_box)

        # Recent failures + live activity log
        live = QHBoxLayout()
        live.setSpacing(12)

        failed_box = QFrame()
        failed_box.setProperty("dashPanel", True)
        failed_layout = QVBoxLayout(failed_box)
        failed_layout.addWidget(self._panel_title("Recent failures"))
        self._failed_table = QTableWidget(0, 3)
        self._failed_table.setHorizontalHeaderLabels(["Type", "Error", "Attempts"])
        self._failed_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._failed_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._failed_table.horizontalHeader().setStretchLastSection(True)
        self._failed_table.setMaximumHeight(180)
        failed_layout.addWidget(self._failed_table)
        live.addWidget(failed_box, stretch=1)

        log_box = QFrame()
        log_box.setProperty("dashPanel", True)
        log_layout = QVBoxLayout(log_box)
        log_layout.addWidget(self._panel_title("Live activity"))
        log_help = QLabel(
            "Recent app log lines (scan, search, acquire). Full history is still in the log folder."
        )
        log_help.setWordWrap(True)
        log_help.setProperty("muted", True)
        log_layout.addWidget(log_help)
        self._live_log = QPlainTextEdit()
        self._live_log.setReadOnly(True)
        self._live_log.setMaximumBlockCount(400)
        self._live_log.setMinimumHeight(160)
        self._live_log.setMaximumHeight(220)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)
        self._live_log.setFont(mono)
        self._live_log.setPlaceholderText("Waiting for activity…")
        log_layout.addWidget(self._live_log)
        live.addWidget(log_box, stretch=2)
        layout.addLayout(live)

        layout.addStretch(1)

    @staticmethod
    def _panel_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("panelTitle", True)
        return label

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        snap = build_dashboard_snapshot(self._container, self._library_id)
        self._apply(snap)
        self._refresh_live_log()

    def _refresh_live_log(self) -> None:
        text = get_live_log_buffer().text()
        # Avoid resetting scroll when content is unchanged.
        if self._live_log.toPlainText() == text:
            return
        at_bottom = (
            self._live_log.verticalScrollBar().value()
            >= self._live_log.verticalScrollBar().maximum() - 4
        )
        self._live_log.setPlainText(text)
        if at_bottom or not text:
            self._live_log.moveCursor(QTextCursor.MoveOperation.End)

    def _apply(self, snap: DashboardSnapshot) -> None:
        if not snap.has_library:
            self._heading.setText("Dashboard")
            self._insight.setText(snap.insight)
            for card in (
                self._kpi_tracks,
                self._kpi_pending,
                self._kpi_running,
                self._kpi_failed,
                self._kpi_review,
                self._kpi_done,
            ):
                card.set_value("—")
            self._pipeline.set_stages(())
            self._failed_table.setRowCount(0)
            self._review_detail.setText("Select or create a library in Settings.")
            self._failure_summary.setText("No failed jobs.")
            self._last_scan.setText("")
            self._processing_report.setText("")
            self._acquisition_summary.setText("No acquisition jobs yet.")
            self._refresh_live_log()
            return

        self._heading.setText(f"Dashboard — {snap.library_name}")
        self._insight.setText(snap.insight)
        self._last_scan.setText(snap.last_scan_summary)
        self._processing_report.setText(snap.processing_report)
        self._apply_acquisition_summary(snap)
        self._kpi_tracks.set_value(str(snap.track_count))
        self._kpi_pending.set_value(str(snap.pending_jobs))
        self._kpi_running.set_value(str(snap.running_jobs))
        self._kpi_failed.set_value(str(snap.failed_jobs))
        self._kpi_review.set_value(str(snap.review_pending))
        self._kpi_done.set_value(str(snap.completed_today))

        self._pipeline.set_stages(snap.stages)

        zone_total = max(sum(snap.tracks_by_zone.values()), 1)
        for zone, (_label, bar, count) in self._zone_bars.items():
            value = int(snap.tracks_by_zone.get(zone, 0))
            bar.setMaximum(zone_total)
            bar.setValue(value)
            count.setText(str(value))

        conf_total = max(snap.track_count, 1)
        for key, (_label, bar, count) in self._conf_bars.items():
            value = int(snap.confidence.get(key, 0))
            # flagged can overlap; still show against track_count for scale
            bar.setMaximum(conf_total)
            bar.setValue(min(value, conf_total))
            count.setText(str(value))
        if snap.average_confidence is None:
            self._avg_conf.setText("Average confidence: — (none scored yet)")
        else:
            self._avg_conf.setText(f"Average confidence: {snap.average_confidence:.0%}")

        if snap.review_pending == 0 and snap.open_duplicates == 0:
            self._review_detail.setText(
                "Nothing waiting on you — no pending reviews or open duplicates."
            )
        else:
            parts = [f"{snap.review_pending} review item(s)"]
            if snap.review_by_type:
                breakdown = ", ".join(
                    f"{name.replace('_', ' ')}: {count}"
                    for name, count in sorted(snap.review_by_type.items())
                )
                parts.append(f"({breakdown})")
            if snap.open_duplicates:
                parts.append(f"· {snap.open_duplicates} open duplicate group(s)")
            self._review_detail.setText(" ".join(parts))

        if snap.top_failures:
            lines = [
                f"• {count}× [{job_type}] {summary}"
                for job_type, summary, count in snap.top_failures
            ]
            self._failure_summary.setText("\n".join(lines))
        else:
            self._failure_summary.setText("No failed jobs.")

        self._fill_jobs(self._failed_table, snap.failed_job_rows, kind="failed")

    def _apply_acquisition_summary(self, snap: DashboardSnapshot) -> None:
        acq = snap.acquisition
        if acq.total == 0:
            self._acquisition_summary.setText(
                "No acquisition jobs yet. Use Acquisition → Scan for missing to create a wishlist."
            )
            return
        parts = [
            f"{acq.total} job(s) total",
            f"{acq.active} active",
            f"{acq.completed} completed",
        ]
        if acq.in_progress:
            parts.append(f"{acq.in_progress} in progress")
        if acq.waiting_for_user:
            parts.append(f"{acq.waiting_for_user} awaiting your pick")
        if acq.failed:
            parts.append(f"{acq.failed} failed / no results")
        self._acquisition_summary.setText(" · ".join(parts))

    def _fill_jobs(self, table: QTableWidget, jobs: tuple, *, kind: str) -> None:
        table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            table.setItem(row, 0, QTableWidgetItem(job.job_type.value))
            if kind == "running":
                table.setItem(row, 1, QTableWidgetItem(str(job.attempt_count)))
                started = (
                    job.started_at.isoformat(timespec="seconds") if job.started_at else "—"
                )
                table.setItem(row, 2, QTableWidgetItem(started))
            else:
                err = (job.error_message or "")[:120]
                table.setItem(row, 1, QTableWidgetItem(err))
                table.setItem(row, 2, QTableWidgetItem(str(job.attempt_count)))
        if not jobs:
            table.setRowCount(1)
            empty = QTableWidgetItem("None" if kind == "running" else "No recent failures")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            table.setItem(0, 0, empty)
            table.setSpan(0, 0, 1, 3)

"""Acquisition / library reports with pie charts."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

from PySide6.QtCharts import QChart, QChartView, QPieSeries
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.widgets.desktop import open_path
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJobState,
    AcquisitionJobType,
)
from vaultseek.services.dto.report_dto import ReportFormat, ReportRequest, ReportType

# Fresh chart baseline each time VaultSeek starts (not persisted across restarts).
_SESSION_STARTED_AT = datetime.now(UTC)


def _pie_chart(title: str, counts: dict[str, int]) -> QChartView:
    series = QPieSeries()
    for label, value in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        if value <= 0:
            continue
        slice_ = series.append(f"{label} ({value})", float(value))
        slice_.setLabelVisible(True)
    chart = QChart()
    chart.addSeries(series)
    chart.setTitle(title)
    chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
    view = QChartView(chart)
    view.setRenderHint(QPainter.RenderHint.Antialiasing)
    view.setMinimumHeight(280)
    return view


class ReportsPage(QWidget):
    """Charts for acquisition success on albums vs tracks."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Reports")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        help_lbl = QLabel(
            "How acquisition is doing this session (charts reset when you reopen VaultSeek). "
            "Use Refresh after downloads complete."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addWidget(help_lbl)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        charts = QHBoxLayout()
        self._by_type_host = QVBoxLayout()
        self._by_state_host = QVBoxLayout()
        self._album_state_host = QVBoxLayout()
        self._track_state_host = QVBoxLayout()
        charts.addLayout(self._by_type_host, stretch=1)
        charts.addLayout(self._by_state_host, stretch=1)
        layout.addLayout(charts)

        charts2 = QHBoxLayout()
        charts2.addLayout(self._album_state_host, stretch=1)
        charts2.addLayout(self._track_state_host, stretch=1)
        layout.addLayout(charts2)

        actions = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.setProperty("secondary", True)
        refresh.clicked.connect(self.refresh)
        open_reports = QPushButton("Open reports folder")
        open_reports.setProperty("secondary", True)
        open_reports.clicked.connect(
            lambda: open_path(self._container.paths.reports_dir)
        )
        gen = QPushButton("Generate library summary file")
        gen.setToolTip("Write a library summary JSON under the reports folder.")
        gen.clicked.connect(self._generate_summary)
        actions.addWidget(refresh)
        actions.addWidget(open_reports)
        actions.addWidget(gen)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)

        self._chart_views: list[QChartView] = []

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._clear_charts()
        if self._library_id is None:
            self._summary.setText("No library selected.")
            return

        jobs = self._container.acquisition_engine.list_jobs(library_id=self._library_id)
        jobs = [
            job
            for job in jobs
            if _aware(job.created_at) >= _SESSION_STARTED_AT
        ]
        if not jobs:
            self._summary.setText(
                "No acquisition activity yet this session "
                f"(started {_SESSION_STARTED_AT.astimezone().strftime('%H:%M')})."
            )
            return

        by_type = Counter(job.job_type.value.replace("_", " ") for job in jobs)
        by_state = Counter(_state_bucket(job.state) for job in jobs)

        album_jobs = [j for j in jobs if j.job_type is AcquisitionJobType.MISSING_ALBUM]
        track_jobs = [
            j
            for j in jobs
            if j.job_type
            in (AcquisitionJobType.MISSING_TRACK, AcquisitionJobType.QUALITY_UPGRADE)
        ]
        album_state = Counter(_state_bucket(j.state) for j in album_jobs)
        track_state = Counter(_state_bucket(j.state) for j in track_jobs)

        completed = sum(1 for j in jobs if j.state is AcquisitionJobState.COMPLETED)
        failed = sum(1 for j in jobs if _state_bucket(j.state) == "failed")
        active = sum(1 for j in jobs if _state_bucket(j.state) == "in progress")
        self._summary.setText(
            f"{len(jobs)} acquisition job(s) · {completed} completed · "
            f"{active} in progress · {failed} failed · "
            f"{len(album_jobs)} album job(s) · {len(track_jobs)} track/upgrade job(s)"
        )

        self._add_chart(self._by_type_host, "Jobs by type", dict(by_type))
        self._add_chart(self._by_state_host, "All jobs by outcome", dict(by_state))
        self._add_chart(
            self._album_state_host,
            "Album jobs (missing album)",
            dict(album_state) if album_state else {"none yet": 1},
        )
        self._add_chart(
            self._track_state_host,
            "Track / upgrade jobs",
            dict(track_state) if track_state else {"none yet": 1},
        )

    def _generate_summary(self) -> None:
        if self._library_id is None:
            return
        result = self._container.report_service.generate(
            ReportRequest(
                report_type=ReportType.LIBRARY_SUMMARY,
                library_id=self._library_id,
                format=ReportFormat.JSON,
            )
        )
        if result.success and result.output_path:
            self._summary.setText(f"Wrote library summary: {result.output_path}")
        else:
            self._summary.setText(result.message or "Report generation failed.")

    def _add_chart(self, host: QVBoxLayout, title: str, counts: dict[str, int]) -> None:
        view = _pie_chart(title, counts)
        host.addWidget(view)
        self._chart_views.append(view)

    def _clear_charts(self) -> None:
        for host in (
            self._by_type_host,
            self._by_state_host,
            self._album_state_host,
            self._track_state_host,
        ):
            while host.count():
                item = host.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        self._chart_views.clear()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _state_bucket(state: AcquisitionJobState) -> str:
    if state is AcquisitionJobState.COMPLETED:
        return "completed"
    if state in {
        AcquisitionJobState.DOWNLOAD_FAILED,
        AcquisitionJobState.VERIFICATION_FAILED,
        AcquisitionJobState.IMPORT_FAILED,
        AcquisitionJobState.NO_RESULTS,
    }:
        return "failed"
    if state is AcquisitionJobState.CANCELLED:
        return "cancelled"
    if state is AcquisitionJobState.WAITING_FOR_USER:
        return "needs choice"
    if state in {
        AcquisitionJobState.CREATED,
        AcquisitionJobState.QUEUED,
        AcquisitionJobState.RETRY_SCHEDULED,
    }:
        return "queued"
    return "in progress"

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
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.config import AcquisitionConfig, save_config
from vaultseek.core.container import Container
from vaultseek.core.logging import get_live_log_buffer
from vaultseek.gui.async_task import run_in_background
from vaultseek.gui.user_help import HelpDialog
from vaultseek.gui.widgets.flow_host import FlowHost
from vaultseek.gui.widgets.integration_status import IntegrationStatusTile
from vaultseek.gui.widgets.pipeline_flow import STAGE_NAV_KEYS, PipelineFlowWidget
from vaultseek.gui.widgets.table_utils import (
    configure_data_table,
)
from vaultseek.models.entities.job import Job
from vaultseek.models.entities.track import LibraryZone
from vaultseek.services.connection_status import (
    dashboard_probe_fingerprint,
    has_connected_download_source,
    nzbget_enabled,
    summarize_music_tools,
)
from vaultseek.services.dashboard import DashboardSnapshot, build_dashboard_snapshot

_TEXT_SELECT = (
    Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
)


def _probe_map(result: object) -> dict[str, bool]:
    """Keep only string keys. A failed batch stays empty so tiles stay unverified."""
    if not isinstance(result, dict):
        return {}
    cleaned: dict[str, bool] = {}
    for key, value in result.items():
        if isinstance(key, str):
            cleaned[key] = bool(value)
    return cleaned


def _selectable_label(text: str = "", *, muted: bool = False, insight: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(_TEXT_SELECT)
    label.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    if muted:
        label.setProperty("muted", True)
    if insight:
        label.setProperty("insight", True)
    return label


def _text_button(text: str) -> QPushButton:
    """Button that keeps its label visible instead of shrinking in a wrapping row."""
    button = QPushButton(text)
    button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    return button


class _KpiCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("kpiCard", True)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        self._value = QLabel("—")
        self._value.setProperty("kpiValue", True)
        self._title = QLabel(title)
        self._title.setWordWrap(True)
        self._title.setProperty("muted", True)
        self._title.setTextInteractionFlags(_TEXT_SELECT)
        self._value.setTextInteractionFlags(_TEXT_SELECT)
        self._value.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
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
        self._client_probes: dict[str, bool] | None = None
        self._probe_token = 0
        self._probe_inflight = False
        self._probe_again = False
        self._probe_fingerprint = ""
        self._probe_applied_fingerprint = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(scroll)
        self._scroll = scroll

        body = QWidget()
        body.setMinimumWidth(0)
        scroll.setWidget(body)
        self._body = body
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(14)

        header = FlowHost(spacing=8)
        self._heading = QLabel("Dashboard")
        self._heading.setProperty("heading", True)
        header.flow().addWidget(self._heading)
        self._btn_setup_wizard = _text_button("Setup wizard")
        self._btn_setup_wizard.setToolTip(
            "Folders, Nicotine+, and optional tokens. Opens anytime — never forced "
            "again after first run."
        )
        self._btn_setup_wizard.setProperty("secondary", True)
        self._btn_setup_wizard.clicked.connect(lambda: self.navigate_requested.emit("setup_wizard"))
        header.flow().addWidget(self._btn_setup_wizard)
        refresh = _text_button("Refresh")
        refresh.setProperty("secondary", True)
        refresh.clicked.connect(lambda: self.refresh(reprobe=True))
        header.flow().addWidget(refresh)
        layout.addWidget(header)

        self._music_tools = QFrame()
        self._music_tools.setProperty("dashPanel", True)
        tools_layout = QVBoxLayout(self._music_tools)
        tools_title = QLabel("Music tools")
        tools_title.setProperty("panelTitle", True)
        tools_layout.addWidget(tools_title)
        self._tools_host = FlowHost(spacing=8)
        self._status_tiles: dict[str, IntegrationStatusTile] = {}
        tools_layout.addWidget(self._tools_host)
        tools_actions = FlowHost(spacing=6)
        btn_settings = _text_button("Settings")
        btn_settings.setProperty("secondary", True)
        btn_settings.clicked.connect(lambda: self.navigate_requested.emit("settings"))
        btn_plugins = _text_button("Plugins")
        btn_plugins.setProperty("secondary", True)
        btn_plugins.clicked.connect(lambda: self.navigate_requested.emit("plugins"))
        btn_help = _text_button("Setup instructions")
        btn_help.setProperty("secondary", True)
        btn_help.clicked.connect(lambda: HelpDialog(self, topic="connection-setup").exec())
        tools_actions.flow().addWidget(btn_settings)
        tools_actions.flow().addWidget(btn_plugins)
        tools_actions.flow().addWidget(btn_help)
        tools_layout.addWidget(tools_actions)
        layout.addWidget(self._music_tools)

        self._insight = _selectable_label(insight=True)
        layout.addWidget(self._insight)

        # First-time / incomplete setup checklist (hide when dismissed).
        self._getting_started = QFrame()
        self._getting_started.setProperty("dashPanel", True)
        gs_layout = QVBoxLayout(self._getting_started)
        gs_title = QLabel("Getting started")
        gs_title.setProperty("panelTitle", True)
        gs_layout.addWidget(gs_title)
        self._getting_started_body = _selectable_label()
        gs_layout.addWidget(self._getting_started_body)
        gs_actions = FlowHost(spacing=6)
        self._btn_gs_scan = _text_button("Scan Incoming")
        self._btn_gs_scan.setProperty("secondary", True)
        self._btn_gs_scan.clicked.connect(lambda: self.navigate_requested.emit("scan"))
        self._btn_gs_missing = _text_button("Find music")
        self._btn_gs_missing.setProperty("secondary", True)
        self._btn_gs_missing.clicked.connect(lambda: self.navigate_requested.emit("find"))
        self._btn_gs_dismiss = _text_button("Dismiss tips")
        self._btn_gs_dismiss.setProperty("secondary", True)
        self._btn_gs_dismiss.clicked.connect(self._dismiss_onboarding_tips)
        gs_actions.flow().addWidget(self._btn_gs_scan)
        gs_actions.flow().addWidget(self._btn_gs_missing)
        gs_actions.flow().addWidget(self._btn_gs_dismiss)
        gs_layout.addWidget(gs_actions)
        layout.addWidget(self._getting_started)

        def _section_title(text: str) -> QLabel:
            label = QLabel(text)
            label.setProperty("panelTitle", True)
            label.setTextInteractionFlags(_TEXT_SELECT)
            label.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            return label

        # Pipeline queue — work waiting/running in the library job queue *right now*
        layout.addWidget(_section_title("Library pipeline — queue right now"))
        self._pipeline_kpi_host = FlowHost(spacing=10)
        self._kpi_pending = _KpiCard("Pending")
        self._kpi_pending.setToolTip(
            "Library pipeline jobs waiting to start (scan, hash, fingerprint, identify, …)."
        )
        self._kpi_running = _KpiCard("Running")
        self._kpi_running.setToolTip("Library pipeline jobs actively processing right now.")
        self._kpi_failed = _KpiCard("Failed")
        self._kpi_failed.setToolTip("Library pipeline jobs that failed and need retry or cleanup.")
        for card in (self._kpi_pending, self._kpi_running, self._kpi_failed):
            self._pipeline_kpi_host.flow().addWidget(card)
        layout.addWidget(self._pipeline_kpi_host)

        # Totals — collection size and throughput (not the live queue)
        layout.addWidget(_section_title("Totals"))
        totals_kpi = FlowHost(spacing=10)
        self._kpi_tracks = _KpiCard("Tracks in collection")
        self._kpi_tracks.setToolTip(
            "Cumulative catalog size for this library. New scans add tracks; "
            "they do not replace earlier totals."
        )
        self._kpi_done = _KpiCard("Pipeline done today")
        self._kpi_done.setToolTip(
            "Library pipeline jobs finished since midnight (scan, identify, artwork, …)."
        )
        self._kpi_review = _KpiCard("Awaiting review")
        self._kpi_review.setToolTip("Review items waiting for your decision.")
        for card in (self._kpi_tracks, self._kpi_done, self._kpi_review):
            totals_kpi.flow().addWidget(card)
        layout.addWidget(totals_kpi)

        # Wishlist — separate from library pipeline (Soulseek downloads)
        layout.addWidget(_section_title("Wishlist — downloads in progress"))
        acq_kpi = FlowHost(spacing=10)
        self._kpi_missing = _KpiCard("Missing tracks")
        self._kpi_missing.setToolTip(
            "Tracks missing vs MusicBrainz release tracklists (detected gaps, not yet queued)."
        )
        self._kpi_acq_active = _KpiCard("Wishlist active")
        self._kpi_acq_active.setToolTip(
            "Acquisition jobs not yet finished (queued, searching, downloading, …)."
        )
        self._kpi_acq_today = _KpiCard("Acquired today")
        self._kpi_acq_today.setToolTip("Missing tracks successfully downloaded and imported today.")
        self._kpi_acq_total = _KpiCard("Acquired all-time")
        self._kpi_acq_total.setToolTip("Total acquisition jobs completed for this library.")
        for card in (
            self._kpi_missing,
            self._kpi_acq_active,
            self._kpi_acq_today,
            self._kpi_acq_total,
        ):
            acq_kpi.flow().addWidget(card)
        layout.addWidget(acq_kpi)

        self._wishlist_hint = QLabel("")
        self._wishlist_hint.setProperty("muted", True)
        self._wishlist_hint.setWordWrap(True)
        layout.addWidget(self._wishlist_hint)
        wishlist_actions = FlowHost(spacing=6)
        change_interval = _text_button("Change in Settings")
        change_interval.setProperty("secondary", True)
        change_interval.setToolTip(
            "Wishlist search interval is saved with Settings → Wishlist & downloads."
        )
        change_interval.clicked.connect(lambda: self.navigate_requested.emit("settings"))
        wishlist_actions.flow().addWidget(change_interval)
        layout.addWidget(wishlist_actions)

        actions = FlowHost(spacing=6)
        self._btn_review = _text_button("Open Review")
        self._btn_jobs = _text_button("Open Jobs")
        self._btn_acquisition = _text_button("Open Wishlist")
        self._btn_library = _text_button("Open Library")
        self._btn_scan = _text_button("Scan Incoming")
        self._btn_force_scan = _text_button("Force rescan")
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
        actions.flow().addWidget(self._btn_review)
        actions.flow().addWidget(self._btn_jobs)
        actions.flow().addWidget(self._btn_acquisition)
        actions.flow().addWidget(self._btn_library)
        actions.flow().addWidget(self._btn_scan)
        actions.flow().addWidget(self._btn_force_scan)
        layout.addWidget(actions)

        self._last_scan = _selectable_label(muted=True)
        layout.addWidget(self._last_scan)

        self._processing_report = _selectable_label(muted=True)
        layout.addWidget(self._processing_report)

        acq_box = QFrame()
        acq_box.setProperty("dashPanel", True)
        acq_layout = QVBoxLayout(acq_box)
        acq_layout.addWidget(self._panel_title("Wishlist"))
        acq_help = _selectable_label(
            "Compares your library to MusicBrainz tracklists. "
            "“Missing tracks” updates when you run Find music → Find missing songs. "
            "Auto-acquire downloads when scores meet the threshold in Settings.",
            muted=True,
        )
        acq_layout.addWidget(acq_help)
        self._acquisition_summary = _selectable_label()
        acq_layout.addWidget(self._acquisition_summary)
        layout.addWidget(acq_box)

        # Pipeline
        pipe_box = QFrame()
        pipe_box.setProperty("dashPanel", True)
        pipe_layout = QVBoxLayout(pipe_box)
        pipe_title = QLabel("Processing pipeline")
        pipe_title.setProperty("panelTitle", True)
        pipe_help = _selectable_label(
            "Left → right: Discover → Hash → Fingerprint → Identify → Review → "
            "Duplicates / Rules → Organize → Artwork → Acquiring (wishlist) → Sync. "
            "Identify the library before acquiring missing tracks.",
            muted=True,
        )
        self._pipeline = PipelineFlowWidget()
        self._pipeline.stage_clicked.connect(self._on_pipeline_stage_clicked)
        pipe_scroll = QScrollArea()
        pipe_scroll.setWidget(self._pipeline)
        pipe_scroll.setWidgetResizable(False)
        pipe_scroll.setFrameShape(QFrame.Shape.NoFrame)
        pipe_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        pipe_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pipe_scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        pipe_scroll.setMinimumHeight(160)
        pipe_layout.addWidget(pipe_title)
        pipe_layout.addWidget(pipe_help)
        pipe_layout.addWidget(pipe_scroll)
        layout.addWidget(pipe_box)

        # Collection + confidence side by side
        mid = FlowHost(spacing=12)
        zone_box = QFrame()
        zone_box.setProperty("dashPanel", True)
        zone_box.setMinimumWidth(280)
        zone_layout = QVBoxLayout(zone_box)
        zone_layout.addWidget(self._panel_title("Collection by zone"))
        zone_help = _selectable_label(
            "Totals for the whole library — each new Incoming scan adds to these, "
            "it does not reset them. Use Settings → Reset processing to clear queues "
            "(or catalog records) without creating a new library.",
            muted=True,
        )
        zone_layout.addWidget(zone_help)
        self._zone_bars: dict[str, tuple[QLabel, QProgressBar, QLabel]] = {}
        for zone in LibraryZone:
            row = QHBoxLayout()
            label = QLabel(zone.value.title())
            label.setWordWrap(True)
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
        mid.flow().addWidget(zone_box)

        conf_box = QFrame()
        conf_box.setProperty("dashPanel", True)
        conf_box.setMinimumWidth(280)
        conf_layout = QVBoxLayout(conf_box)
        conf_layout.addWidget(self._panel_title("Identification confidence"))
        self._avg_conf = _selectable_label("Average: —", muted=True)
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
            label.setWordWrap(True)
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
        conf_note = _selectable_label(
            "High ≥ auto-approve threshold. Flagged tracks need a human decision "
            "even if some fields look strong.",
            muted=True,
        )
        conf_layout.addWidget(conf_note)
        mid.flow().addWidget(conf_box)
        layout.addWidget(mid)

        # Review breakdown + duplicates
        review_box = QFrame()
        review_box.setProperty("dashPanel", True)
        review_layout = QVBoxLayout(review_box)
        review_layout.addWidget(self._panel_title("Attention needed"))
        self._review_detail = _selectable_label("No pending review items.")
        review_layout.addWidget(self._review_detail)
        layout.addWidget(review_box)

        fail_box = QFrame()
        fail_box.setProperty("dashPanel", True)
        fail_layout = QVBoxLayout(fail_box)
        fail_layout.addWidget(self._panel_title("Common failures"))
        fail_help = _selectable_label(
            "Grouped from failed jobs — the pattern that is blocking the most work.",
            muted=True,
        )
        fail_layout.addWidget(fail_help)
        self._failure_summary = _selectable_label("No failed jobs.")
        fail_layout.addWidget(self._failure_summary)
        layout.addWidget(fail_box)

        # Recent failures + live activity log
        live = FlowHost(spacing=12)
        failed_box = QFrame()
        failed_box.setProperty("dashPanel", True)
        failed_box.setMinimumWidth(280)
        failed_layout = QVBoxLayout(failed_box)
        failed_layout.addWidget(self._panel_title("Recent failures"))
        self._failed_table = QTableWidget(0, 3)
        self._failed_table.setHorizontalHeaderLabels(["Type", "Error", "Attempts"])
        self._failed_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._failed_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_data_table(self._failed_table)
        self._failed_table.setMaximumHeight(180)
        self._failed_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._failed_table.horizontalHeader().setMinimumSectionSize(48)
        failed_layout.addWidget(self._failed_table)
        live.flow().addWidget(failed_box)

        log_box = QFrame()
        log_box.setProperty("dashPanel", True)
        log_box.setMinimumWidth(280)
        log_layout = QVBoxLayout(log_box)
        log_layout.addWidget(self._panel_title("Live activity"))
        log_help = _selectable_label(
            "Recent app log lines (scan, search, acquire). Full history is in the log folder.",
            muted=True,
        )
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
        live.flow().addWidget(log_box)
        layout.addWidget(live)

        layout.addStretch(1)

    @staticmethod
    def _panel_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("panelTitle", True)
        label.setTextInteractionFlags(_TEXT_SELECT)
        label.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        return label

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self, *, reprobe: bool = False) -> None:
        hours = float(self._container.config.acquisition.wishlist_search_interval_hours or 0.0)
        interval = (
            "Wishlist search: continuous (rate-limited)"
            if hours <= 0
            else f"Wishlist search: at most every {hours:g} hour(s)"
        )
        self._wishlist_hint.setText(interval + " — change under Settings → Wishlist & downloads.")
        self._drop_stale_client_probes()
        snap = build_dashboard_snapshot(self._container, self._library_id)
        self._apply(snap)
        self._refresh_live_log()
        self._schedule_client_probes(force=reprobe)

    def _on_pipeline_stage_clicked(self, stage_key: str) -> None:
        nav_key = STAGE_NAV_KEYS.get(stage_key)
        if nav_key:
            self.navigate_requested.emit(nav_key)

    def _dismiss_onboarding_tips(self) -> None:
        from dataclasses import replace

        updated = replace(self._container.config, onboarding_tips_dismissed=True)
        save_config(updated, self._container.paths.config_file)
        self._container.config = updated
        self._getting_started.setVisible(False)

    def _refresh_getting_started(self, snap: DashboardSnapshot) -> None:
        """Show a short checklist until the user dismisses tips (or has no library)."""
        # Never hide when there is no library — otherwise first-time users are stuck.
        if self._container.config.onboarding_tips_dismissed and snap.has_library:
            self._getting_started.setVisible(False)
            return

        steps: list[str] = []
        if not snap.has_library:
            steps.append(
                "1. Create folders — click Setup wizard (top of this page) for Incoming + Library."
            )
        else:
            steps.append("1. Library folders — done.")

        acq = self._container.config.acquisition
        download_on = acq.nicotine_plus.enabled or (
            acq.prowlarr.enabled
            and (acq.qbittorrent.enabled or acq.sabnzbd.enabled or nzbget_enabled(acq))
        )
        connected_ids = self._container.provider_manager.connected_provider_ids()
        if not download_on:
            steps.append(
                "2. Enable a download source: Settings → Wishlist & downloads (Nicotine+) "
                "or System → Plugins (Prowlarr, SABnzbd, or NZBGet)."
            )
        elif not has_connected_download_source(connected_ids):
            steps.append(
                "2. Start the enabled download client, then Test connection in Settings "
                "(Nicotine+) or Plugins (Prowlarr)."
            )
        else:
            names = [
                row.name
                for row in summarize_music_tools(
                    acquisition=acq,
                    metadata=self._container.config.metadata,
                    recommendations=self._container.config.recommendations,
                    connected_ids=connected_ids,
                )
                if row.state == "connected"
            ]
            steps.append(f"2. Download source connected — {', '.join(names)}.")

        if snap.track_count == 0:
            steps.append("3. Scan Incoming (or drop music into Incoming) to build the catalog.")
        else:
            steps.append(
                f"3. Catalog has {snap.track_count} track(s) — keep scanning as you add files."
            )

        if snap.acquisition.total == 0:
            steps.append("4. Find gaps — Find & get → Find music (Library gaps or Discogs browse).")
        else:
            steps.append(
                f"4. Wishlist has {snap.acquisition.active} active job(s) — "
                "watch Wishlist / Jobs."
            )

        steps.append(
            "Colors on Albums/Library: green = OK · orange = missing or below quality prefs."
        )
        self._getting_started_body.setText("\n".join(steps))
        self._getting_started.setVisible(True)

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

    def _refresh_music_tools(self) -> None:
        media_plugins: tuple[str, ...] = ()
        if self._library_id is not None:
            media_plugins = tuple(
                state.plugin_id
                for state in self._container.media_server_repo.list_by_library(self._library_id)
                if state.server_url
            )
        rows = summarize_music_tools(
            acquisition=self._container.config.acquisition,
            metadata=self._container.config.metadata,
            recommendations=self._container.config.recommendations,
            connected_ids=self._container.provider_manager.connected_provider_ids(),
            media_plugins=media_plugins,
            client_probes=self._client_probes,
        )
        for row in rows:
            key = row.short_name or row.name
            tile = self._status_tiles.get(key)
            if tile is None:
                tile = IntegrationStatusTile(row)
                tile.activated.connect(self.navigate_requested.emit)
                self._tools_host.flow().addWidget(tile)
                tile.show()
                self._status_tiles[key] = tile
            else:
                tile.apply_status(row)
        self._tools_host.flow().invalidate()
        self._tools_host.updateGeometry()

    def _drop_stale_client_probes(self) -> None:
        """Hide probe results that belong to different connection settings."""
        fingerprint = dashboard_probe_fingerprint(self._container.config.acquisition)
        if fingerprint != self._probe_applied_fingerprint:
            self._client_probes = None

    def _schedule_client_probes(self, *, force: bool) -> None:
        """Start one background probe. Skip duplicates; drop results after edits."""
        acquisition = self._container.config.acquisition
        fingerprint = dashboard_probe_fingerprint(acquisition)
        if self._probe_inflight:
            if force or fingerprint != self._probe_fingerprint:
                self._probe_token += 1
                self._probe_again = True
                self._probe_fingerprint = fingerprint
                self._client_probes = None
            return
        if (
            not force
            and fingerprint == self._probe_applied_fingerprint
            and self._client_probes is not None
        ):
            return
        self._start_client_probes(acquisition, fingerprint)

    def _start_client_probes(self, acquisition: AcquisitionConfig, fingerprint: str) -> None:
        self._probe_token += 1
        token = self._probe_token
        self._probe_inflight = True
        self._probe_again = False
        self._probe_fingerprint = fingerprint
        checks = self._container.connection_checks

        def work() -> dict[str, bool]:
            return checks.probe_dashboard_clients(acquisition)

        def finish(result: object) -> None:
            self._probe_inflight = False
            if not self._page_alive():
                return
            live = dashboard_probe_fingerprint(self._container.config.acquisition)
            stale = token != self._probe_token or live != fingerprint
            if stale:
                self._client_probes = None
                self._probe_applied_fingerprint = ""
                self._refresh_music_tools()
                if self._probe_again or live != fingerprint:
                    self._probe_again = False
                    self._schedule_client_probes(force=True)
                return
            self._client_probes = _probe_map(result)
            self._probe_applied_fingerprint = fingerprint
            self._refresh_music_tools()

        run_in_background(work, on_finished=finish, on_failed=lambda _message: finish(None))

    def _page_alive(self) -> bool:
        try:
            self.objectName()
        except RuntimeError:
            return False
        return True

    def _apply(self, snap: DashboardSnapshot) -> None:
        self._refresh_getting_started(snap)
        self._refresh_music_tools()
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
                self._kpi_missing,
                self._kpi_acq_active,
                self._kpi_acq_today,
                self._kpi_acq_total,
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
        self._kpi_pending.set_value(str(snap.pending_jobs))
        self._kpi_running.set_value(str(snap.running_jobs))
        self._kpi_failed.set_value(str(snap.failed_jobs))
        self._kpi_tracks.set_value(str(snap.track_count))
        self._kpi_done.set_value(str(snap.completed_today))
        self._kpi_review.set_value(str(snap.review_pending))
        gaps = snap.missing_media
        if gaps.scanned:
            self._kpi_missing.set_value(str(gaps.missing_tracks))
        else:
            self._kpi_missing.set_value("—")
        acq = snap.acquisition
        self._kpi_acq_active.set_value(str(acq.active))
        self._kpi_acq_today.set_value(str(acq.completed_today))
        self._kpi_acq_total.set_value(str(acq.completed))

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
        gaps = snap.missing_media
        acq = snap.acquisition
        lines: list[str] = []

        if not gaps.available:
            lines.append("Missing-track detection unavailable (MusicBrainz provider required).")
        elif not gaps.scanned:
            lines.append(
                "Missing tracks: not scanned yet — run Find music → Find missing songs "
                "(this checks MusicBrainz and can take a minute)."
            )
        elif gaps.albums_scanned == 0:
            lines.append(
                "No albums linked to MusicBrainz yet — identify albums first so gaps "
                "can be detected."
            )
        elif gaps.missing_tracks:
            lines.append(
                f"Detected: {gaps.missing_tracks} missing track(s) across "
                f"{gaps.incomplete_albums} incomplete album(s) "
                f"({gaps.complete_albums}/{gaps.albums_scanned} albums complete vs MusicBrainz)."
            )
        else:
            lines.append(
                f"All {gaps.albums_scanned} MusicBrainz-linked album(s) have expected tracks."
            )
        if gaps.scanned and gaps.scanned_at is not None:
            when = gaps.scanned_at.astimezone().strftime("%Y-%m-%d %H:%M")
            lines.append(f"Last missing-media scan: {when}")

        if acq.total == 0:
            if gaps.scanned and gaps.missing_tracks:
                lines.append(
                    "No wishlist jobs yet — open Find music → Find missing songs to queue "
                    "downloads."
                )
            elif gaps.available and gaps.albums_scanned:
                lines.append("No wishlist jobs — nothing missing to acquire.")
            else:
                lines.append(
                    "No wishlist jobs yet. Use Find music → Find missing songs after albums "
                    "are identified."
                )
        else:
            wishlist_parts = [
                f"{acq.total} wishlist job(s)",
                f"{acq.active} active",
                f"{acq.completed} acquired all-time",
            ]
            if acq.completed_today:
                wishlist_parts.append(f"{acq.completed_today} acquired today")
            if acq.queued:
                wishlist_parts.append(f"{acq.queued} queued")
            if acq.in_progress:
                wishlist_parts.append(f"{acq.in_progress} in progress")
            if acq.waiting_for_user:
                wishlist_parts.append(f"{acq.waiting_for_user} awaiting your pick")
            if acq.failed:
                wishlist_parts.append(f"{acq.failed} failed / no results")
            lines.append("Wishlist: " + " · ".join(wishlist_parts))

        self._acquisition_summary.setText("\n".join(lines))

    def _fill_jobs(self, table: QTableWidget, jobs: tuple[Job, ...], *, kind: str) -> None:
        table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            table.setItem(row, 0, QTableWidgetItem(job.job_type.value))
            if kind == "running":
                table.setItem(row, 1, QTableWidgetItem(str(job.attempt_count)))
                started = job.started_at.isoformat(timespec="seconds") if job.started_at else "—"
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

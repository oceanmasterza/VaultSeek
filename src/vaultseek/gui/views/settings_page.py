"""Settings page — library create/edit and app preferences."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid7

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.config import save_config
from vaultseek.core.container import Container
from vaultseek.gui.views.rules_page import RulesPage
from vaultseek.gui.widgets.desktop import open_path
from vaultseek.gui.widgets.path_picker import PathPickerRow
from vaultseek.gui.widgets.scrollable import wrap_scrollable
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.media_server_state import MediaServerState
from vaultseek.models.entities.track import LibraryZone
from vaultseek.services.acquisition_bootstrap import (
    connect_acquisition_providers,
    probe_nicotine_plus_connection,
)
from vaultseek.services.quality_presets import (
    PRESET_CHOICES,
    PRESET_CUSTOM,
    infer_preset,
    normalize_preset_id,
    values_for_preset,
)
from vaultseek.services.library_reset import reset_library_processing


class SettingsPage(QWidget):
    """Library zone paths plus light app-level preferences."""

    library_saved = Signal(object)
    preferences_saved = Signal(str)
    scan_requested = Signal()

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._editing_id: UUID | None = None
        self._suggest_siblings = True

        body = QWidget()
        wrap_scrollable(self, body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)
        heading = QLabel("Settings")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        lib_box = QGroupBox("Library")
        form = QFormLayout(lib_box)
        self._name = QLineEdit()
        self._name.setPlaceholderText("My Music")
        self._name.setToolTip("Display name for this library in the toolbar.")
        self._incoming = PathPickerRow(placeholder=r"e.g. D:\Music\Incoming")
        self._incoming.setToolTip(
            "Drop folder. Files stay here through identify/rules; they move to "
            "Library only after auto-approve or Review approval."
        )
        self._staging = PathPickerRow(placeholder=r"e.g. D:\Music\Staging")
        self._library = PathPickerRow(placeholder=r"e.g. D:\Music\Library")
        self._archive = PathPickerRow(placeholder=r"e.g. D:\Music\Archive")
        self._incoming.setToolTip("Drop zone for new files. Watched when enabled below.")
        self._staging.setToolTip(
            "Optional hold folder (legacy/manual). New files stay in Incoming "
            "until confirmed, then move straight to Library."
        )
        self._library.setToolTip("Canonical organized collection.")
        self._archive.setToolTip("Duplicates and rejected files.")
        self._watch = QCheckBox("Watch incoming folder")
        self._watch.setToolTip("Automatically enqueue a scan when new files appear.")
        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0.0, 1.0)
        self._threshold.setSingleStep(0.05)
        self._threshold.setValue(0.90)
        self._threshold.setToolTip("Metadata confidence at or above this value auto-approves.")
        form.addRow("Name", self._name)
        form.addRow("Incoming", self._incoming)
        form.addRow("Staging", self._staging)
        form.addRow("Library", self._library)
        form.addRow("Archive", self._archive)
        self._logs_path = PathPickerRow(show_browse=False, read_only=True, show_open=True)
        self._logs_path.setToolTip("Application log files (vaultseek.log, debug.log).")
        self._reports_path = PathPickerRow(show_browse=False, read_only=True, show_open=True)
        self._reports_path.setToolTip("Generated library/acquisition report files.")
        form.addRow("Logs", self._logs_path)
        form.addRow("Reports", self._reports_path)
        logs_actions = QHBoxLayout()
        open_debug = QPushButton("Open debug.log")
        open_app_log = QPushButton("Open vaultseek.log")
        open_crashes = QPushButton("Open crashes")
        for btn in (open_debug, open_app_log, open_crashes):
            btn.setProperty("secondary", True)
        open_debug.setToolTip(str(container.paths.logs_dir / "debug.log"))
        open_app_log.setToolTip(str(container.paths.logs_dir / "vaultseek.log"))
        open_crashes.setToolTip(str(container.paths.crashes_dir))
        open_debug.clicked.connect(
            lambda: open_path(self._container.paths.logs_dir / "debug.log")
        )
        open_app_log.clicked.connect(
            lambda: open_path(self._container.paths.logs_dir / "vaultseek.log")
        )
        open_crashes.clicked.connect(lambda: open_path(self._container.paths.crashes_dir))
        logs_actions.addWidget(open_debug)
        logs_actions.addWidget(open_app_log)
        logs_actions.addWidget(open_crashes)
        logs_actions.addStretch(1)
        form.addRow(logs_actions)
        form.addRow(self._watch)
        form.addRow("Auto-approve threshold", self._threshold)
        # Suggest sibling folders after the first zone is chosen.
        self._incoming.path_changed.connect(self._maybe_suggest_siblings)
        layout.addWidget(lib_box)

        lib_buttons = QHBoxLayout()
        save_lib = QPushButton("Save library")
        save_lib.setDefault(True)
        new_lib = QPushButton("New library")
        new_lib.setProperty("secondary", True)
        scan_btn = QPushButton("Scan incoming now")
        scan_btn.setProperty("secondary", True)
        scan_btn.setToolTip("Enqueue a scan of the Incoming folder for this library.")
        save_lib.clicked.connect(self._save_library)
        new_lib.clicked.connect(self._new_library)
        scan_btn.clicked.connect(self._scan_incoming)
        lib_buttons.addWidget(save_lib)
        lib_buttons.addWidget(new_lib)
        lib_buttons.addWidget(scan_btn)
        lib_buttons.addStretch(1)
        layout.addLayout(lib_buttons)

        reset_box = QGroupBox("Reset processing")
        reset_layout = QVBoxLayout(reset_box)
        reset_help = QLabel(
            "Start over without creating a new library. Zone paths and preferences "
            "are kept. Track totals on the Dashboard are cumulative — new scans add "
            "to them; use catalog clear only if you want those numbers to go back to zero."
        )
        reset_help.setWordWrap(True)
        reset_help.setProperty("muted", True)
        reset_layout.addWidget(reset_help)
        reset_btns = QHBoxLayout()
        clear_queues = QPushButton("Clear job & review queues")
        clear_queues.setProperty("secondary", True)
        clear_queues.setToolTip(
            "Delete pending/running/failed jobs and review items. Catalog tracks stay."
        )
        clear_catalog = QPushButton("Clear catalog records…")
        clear_catalog.setProperty("secondary", True)
        clear_catalog.setToolTip(
            "Also remove track rows from the database (files on disk are not deleted). "
            "Re-scan Incoming afterward to rebuild from files still in Incoming."
        )
        clear_queues.clicked.connect(self._reset_queues)
        clear_catalog.clicked.connect(self._reset_catalog)
        reset_btns.addWidget(clear_queues)
        reset_btns.addWidget(clear_catalog)
        reset_btns.addStretch(1)
        reset_layout.addLayout(reset_btns)
        layout.addWidget(reset_box)

        acq_box = QGroupBox("Acquisition")
        acq_form = QFormLayout(acq_box)
        self._acq_threshold = QDoubleSpinBox()
        self._acq_threshold.setRange(0.0, 1.0)
        self._acq_threshold.setSingleStep(0.05)
        self._acq_threshold.setValue(0.45)
        self._acq_threshold.setToolTip(
            "Minimum match score (0–1) to download automatically. "
            "Lower = more automatic downloads from Soulseek; higher = more manual approval."
        )
        self._auto_queue_jobs = QCheckBox("Auto-queue jobs created by Scan for missing")
        self._auto_queue_jobs.setToolTip(
            "When enabled, missing-media scan jobs are queued so background automation "
            "can search and download. When disabled, jobs stay Created until you "
            "Auto-acquire selected on the Acquisition page."
        )
        self._nicotine_enabled = QCheckBox("Enable Nicotine+ provider")
        self._nicotine_transport = QComboBox()
        self._nicotine_transport.addItem("VaultSeek NDJSON socket", "socket")
        self._nicotine_transport.addItem("HTTP (api-nicotine-plus)", "http")
        self._nicotine_host = QLineEdit("127.0.0.1")
        self._nicotine_port = QSpinBox()
        self._nicotine_port.setRange(1, 65535)
        self._nicotine_port.setValue(22024)
        self._nicotine_api_port = QSpinBox()
        self._nicotine_api_port.setRange(1024, 65535)
        self._nicotine_api_port.setValue(12339)
        self._nicotine_api_token = QLineEdit()
        self._nicotine_api_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._nicotine_api_token.setPlaceholderText("api-nicotine-plus token (optional)")
        self._nicotine_search_interval = QDoubleSpinBox()
        self._nicotine_search_interval.setRange(1.0, 120.0)
        self._nicotine_search_interval.setSingleStep(1.0)
        self._nicotine_search_interval.setDecimals(1)
        self._nicotine_search_interval.setSuffix(" s")
        self._nicotine_search_interval.setValue(5.0)
        self._nicotine_search_interval.setToolTip(
            "Minimum seconds between Soulseek searches. The network bans accounts "
            "that search too quickly (often ~30 minutes). Exact limits are unpublished; "
            "5 seconds is a conservative default."
        )
        self._nicotine_search_max_per_min = QSpinBox()
        self._nicotine_search_max_per_min.setRange(1, 30)
        self._nicotine_search_max_per_min.setValue(8)
        self._nicotine_search_max_per_min.setToolTip(
            "Hard cap on Soulseek searches in any rolling 60-second window."
        )
        acq_form.addRow("Auto-acquire threshold", self._acq_threshold)
        acq_form.addRow(self._auto_queue_jobs)
        self._quality_preset = QComboBox()
        for preset_id, label, tip in PRESET_CHOICES:
            self._quality_preset.addItem(label, preset_id)
            idx = self._quality_preset.count() - 1
            self._quality_preset.setItemData(idx, tip, Qt.ItemDataRole.ToolTipRole)
        self._quality_preset.setToolTip(
            "Named profiles for orange traffic lights and quality upgrades. "
            "Custom keeps your manual codec / bitrate values."
        )
        self._quality_preset_hint = QLabel("")
        self._quality_preset_hint.setProperty("muted", True)
        self._quality_preset_hint.setWordWrap(True)
        self._quality_applying = False
        self._prefer_lossless = QCheckBox("Prefer lossless (FLAC/ALAC) when available")
        self._prefer_lossless.setChecked(True)
        self._preferred_codec = QLineEdit()
        self._preferred_codec.setPlaceholderText("Optional exact codec, e.g. FLAC or MP3")
        self._min_bitrate = QSpinBox()
        self._min_bitrate.setRange(0, 3200)
        self._min_bitrate.setSingleStep(32)
        self._min_bitrate.setValue(192)
        self._min_bitrate.setSuffix(" kbps")
        self._min_bitrate.setToolTip(
            "Minimum acceptable bitrate for lossy files. Green = meets this; "
            "orange = present but below. 0 disables the bitrate floor."
        )
        self._download_whole_album = QCheckBox(
            "When upgrading, prefer matching whole-album folders from the same peer"
        )
        self._download_whole_album.setChecked(True)
        self._wishlist_hours = QDoubleSpinBox()
        self._wishlist_hours.setRange(0.0, 168.0)
        self._wishlist_hours.setSingleStep(1.0)
        self._wishlist_hours.setDecimals(1)
        self._wishlist_hours.setSuffix(" hours")
        self._wishlist_hours.setSpecialValueText("Continuous")
        self._wishlist_hours.setToolTip(
            "How often background wishlist searches run. 0 = as often as Soulseek "
            "rate limits allow. Example: 6 = at most one search pass every 6 hours."
        )
        acq_form.addRow("Quality preset", self._quality_preset)
        acq_form.addRow(self._quality_preset_hint)
        acq_form.addRow(self._prefer_lossless)
        acq_form.addRow("Preferred codec", self._preferred_codec)
        acq_form.addRow("Min bitrate (lossy)", self._min_bitrate)
        acq_form.addRow(self._download_whole_album)
        acq_form.addRow("Wishlist search every", self._wishlist_hours)
        self._quality_preset.currentIndexChanged.connect(self._on_quality_preset_changed)
        self._prefer_lossless.toggled.connect(self._on_quality_fields_edited)
        self._preferred_codec.textEdited.connect(self._on_quality_fields_edited)
        self._min_bitrate.valueChanged.connect(self._on_quality_fields_edited)
        acq_form.addRow(self._nicotine_enabled)
        acq_form.addRow("Nicotine+ transport", self._nicotine_transport)
        acq_form.addRow("Nicotine+ host", self._nicotine_host)
        acq_form.addRow("NDJSON port", self._nicotine_port)
        acq_form.addRow("HTTP API port", self._nicotine_api_port)
        acq_form.addRow("HTTP API token", self._nicotine_api_token)
        acq_form.addRow("Min seconds between searches", self._nicotine_search_interval)
        acq_form.addRow("Max searches per minute", self._nicotine_search_max_per_min)
        test_conn = QPushButton("Test Nicotine+ connection")
        test_conn.setProperty("secondary", True)
        test_conn.setToolTip(
            "Probe the current form values without saving. "
            "HTTP mode checks api-nicotine-plus; socket mode checks the NDJSON port."
        )
        test_conn.clicked.connect(self._test_nicotine_connection)
        acq_form.addRow(test_conn)
        acq_help = QLabel(
            "HTTP mode talks to the community api-nicotine-plus plugin inside Nicotine+. "
            "Socket mode expects a VaultSeek NDJSON companion on the NDJSON port. "
            "Completed downloads are copied into Incoming, then organized into your Music folder. "
            "Restart VaultSeek after saving acquisition settings. "
            "Enable Nicotine+ (and keep it connected) or searches return no results. "
            "Search rate limits protect against Soulseek's automatic 30-minute flood ban."
        )
        acq_help.setWordWrap(True)
        acq_help.setProperty("muted", True)
        acq_form.addRow(acq_help)
        layout.addWidget(acq_box)

        prefs = QGroupBox("Application")
        prefs_form = QFormLayout(prefs)
        self._log_level = QComboBox()
        self._log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._theme = QComboBox()
        self._theme.addItems(["dark", "light"])
        self._discogs_token = QLineEdit()
        self._discogs_token.setPlaceholderText("Paste Discogs personal access token")
        self._discogs_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._discogs_token.setToolTip(
            "Used for Discogs metadata (genre, label, catalog) and cover art. "
            "Create a token at https://www.discogs.com/settings/developers. Restart after saving."
        )
        prefs_form.addRow("Log level", self._log_level)
        prefs_form.addRow("Theme", self._theme)
        prefs_form.addRow("Discogs token", self._discogs_token)
        discogs_help = QLabel(
            "Optional. Improves identification with genre/label/catalog and Discogs covers. "
            "Token: https://www.discogs.com/settings/developers"
        )
        discogs_help.setWordWrap(True)
        discogs_help.setProperty("muted", True)
        discogs_help.setOpenExternalLinks(True)
        prefs_form.addRow(discogs_help)
        self._acoustid_rows: list[tuple[QLineEdit, QLineEdit, QLineEdit]] = []
        acoustid_box = QGroupBox("AcoustID accounts (fingerprint lookups)")
        acoustid_form = QFormLayout(acoustid_box)
        for index in range(3):
            label = QLineEdit()
            label.setPlaceholderText(f"Account {index + 1}")
            key = QLineEdit()
            key.setPlaceholderText("Application API key")
            key.setEchoMode(QLineEdit.EchoMode.Password)
            proxy = QLineEdit()
            proxy.setPlaceholderText("http://user:pass@host:port (optional)")
            proxy.setToolTip(
                "HTTP(S) proxy for this AcoustID key. Use a different proxy per account "
                "so each gets its own 3 requests/sec limit."
            )
            self._acoustid_rows.append((label, key, proxy))
            acoustid_form.addRow(f"Label {index + 1}", label)
            acoustid_form.addRow(f"API key {index + 1}", key)
            acoustid_form.addRow(f"Proxy {index + 1}", proxy)
        acoustid_help = QLabel(
            "Each AcoustID application key allows ~3 fingerprint lookups/sec (per key + IP). "
            "Add up to 3 keys with separate proxies for ~9/sec combined. "
            "Register keys at https://acoustid.org/new-applications. Restart after saving."
        )
        acoustid_help.setWordWrap(True)
        acoustid_help.setProperty("muted", True)
        acoustid_help.setOpenExternalLinks(True)
        acoustid_form.addRow(acoustid_help)
        prefs_form.addRow(acoustid_box)

        self._fingerprint_mode = QComboBox()
        self._fingerprint_mode.addItem("Fingerprint every song", "all")
        self._fingerprint_mode.addItem("Sample album folders (faster)", "sample")
        self._fingerprint_mode.setToolTip(
            "Sampling fingerprints a few songs per album folder, then trusts the "
            "rest when tags, filenames, and track count match the official release."
        )
        self._fingerprint_sample_min = QSpinBox()
        self._fingerprint_sample_min.setRange(1, 20)
        self._fingerprint_sample_min.setValue(3)
        self._fingerprint_sample_min.setToolTip(
            "Minimum AcoustID-confirmed songs in a folder before the rest can skip fingerprinting."
        )
        self._fingerprint_mode.currentIndexChanged.connect(self._sync_fingerprint_sample_enabled)
        prefs_form.addRow("Fingerprinting", self._fingerprint_mode)
        prefs_form.addRow("Sample size (min confirmed)", self._fingerprint_sample_min)
        fingerprint_help = QLabel(
            "Sample mode only skips remaining songs in a folder after all four are true: "
            "(1) at least N songs fingerprinted to the same album, "
            "(2) every file’s tags match the official tracklist, "
            "(3) filenames look correct, "
            "(4) file count matches the official track count. "
            "Requires an AcoustID API key. Restart VaultSeek after changing these settings."
        )
        fingerprint_help.setWordWrap(True)
        fingerprint_help.setProperty("muted", True)
        prefs_form.addRow(fingerprint_help)

        prefs_actions = QHBoxLayout()
        save_prefs = QPushButton("Save preferences")
        open_logs = QPushButton("Open log folder")
        open_data = QPushButton("Open data folder")
        open_logs.setProperty("secondary", True)
        open_data.setProperty("secondary", True)
        open_logs.setToolTip(str(container.paths.logs_dir))
        open_data.setToolTip(str(container.paths.root))
        save_prefs.clicked.connect(self._save_preferences)
        open_logs.clicked.connect(lambda: open_path(self._container.paths.logs_dir))
        open_data.clicked.connect(lambda: open_path(self._container.paths.root))
        prefs_actions.addWidget(save_prefs)
        prefs_actions.addWidget(open_logs)
        prefs_actions.addWidget(open_data)
        prefs_actions.addStretch(1)
        prefs_form.addRow(prefs_actions)
        layout.addWidget(prefs)

        media = QGroupBox("Media servers")
        media_form = QFormLayout(media)
        self._ms_plugin = QComboBox()
        self._ms_plugin.addItems(
            [
                "navidrome",
                "jellyfin",
                "emby",
                "plex",
                "subsonic",
                "ampache",
                "koel",
                "funkwhale",
                "lyrion",
            ]
        )
        self._ms_url = QLineEdit()
        self._ms_url.setPlaceholderText("https://navidrome.example:4533")
        self._ms_username = QLineEdit()
        self._ms_password = QLineEdit()
        self._ms_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._ms_token = QLineEdit()
        self._ms_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._ms_db_path = PathPickerRow(
            mode="file",
            placeholder=r"e.g. C:\navidrome\navidrome.db",
            file_filter="SQLite database (*.db *.sqlite *.sqlite3);;All files (*.*)",
        )
        media_form.addRow("Plugin", self._ms_plugin)
        media_form.addRow("Server URL", self._ms_url)
        media_form.addRow("Username", self._ms_username)
        media_form.addRow("Password", self._ms_password)
        media_form.addRow("Token (Jellyfin/Plex)", self._ms_token)
        media_form.addRow("Navidrome DB path", self._ms_db_path)
        save_ms = QPushButton("Save media server")
        save_ms.clicked.connect(self._save_media_server)
        media_form.addRow(save_ms)
        self._ms_status = QLabel("")
        media_form.addRow(self._ms_status)
        layout.addWidget(media)
        self._ms_plugin.currentTextChanged.connect(self._load_media_server_form)

        self._rules_page = RulesPage(container)
        layout.addWidget(self._rules_page)

        layout.addStretch(1)

    def set_library(self, library_id: UUID | None) -> None:
        self._editing_id = library_id
        self._rules_page.set_library(library_id)
        self.refresh()

    def refresh(self) -> None:
        config = self._container.config
        self._logs_path.setText(str(self._container.paths.logs_dir))
        self._reports_path.setText(str(self._container.paths.reports_dir))
        self._rules_page.refresh()
        self._log_level.setCurrentText(config.log_level)
        self._theme.setCurrentText(config.theme)
        self._discogs_token.setText(config.metadata.discogs_user_token or "")
        from vaultseek.core.config import AcoustIdEndpointConfig

        endpoints = list(config.metadata.acoustid_endpoints)
        if not endpoints and config.metadata.acoustid_api_key:
            endpoints = [
                AcoustIdEndpointConfig(
                    api_key=config.metadata.acoustid_api_key,
                    label="Primary",
                )
            ]
        while len(endpoints) < 3:
            endpoints.append(AcoustIdEndpointConfig())
        for row, endpoint in zip(self._acoustid_rows, endpoints[:3], strict=True):
            label_edit, key_edit, proxy_edit = row
            label_edit.setText(endpoint.label)
            key_edit.setText(endpoint.api_key)
            proxy_edit.setText(endpoint.proxy_url)
        mode_index = self._fingerprint_mode.findData(config.metadata.fingerprint_mode)
        self._fingerprint_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        self._fingerprint_sample_min.setValue(config.metadata.fingerprint_sample_min)
        self._sync_fingerprint_sample_enabled()
        self._acq_threshold.setValue(config.acquisition.auto_acquire_threshold)
        self._auto_queue_jobs.setChecked(config.acquisition.auto_queue_jobs)
        self._set_quality_preset_combo(
            normalize_preset_id(getattr(config.acquisition, "quality_preset", PRESET_CUSTOM))
        )
        self._prefer_lossless.setChecked(config.acquisition.prefer_lossless)
        self._preferred_codec.setText(config.acquisition.preferred_codec or "")
        self._min_bitrate.setValue(int(config.acquisition.min_bitrate_kbps))
        self._update_quality_preset_hint()
        self._download_whole_album.setChecked(config.acquisition.download_whole_album_on_upgrade)
        self._wishlist_hours.setValue(float(config.acquisition.wishlist_search_interval_hours))
        nicotine = config.acquisition.nicotine_plus
        self._nicotine_enabled.setChecked(nicotine.enabled)
        transport_index = self._nicotine_transport.findData(nicotine.transport)
        self._nicotine_transport.setCurrentIndex(transport_index if transport_index >= 0 else 0)
        self._nicotine_host.setText(nicotine.host)
        self._nicotine_port.setValue(nicotine.port)
        self._nicotine_api_port.setValue(nicotine.api_port)
        self._nicotine_api_token.setText(nicotine.api_token)
        self._nicotine_search_interval.setValue(float(nicotine.search_min_interval_seconds))
        self._nicotine_search_max_per_min.setValue(int(nicotine.search_max_per_minute))

        if self._editing_id is None:
            self._clear_library_form()
            self._clear_media_server_form()
            return
        library = self._container.library_repo.get(self._editing_id)
        if library is None:
            self._clear_library_form()
            self._clear_media_server_form()
            return
        self._name.setText(library.name)
        self._suggest_siblings = False
        try:
            self._incoming.setText(library.incoming_path)
            self._staging.setText(library.staging_path)
            self._library.setText(library.library_path)
            self._archive.setText(library.archive_path)
        finally:
            self._suggest_siblings = True
        self._watch.setChecked(library.watch_enabled)
        self._threshold.setValue(library.auto_approve_threshold)
        self._load_media_server_form()

    def _clear_library_form(self) -> None:
        self._name.clear()
        self._suggest_siblings = False
        try:
            self._incoming.clear()
            self._staging.clear()
            self._library.clear()
            self._archive.clear()
        finally:
            self._suggest_siblings = True
        self._watch.setChecked(False)
        self._threshold.setValue(0.90)

    def _clear_media_server_form(self) -> None:
        self._ms_url.clear()
        self._ms_username.clear()
        self._ms_password.clear()
        self._ms_token.clear()
        self._ms_db_path.clear()
        self._ms_status.setText("")

    def _maybe_suggest_siblings(self, incoming_text: str) -> None:
        """When Incoming is set and other zones are empty, fill sibling folders."""
        if not self._suggest_siblings:
            return
        incoming = incoming_text.strip()
        if not incoming:
            return
        if self._staging.text() or self._library.text() or self._archive.text():
            return
        parent = Path(incoming).expanduser().resolve().parent
        self._staging.setText(str(parent / "Staging"))
        self._library.setText(str(parent / "Library"))
        self._archive.setText(str(parent / "Archive"))

    def _load_media_server_form(self, _plugin: str = "") -> None:
        self._clear_media_server_form()
        if self._editing_id is None:
            return
        plugin_id = self._ms_plugin.currentText()
        for row in self._container.media_server_repo.list_by_library(self._editing_id):
            if row.plugin_id != plugin_id:
                continue
            self._ms_url.setText(row.server_url or "")
            cfg = row.config or {}
            self._ms_username.setText(str(cfg.get("username", "")))
            self._ms_password.setText(str(cfg.get("password", "")))
            self._ms_token.setText(str(cfg.get("token", "")))
            self._ms_db_path.setText(row.db_path or "")
            status = row.last_sync_status or "never"
            when = row.last_sync_at.isoformat(timespec="seconds") if row.last_sync_at else "—"
            self._ms_status.setText(f"Last sync: {status} ({when})")
            return

    def _new_library(self) -> None:
        self._editing_id = None
        self._clear_library_form()

    def _scan_incoming(self) -> None:
        if self._editing_id is None:
            QMessageBox.warning(self, "Settings", "Save a library first.")
            return
        library = self._container.library_repo.get(self._editing_id)
        if library is None:
            QMessageBox.warning(self, "Settings", "Library not found.")
            return
        stats = self._container.job_queue.get_stats(library.id)
        if stats.by_type.get(JobType.SCAN_DIRECTORY.value, 0) > 0:
            QMessageBox.information(
                self,
                "Settings",
                "A scan is already pending or running for this library.",
            )
            return
        self._container.job_queue.enqueue(
            JobType.SCAN_DIRECTORY,
            library.id,
            {
                "directory": library.incoming_path,
                "zone": LibraryZone.INCOMING.value,
            },
        )
        QMessageBox.information(
            self,
            "Settings",
            f"Scan queued for:\n{library.incoming_path}",
        )
        self.scan_requested.emit()

    def _reset_queues(self) -> None:
        if self._editing_id is None:
            QMessageBox.warning(self, "Settings", "Save a library first.")
            return
        answer = QMessageBox.question(
            self,
            "Clear queues",
            "Delete all jobs and review items for this library?\n\n"
            "Catalog tracks and files on disk are kept.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = reset_library_processing(
            self._container.engine, self._editing_id, clear_catalog=False
        )
        QMessageBox.information(
            self,
            "Queues cleared",
            f"Removed {result.jobs_deleted} job(s) and "
            f"{result.reviews_deleted} review item(s).",
        )

    def _reset_catalog(self) -> None:
        if self._editing_id is None:
            QMessageBox.warning(self, "Settings", "Save a library first.")
            return
        answer = QMessageBox.warning(
            self,
            "Clear catalog records",
            "This removes track records, jobs, and reviews for this library "
            "from the database.\n\n"
            "Audio files on disk are NOT deleted, but Dashboard totals reset to zero. "
            "Files already moved out of Incoming will not reappear until you put them "
            "back in Incoming and scan again.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = reset_library_processing(
            self._container.engine, self._editing_id, clear_catalog=True
        )
        QMessageBox.information(
            self,
            "Catalog cleared",
            f"Removed {result.tracks_deleted} track(s), {result.jobs_deleted} job(s), "
            f"{result.reviews_deleted} review(s), and "
            f"{result.duplicate_groups_deleted} duplicate group(s).\n\n"
            "Scan Incoming when you are ready to start again.",
        )

    def _save_library(self) -> None:
        name = self._name.text().strip()
        incoming = self._incoming.text()
        staging = self._staging.text()
        library_path = self._library.text()
        archive = self._archive.text()
        if not name or not incoming or not staging or not library_path or not archive:
            QMessageBox.warning(self, "Settings", "Name and all four zone paths are required.")
            return

        for label, path in (
            ("Incoming", incoming),
            ("Staging", staging),
            ("Library", library_path),
            ("Archive", archive),
        ):
            candidate = Path(path)
            if candidate.exists() and not candidate.is_dir():
                QMessageBox.warning(
                    self,
                    "Settings",
                    f"{label} path exists but is not a folder:\n{path}",
                )
                return

        now = datetime.now(UTC)
        library_id = self._editing_id
        created_at = now
        if library_id is not None:
            existing = self._container.library_repo.get(library_id)
            if existing is not None:
                created_at = existing.created_at
        else:
            library_id = uuid7()

        try:
            for path in (incoming, staging, library_path, archive):
                Path(path).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Settings", f"Could not create folders:\n{exc}")
            return

        library = Library(
            id=library_id,
            name=name,
            incoming_path=incoming,
            staging_path=staging,
            library_path=library_path,
            archive_path=archive,
            created_at=created_at,
            updated_at=now,
            watch_enabled=self._watch.isChecked(),
            auto_approve_threshold=self._threshold.value(),
        )
        self._container.library_repo.upsert(library)
        self._editing_id = library.id
        QMessageBox.information(self, "Settings", f"Library “{name}” saved.")
        self.library_saved.emit(library.id)

    def _sync_fingerprint_sample_enabled(self) -> None:
        sample = self._fingerprint_mode.currentData() == "sample"
        self._fingerprint_sample_min.setEnabled(sample)

    def _set_quality_preset_combo(self, preset_id: str) -> None:
        key = normalize_preset_id(preset_id)
        index = self._quality_preset.findData(key)
        self._quality_applying = True
        self._quality_preset.setCurrentIndex(index if index >= 0 else self._quality_preset.findData(PRESET_CUSTOM))
        self._quality_applying = False
        self._update_quality_preset_hint()

    def _update_quality_preset_hint(self) -> None:
        tip = ""
        for preset_id, _label, description in PRESET_CHOICES:
            if preset_id == self._quality_preset.currentData():
                tip = description
                break
        self._quality_preset_hint.setText(tip)

    def _on_quality_preset_changed(self, _index: int = 0) -> None:
        if self._quality_applying:
            return
        values = values_for_preset(str(self._quality_preset.currentData() or PRESET_CUSTOM))
        self._update_quality_preset_hint()
        if values is None:
            return
        self._quality_applying = True
        self._prefer_lossless.setChecked(values.prefer_lossless)
        self._preferred_codec.setText(values.preferred_codec)
        self._min_bitrate.setValue(values.min_bitrate_kbps)
        self._quality_applying = False

    def _on_quality_fields_edited(self, *_args: object) -> None:
        if self._quality_applying:
            return
        matched = infer_preset(
            prefer_lossless=self._prefer_lossless.isChecked(),
            preferred_codec=self._preferred_codec.text().strip(),
            min_bitrate_kbps=int(self._min_bitrate.value()),
        )
        if self._quality_preset.currentData() != matched:
            self._set_quality_preset_combo(matched)

    def _save_preferences(self) -> None:
        from dataclasses import replace as dc_replace

        from vaultseek.core.config import AcquisitionConfig, AcoustIdEndpointConfig, NicotinePlusConfig

        endpoint_rows: list[AcoustIdEndpointConfig] = []
        for index, (label_edit, key_edit, proxy_edit) in enumerate(self._acoustid_rows, start=1):
            api_key = key_edit.text().strip()
            if not api_key:
                continue
            endpoint_rows.append(
                AcoustIdEndpointConfig(
                    api_key=api_key,
                    proxy_url=proxy_edit.text().strip(),
                    label=label_edit.text().strip() or f"Account {index}",
                )
            )
        primary_key = endpoint_rows[0].api_key if endpoint_rows else ""

        enabled = list(self._container.config.acquisition.enabled_providers)
        if self._nicotine_enabled.isChecked():
            if "nicotine_plus" not in enabled:
                enabled.append("nicotine_plus")
            enabled = [provider_id for provider_id in enabled if provider_id != "stub"]
        else:
            enabled = [provider_id for provider_id in enabled if provider_id != "nicotine_plus"]
        if not enabled:
            enabled = ["stub"]

        metadata = dc_replace(
            self._container.config.metadata,
            acoustid_api_key=primary_key,
            acoustid_endpoints=tuple(endpoint_rows),
            discogs_user_token=self._discogs_token.text().strip(),
            fingerprint_mode=str(self._fingerprint_mode.currentData() or "all"),
            fingerprint_sample_min=int(self._fingerprint_sample_min.value()),
        )
        # Keep discogs in provider lists when a token is present.
        meta_enabled = list(metadata.enabled_providers)
        meta_order = list(metadata.provider_order)
        if metadata.discogs_user_token:
            if "discogs" not in meta_enabled:
                if "musicbrainz" in meta_enabled:
                    meta_enabled.insert(meta_enabled.index("musicbrainz") + 1, "discogs")
                else:
                    meta_enabled.append("discogs")
            if "discogs" not in meta_order:
                if "musicbrainz" in meta_order:
                    meta_order.insert(meta_order.index("musicbrainz") + 1, "discogs")
                else:
                    meta_order.append("discogs")
        metadata = dc_replace(
            metadata,
            enabled_providers=tuple(meta_enabled),
            provider_order=tuple(meta_order),
        )
        acquisition = AcquisitionConfig(
            enabled_providers=tuple(dict.fromkeys(enabled)),
            provider_order=self._container.config.acquisition.provider_order,
            search_timeout_seconds=self._container.config.acquisition.search_timeout_seconds,
            auto_queue_jobs=self._auto_queue_jobs.isChecked(),
            auto_acquire_threshold=float(self._acq_threshold.value()),
            prefer_lossless=self._prefer_lossless.isChecked(),
            preferred_codec=self._preferred_codec.text().strip(),
            min_bitrate_kbps=int(self._min_bitrate.value()),
            quality_preset=normalize_preset_id(self._quality_preset.currentData()),
            download_whole_album_on_upgrade=self._download_whole_album.isChecked(),
            wishlist_search_interval_hours=float(self._wishlist_hours.value()),
            nicotine_plus=NicotinePlusConfig(
                enabled=self._nicotine_enabled.isChecked(),
                host=self._nicotine_host.text().strip() or "127.0.0.1",
                port=int(self._nicotine_port.value()),
                transport=str(self._nicotine_transport.currentData() or "socket"),
                api_port=int(self._nicotine_api_port.value()),
                api_token=self._nicotine_api_token.text().strip(),
                search_min_interval_seconds=float(self._nicotine_search_interval.value()),
                search_max_per_minute=int(self._nicotine_search_max_per_min.value()),
            ),
        )
        updated = replace(
            self._container.config,
            log_level=self._log_level.currentText(),
            theme=self._theme.currentText(),
            metadata=metadata,
            acquisition=acquisition,
        )
        save_config(updated, self._container.paths.config_file)
        self._container.config = updated
        connect_acquisition_providers(acquisition, self._container.provider_manager)
        self._container.acquisition_runner.set_auto_acquire_threshold(
            acquisition.auto_acquire_threshold
        )
        self._container.acquisition_automation_service.set_acquisition_config(acquisition)
        self.preferences_saved.emit(updated.theme)
        QMessageBox.information(
            self,
            "Settings",
            "Preferences saved. Restart VaultSeek so Discogs, fingerprinting, and AcoustID "
            "settings take effect.",
        )

    def _test_nicotine_connection(self) -> None:
        result = probe_nicotine_plus_connection(
            host=self._nicotine_host.text().strip() or "127.0.0.1",
            port=int(self._nicotine_port.value()),
            transport=str(self._nicotine_transport.currentData() or "socket"),
            api_port=int(self._nicotine_api_port.value()),
            api_token=self._nicotine_api_token.text().strip(),
        )
        if result.ok:
            QMessageBox.information(self, "Nicotine+ connection", result.message)
        else:
            QMessageBox.warning(self, "Nicotine+ connection", result.message)

    def _save_media_server(self) -> None:
        if self._editing_id is None:
            QMessageBox.warning(self, "Settings", "Save a library first.")
            return
        url = self._ms_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Settings", "Server URL is required.")
            return
        plugin_id = self._ms_plugin.currentText()
        config = {
            "username": self._ms_username.text(),
            "password": self._ms_password.text(),
            "token": self._ms_token.text(),
        }
        db_path = self._ms_db_path.text() or None
        existing = [
            row
            for row in self._container.media_server_repo.list_by_library(self._editing_id)
            if row.plugin_id == plugin_id
        ]
        prior = existing[0] if existing else None
        state_id = prior.id if prior is not None else uuid7()
        self._container.media_server_repo.upsert(
            MediaServerState(
                id=state_id,
                library_id=self._editing_id,
                plugin_id=plugin_id,
                server_url=url,
                db_path=db_path,
                config=config,
                last_sync_at=prior.last_sync_at if prior is not None else None,
                last_sync_status=prior.last_sync_status if prior is not None else None,
            )
        )
        self._load_media_server_form()
        QMessageBox.information(self, "Settings", f"Media server “{plugin_id}” saved.")

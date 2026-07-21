"""Settings page — library create/edit and app preferences."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid7

from PySide6.QtCore import Signal
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
        self._acq_threshold.setValue(0.90)
        self._acq_threshold.setToolTip(
            "Search results at or above this score auto-download during Auto-acquire."
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
        acq_form.addRow("Auto-acquire threshold", self._acq_threshold)
        acq_form.addRow(self._nicotine_enabled)
        acq_form.addRow("Nicotine+ transport", self._nicotine_transport)
        acq_form.addRow("Nicotine+ host", self._nicotine_host)
        acq_form.addRow("NDJSON port", self._nicotine_port)
        acq_form.addRow("HTTP API port", self._nicotine_api_port)
        acq_form.addRow("HTTP API token", self._nicotine_api_token)
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
            "Restart VaultSeek after saving acquisition settings."
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
        self._acoustid_key = QLineEdit()
        self._acoustid_key.setPlaceholderText("Paste AcoustID application key")
        self._acoustid_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._acoustid_key.setToolTip(
            "Required only for tracks that tags/MusicBrainz cannot identify. "
            "Lookups are rate-limited to 3/sec. Register at "
            "https://acoustid.org/new-applications (application key, not user key). "
            "Restart VaultSeek after saving."
        )
        prefs_form.addRow("Log level", self._log_level)
        prefs_form.addRow("Theme", self._theme)
        prefs_form.addRow("AcoustID API key", self._acoustid_key)
        acoustid_help = QLabel(
            "Most tagged files use embedded tags + MusicBrainz only. AcoustID "
            "(fingerprint) runs only when that is not enough, at most 3 requests/sec. "
            "Key: https://acoustid.org/new-applications"
        )
        acoustid_help.setWordWrap(True)
        acoustid_help.setProperty("muted", True)
        acoustid_help.setOpenExternalLinks(True)
        prefs_form.addRow(acoustid_help)

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

        layout.addStretch(1)

    def set_library(self, library_id: UUID | None) -> None:
        self._editing_id = library_id
        self.refresh()

    def refresh(self) -> None:
        config = self._container.config
        self._log_level.setCurrentText(config.log_level)
        self._theme.setCurrentText(config.theme)
        self._acoustid_key.setText(config.metadata.acoustid_api_key or "")
        mode_index = self._fingerprint_mode.findData(config.metadata.fingerprint_mode)
        self._fingerprint_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        self._fingerprint_sample_min.setValue(config.metadata.fingerprint_sample_min)
        self._sync_fingerprint_sample_enabled()
        self._acq_threshold.setValue(config.acquisition.auto_acquire_threshold)
        nicotine = config.acquisition.nicotine_plus
        self._nicotine_enabled.setChecked(nicotine.enabled)
        transport_index = self._nicotine_transport.findData(nicotine.transport)
        self._nicotine_transport.setCurrentIndex(transport_index if transport_index >= 0 else 0)
        self._nicotine_host.setText(nicotine.host)
        self._nicotine_port.setValue(nicotine.port)
        self._nicotine_api_port.setValue(nicotine.api_port)
        self._nicotine_api_token.setText(nicotine.api_token)

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

    def _save_preferences(self) -> None:
        from dataclasses import replace as dc_replace

        from vaultseek.core.config import AcquisitionConfig, NicotinePlusConfig

        metadata = dc_replace(
            self._container.config.metadata,
            acoustid_api_key=self._acoustid_key.text().strip(),
            fingerprint_mode=str(self._fingerprint_mode.currentData() or "all"),
            fingerprint_sample_min=int(self._fingerprint_sample_min.value()),
        )
        acquisition = AcquisitionConfig(
            enabled_providers=self._container.config.acquisition.enabled_providers,
            provider_order=self._container.config.acquisition.provider_order,
            search_timeout_seconds=self._container.config.acquisition.search_timeout_seconds,
            auto_queue_jobs=self._container.config.acquisition.auto_queue_jobs,
            auto_acquire_threshold=float(self._acq_threshold.value()),
            nicotine_plus=NicotinePlusConfig(
                enabled=self._nicotine_enabled.isChecked(),
                host=self._nicotine_host.text().strip() or "127.0.0.1",
                port=int(self._nicotine_port.value()),
                transport=str(self._nicotine_transport.currentData() or "socket"),
                api_port=int(self._nicotine_api_port.value()),
                api_token=self._nicotine_api_token.text().strip(),
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
        self.preferences_saved.emit(updated.theme)
        QMessageBox.information(
            self,
            "Settings",
            "Preferences saved. Restart VaultSeek so fingerprinting and AcoustID "
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

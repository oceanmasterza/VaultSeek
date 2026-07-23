"""First-run setup wizard — walks a new user through the minimum to start.

Inspired by Lidarr’s “add root folder” and Picard’s guided tagging flow:
ask for folders first, then optional download/identity services, then one
clear next action (scan Incoming). Existing functionality stays in Settings;
this wizard only sequences the same fields for first-time clarity.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid7

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from vaultseek.core.config import (
    AcquisitionConfig,
    NicotinePlusConfig,
    save_config,
)
from vaultseek.core.container import Container
from vaultseek.gui.widgets.path_picker import PathPickerRow
from vaultseek.models.entities.library import Library
from vaultseek.services.acquisition_bootstrap import (
    connect_acquisition_providers,
    probe_nicotine_plus_connection,
)


class SetupWizard(QWizard):
    """Modal guided setup. Emits ``finished_setup`` with the library id when done."""

    finished_setup = Signal(object)  # UUID | None

    def __init__(self, container: Container, parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self.setWindowTitle("VaultSeek setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumWidth(640)
        self.setMinimumHeight(480)

        self._welcome = _WelcomePage()
        self._folders = _FoldersPage()
        self._nicotine = _NicotinePage()
        self._tokens = _TokensPage(container)
        self._quality = _QualityPage()
        self._done = _DonePage()

        self.addPage(self._welcome)
        self.addPage(self._folders)
        self.addPage(self._nicotine)
        self.addPage(self._tokens)
        self.addPage(self._quality)
        self.addPage(self._done)

        self.finished.connect(self._on_finished)

    def _on_finished(self, result: int) -> None:
        if result != QWizard.DialogCode.Accepted:
            self.finished_setup.emit(None)
            return
        try:
            library_id = self._persist()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Setup", str(exc))
            self.finished_setup.emit(None)
            return
        self.finished_setup.emit(library_id)

    def _persist(self) -> UUID:
        """Create/update library + write config from wizard fields."""
        name = self._folders.name_edit.text().strip() or "My Music"
        incoming = self._folders.incoming.text().strip()
        library_path = self._folders.library.text().strip()
        staging = self._folders.staging.text().strip() or str(Path(incoming).parent / "Staging")
        archive = self._folders.archive.text().strip() or str(Path(incoming).parent / "Archive")
        if not incoming or not library_path:
            raise ValueError("Incoming and Library folders are required.")

        for path in (incoming, staging, library_path, archive):
            Path(path).mkdir(parents=True, exist_ok=True)

        now = datetime.now(UTC)
        existing = self._container.library_repo.list_all()
        if existing:
            library = existing[0]
            updated = replace(
                library,
                name=name,
                incoming_path=incoming,
                staging_path=staging,
                library_path=library_path,
                archive_path=archive,
                watch_enabled=self._folders.watch.isChecked(),
                updated_at=now,
            )
            self._container.library_repo.upsert(updated)
            library_id = library.id
        else:
            library_id = uuid7()
            library = Library(
                id=library_id,
                name=name,
                incoming_path=incoming,
                staging_path=staging,
                library_path=library_path,
                archive_path=archive,
                watch_enabled=self._folders.watch.isChecked(),
                auto_approve_threshold=0.90,
                created_at=now,
                updated_at=now,
            )
            self._container.library_repo.upsert(library)

        # Merge Nicotine + quality + optional tokens into app config.
        nicotine = NicotinePlusConfig(
            enabled=self._nicotine.enabled.isChecked(),
            host=self._nicotine.host.text().strip() or "127.0.0.1",
            port=22024,
            transport="http",
            api_port=int(self._nicotine.api_port.value()),
            api_token=self._nicotine.api_token.text().strip(),
            search_min_interval_seconds=(
                self._container.config.acquisition.nicotine_plus.search_min_interval_seconds
            ),
            search_max_per_minute=(
                self._container.config.acquisition.nicotine_plus.search_max_per_minute
            ),
        )
        enabled = list(self._container.config.acquisition.enabled_providers)
        if nicotine.enabled:
            if "nicotine_plus" not in enabled:
                enabled.append("nicotine_plus")
            enabled = [p for p in enabled if p != "stub"]
        if not enabled:
            enabled = ["stub"]

        acquisition = AcquisitionConfig(
            enabled_providers=tuple(dict.fromkeys(enabled)),
            provider_order=self._container.config.acquisition.provider_order,
            search_timeout_seconds=self._container.config.acquisition.search_timeout_seconds,
            auto_queue_jobs=True,
            auto_acquire_threshold=self._container.config.acquisition.auto_acquire_threshold,
            prefer_lossless=self._quality.prefer_lossless.isChecked(),
            preferred_codec=self._container.config.acquisition.preferred_codec,
            min_bitrate_kbps=int(self._quality.min_bitrate.value()),
            download_whole_album_on_upgrade=(
                self._container.config.acquisition.download_whole_album_on_upgrade
            ),
            wishlist_search_interval_hours=(
                self._container.config.acquisition.wishlist_search_interval_hours
            ),
            nicotine_plus=nicotine,
        )
        metadata = replace(
            self._container.config.metadata,
            discogs_user_token=self._tokens.discogs.text().strip(),
            acoustid_api_key=self._tokens.acoustid.text().strip()
            or self._container.config.metadata.acoustid_api_key,
        )
        updated_config = replace(
            self._container.config,
            setup_completed=True,
            onboarding_tips_dismissed=False,
            acquisition=acquisition,
            metadata=metadata,
        )
        save_config(updated_config, self._container.paths.config_file)
        self._container.config = updated_config
        self._container.acquisition_automation_service.set_acquisition_config(acquisition)
        connect_acquisition_providers(acquisition, self._container.provider_manager)
        return library_id


class _WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Welcome to VaultSeek")
        self.setSubTitle("Find what’s missing, download it, and keep your music library tidy.")
        layout = QVBoxLayout(self)
        body = QLabel(
            "<p><b>What VaultSeek does</b></p>"
            "<ol>"
            "<li><b>Incoming</b> — drop new files or let downloads land here.</li>"
            "<li><b>Identify</b> — fingerprint and match to MusicBrainz / Discogs.</li>"
            "<li><b>Library</b> — organize into Artist / Year - Album folders.</li>"
            "<li><b>Acquire</b> — search Soulseek (via Nicotine+) for missing tracks.</li>"
            "</ol>"
            "<p>This short wizard sets up the folders and optional download connection. "
            "You can change everything later in Settings.</p>"
        )
        body.setWordWrap(True)
        body.setOpenExternalLinks(True)
        layout.addWidget(body)
        layout.addStretch(1)


class _FoldersPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Music folders")
        self.setSubTitle(
            "Like Lidarr’s root folder: tell VaultSeek where downloads land and "
            "where the organized collection lives."
        )
        layout = QFormLayout(self)
        self.name_edit = QLineEdit("My Music")
        self.incoming = PathPickerRow(placeholder=r"e.g. D:\Music\Incoming")
        self.staging = PathPickerRow(placeholder=r"e.g. D:\Music\Staging")
        self.library = PathPickerRow(placeholder=r"e.g. D:\Music\Library")
        self.archive = PathPickerRow(placeholder=r"e.g. D:\Music\Archive")
        self.watch = QCheckBox("Watch Incoming for new files")
        self.watch.setChecked(True)
        help_lbl = QLabel(
            "Tip: pick Incoming first — Staging, Library, and Archive are suggested as siblings."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addRow("Library name", self.name_edit)
        layout.addRow("Incoming (drop zone)", self.incoming)
        layout.addRow("Library (organized music)", self.library)
        layout.addRow("Staging (optional)", self.staging)
        layout.addRow("Archive (optional)", self.archive)
        layout.addRow(self.watch)
        layout.addRow(help_lbl)
        self.incoming.path_changed.connect(self._suggest_siblings)
        self.registerField("incoming*", self.incoming.line_edit())
        self.registerField("library_path*", self.library.line_edit())

    def _suggest_siblings(self, incoming_text: str) -> None:
        incoming = incoming_text.strip()
        if not incoming:
            return
        if self.staging.text() or self.library.text() or self.archive.text():
            return
        parent = Path(incoming).expanduser().resolve().parent
        self.staging.setText(str(parent / "Staging"))
        self.library.setText(str(parent / "Library"))
        self.archive.setText(str(parent / "Archive"))

    def validatePage(self) -> bool:  # noqa: N802 — Qt API
        if not self.incoming.text().strip() or not self.library.text().strip():
            QMessageBox.warning(
                self,
                "Folders",
                "Incoming and Library folders are required to continue.",
            )
            return False
        return True


class _NicotinePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Downloads (Nicotine+)")
        self.setSubTitle(
            "Optional but recommended — Soulseek searches need Nicotine+ with the "
            "api-nicotine-plus plugin (HTTP)."
        )
        layout = QFormLayout(self)
        self.enabled = QCheckBox("Enable Nicotine+ downloads")
        self.enabled.setChecked(True)
        self.host = QLineEdit("127.0.0.1")
        self.api_port = QSpinBox()
        self.api_port.setRange(1024, 65535)
        self.api_port.setValue(12339)
        self.api_token = QLineEdit()
        self.api_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_token.setPlaceholderText("Optional API token")
        test = QPushButton("Test connection")
        test.setProperty("secondary", True)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        test.clicked.connect(self._test)
        skip = QLabel(
            "You can skip this and enable later in Settings → Acquisition. "
            "Without Nicotine+, library scanning and organize still work."
        )
        skip.setWordWrap(True)
        skip.setProperty("muted", True)
        layout.addRow(self.enabled)
        layout.addRow("Host", self.host)
        layout.addRow("HTTP API port", self.api_port)
        layout.addRow("API token", self.api_token)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addStretch(1)
        layout.addRow(row)
        layout.addRow(self.status)
        layout.addRow(skip)

    def _test(self) -> None:
        result = probe_nicotine_plus_connection(
            host=self.host.text().strip() or "127.0.0.1",
            port=22024,
            transport="http",
            api_port=int(self.api_port.value()),
            api_token=self.api_token.text().strip(),
        )
        self.status.setText(result.message)


class _TokensPage(QWizardPage):
    def __init__(self, container: Container) -> None:
        super().__init__()
        self.setTitle("Optional accounts")
        self.setSubTitle("Improve identification and Discogs browse — skip if you prefer.")
        layout = QFormLayout(self)
        self.discogs = QLineEdit()
        self.discogs.setEchoMode(QLineEdit.EchoMode.Password)
        self.discogs.setPlaceholderText("Discogs personal access token")
        self.discogs.setText(container.config.metadata.discogs_user_token or "")
        self.acoustid = QLineEdit()
        self.acoustid.setEchoMode(QLineEdit.EchoMode.Password)
        self.acoustid.setPlaceholderText("AcoustID application API key")
        self.acoustid.setText(container.config.metadata.acoustid_api_key or "")
        help_lbl = QLabel(
            "Discogs: https://www.discogs.com/settings/developers<br>"
            "AcoustID: https://acoustid.org/new-applications"
        )
        help_lbl.setOpenExternalLinks(True)
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addRow("Discogs token", self.discogs)
        layout.addRow("AcoustID key", self.acoustid)
        layout.addRow(help_lbl)


class _QualityPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Library quality")
        self.setSubTitle("Used for orange “below prefs / missing” highlights and upgrade jobs.")
        layout = QFormLayout(self)
        self.prefer_lossless = QCheckBox("Prefer lossless (FLAC) when available")
        self.prefer_lossless.setChecked(True)
        self.min_bitrate = QSpinBox()
        self.min_bitrate.setRange(0, 3200)
        self.min_bitrate.setSingleStep(32)
        self.min_bitrate.setValue(192)
        self.min_bitrate.setSuffix(" kbps")
        layout.addRow(self.prefer_lossless)
        layout.addRow("Min bitrate for lossy", self.min_bitrate)


class _DonePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("You’re ready")
        self.setSubTitle("Finish to save. Then follow the Dashboard checklist.")
        layout = QVBoxLayout(self)
        body = QLabel(
            "<p>After you click <b>Finish</b>:</p>"
            "<ol>"
            "<li>Open <b>Dashboard</b> — use the Getting started checklist.</li>"
            "<li><b>Scan Incoming</b> if you already have files to identify.</li>"
            "<li>Use <b>Find &amp; get → Find music</b> (gaps or Discogs) to queue downloads.</li>"
            "<li>Watch <b>Wishlist</b> / <b>Jobs</b> while searches and imports run.</li>"
            "</ol>"
            "<p>Re-open this wizard anytime from the Dashboard <b>Setup wizard</b> button "
            "or <b>Help → Setup wizard…</b></p>"
        )
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addStretch(1)

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
from uuid import UUID

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
    QWidget,
    QWizard,
    QWizardPage,
)

from vaultseek.core.config import (
    AcoustIdEndpointConfig,
    save_config,
)
from vaultseek.core.container import Container
from vaultseek.core.uuid_utils import generate_uuid7
from vaultseek.gui.widgets.path_picker import PathPickerRow
from vaultseek.gui.widgets.quality_fields import QualityFields
from vaultseek.models.entities.library import Library
from vaultseek.services.acquisition_bootstrap import (
    connect_acquisition_providers,
    probe_nicotine_plus_connection,
)
from vaultseek.services.quality_presets import PRESET_COLLECTOR, normalize_preset_id


class SetupWizard(QWizard):
    """Modal guided setup. Emits ``finished_setup`` with the library id when done."""

    finished_setup = Signal(object)  # UUID | None

    def __init__(
        self,
        container: Container,
        parent: QWidget | None = None,
        *,
        library_id: UUID | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id = library_id
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

        self._prefill()
        self.finished.connect(self._on_finished)

    def _target_library(self) -> Library | None:
        if self._library_id is not None:
            found = self._container.library_repo.get(self._library_id)
            if found is not None:
                return found
        existing = self._container.library_repo.list_all()
        return existing[0] if existing else None

    def _prefill(self) -> None:
        """Load the active library and saved config so re-runs do not wipe fields."""
        library = self._target_library()
        if library is not None:
            self._library_id = library.id
            self._folders.name_edit.setText(library.name)
            self._folders.incoming.setText(library.incoming_path)
            self._folders.library.setText(library.library_path)
            self._folders.staging.setText(library.staging_path)
            self._folders.archive.setText(library.archive_path)
            self._folders.watch.setChecked(library.watch_enabled)

        nicotine = self._container.config.acquisition.nicotine_plus
        self._nicotine.enabled.setChecked(nicotine.enabled)
        self._nicotine.host.setText(nicotine.host or "127.0.0.1")
        self._nicotine.api_port.setValue(int(nicotine.api_port or 12339))
        self._nicotine.api_token.setText(nicotine.api_token)

        if self._container.config.setup_completed:
            self._quality.fields.load(self._container.config.acquisition)
        else:
            self._quality.fields.select_preset(PRESET_COLLECTOR)

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
        existing = self._target_library()
        if existing is not None:
            updated = replace(
                existing,
                name=name,
                incoming_path=incoming,
                staging_path=staging,
                library_path=library_path,
                archive_path=archive,
                watch_enabled=self._folders.watch.isChecked(),
                updated_at=now,
            )
            self._container.library_repo.upsert(updated)
            library_id = existing.id
        else:
            library_id = generate_uuid7()
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

        # Merge Nicotine + quality + optional tokens without wiping nested fields.
        existing_nic = self._container.config.acquisition.nicotine_plus
        nicotine = replace(
            existing_nic,
            enabled=self._nicotine.enabled.isChecked(),
            host=self._nicotine.host.text().strip() or "127.0.0.1",
            api_port=int(self._nicotine.api_port.value()),
            api_token=self._nicotine.api_token.text().strip(),
        )
        enabled = list(self._container.config.acquisition.enabled_providers)
        if nicotine.enabled:
            if "nicotine_plus" not in enabled:
                enabled.append("nicotine_plus")
            enabled = [p for p in enabled if p != "stub"]
        else:
            enabled = [p for p in enabled if p != "nicotine_plus"]
        if not enabled:
            enabled = ["stub"]

        quality = self._quality.fields
        acquisition = replace(
            self._container.config.acquisition,
            enabled_providers=tuple(dict.fromkeys(enabled)),
            auto_queue_jobs=True,
            prefer_lossless=quality.prefer_lossless.isChecked(),
            preferred_codec=quality.preferred_codec.text().strip(),
            min_bitrate_kbps=int(quality.min_bitrate.value()),
            quality_preset=normalize_preset_id(quality.preset_id()),
            nicotine_plus=nicotine,
        )
        discogs_token = self._tokens.discogs.text().strip()
        acoustid_key = self._tokens.acoustid.text().strip()
        metadata = self._container.config.metadata
        endpoints = list(metadata.acoustid_endpoints)
        if acoustid_key:
            if endpoints:
                endpoints[0] = replace(endpoints[0], api_key=acoustid_key)
            else:
                endpoints = [AcoustIdEndpointConfig(api_key=acoustid_key, label="Primary")]
            metadata = replace(
                metadata,
                discogs_user_token=discogs_token,
                acoustid_api_key=acoustid_key,
                acoustid_endpoints=tuple(endpoints),
            )
        else:
            metadata = replace(metadata, discogs_user_token=discogs_token)
        already_completed = self._container.config.setup_completed
        updated_config = replace(
            self._container.config,
            setup_completed=True,
            onboarding_tips_dismissed=(
                self._container.config.onboarding_tips_dismissed if already_completed else False
            ),
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
            "You can skip this and enable later in Settings → Wishlist & downloads. "
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
        existing_key = container.config.metadata.acoustid_api_key or ""
        if not existing_key and container.config.metadata.acoustid_endpoints:
            existing_key = container.config.metadata.acoustid_endpoints[0].api_key
        self.acoustid.setText(existing_key)
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
        self.fields = QualityFields()
        self.fields.add_to_form(layout)


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

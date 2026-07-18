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
    QVBoxLayout,
    QWidget,
)

from musicvault.core.config import save_config
from musicvault.core.container import Container
from musicvault.models.entities.library import Library
from musicvault.models.entities.media_server_state import MediaServerState


class SettingsPage(QWidget):
    """Library zone paths plus light app-level preferences."""

    library_saved = Signal(object)
    preferences_saved = Signal(str)

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._editing_id: UUID | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Settings")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        lib_box = QGroupBox("Library")
        form = QFormLayout(lib_box)
        self._name = QLineEdit()
        self._incoming = QLineEdit()
        self._staging = QLineEdit()
        self._library = QLineEdit()
        self._archive = QLineEdit()
        self._watch = QCheckBox("Watch incoming folder")
        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0.0, 1.0)
        self._threshold.setSingleStep(0.05)
        self._threshold.setValue(0.90)
        form.addRow("Name", self._name)
        form.addRow("Incoming", self._incoming)
        form.addRow("Staging", self._staging)
        form.addRow("Library", self._library)
        form.addRow("Archive", self._archive)
        form.addRow(self._watch)
        form.addRow("Auto-approve threshold", self._threshold)
        layout.addWidget(lib_box)

        lib_buttons = QHBoxLayout()
        save_lib = QPushButton("Save library")
        new_lib = QPushButton("New library")
        new_lib.setProperty("secondary", True)
        save_lib.clicked.connect(self._save_library)
        new_lib.clicked.connect(self._new_library)
        lib_buttons.addWidget(save_lib)
        lib_buttons.addWidget(new_lib)
        lib_buttons.addStretch(1)
        layout.addLayout(lib_buttons)

        prefs = QGroupBox("Application")
        prefs_form = QFormLayout(prefs)
        self._log_level = QComboBox()
        self._log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._theme = QComboBox()
        self._theme.addItems(["dark", "light"])
        prefs_form.addRow("Log level", self._log_level)
        prefs_form.addRow("Theme", self._theme)
        save_prefs = QPushButton("Save preferences")
        save_prefs.clicked.connect(self._save_preferences)
        prefs_form.addRow(save_prefs)
        layout.addWidget(prefs)

        media = QGroupBox("Media servers")
        media_form = QFormLayout(media)
        self._ms_plugin = QComboBox()
        self._ms_plugin.addItems(["navidrome", "jellyfin", "plex", "subsonic"])
        self._ms_url = QLineEdit()
        self._ms_username = QLineEdit()
        self._ms_password = QLineEdit()
        self._ms_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._ms_token = QLineEdit()
        self._ms_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._ms_db_path = QLineEdit()
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

        layout.addStretch(1)

    def set_library(self, library_id: UUID | None) -> None:
        self._editing_id = library_id
        self.refresh()

    def refresh(self) -> None:
        config = self._container.config
        self._log_level.setCurrentText(config.log_level)
        self._theme.setCurrentText(config.theme)

        if self._editing_id is None:
            self._clear_library_form()
            return
        library = self._container.library_repo.get(self._editing_id)
        if library is None:
            self._clear_library_form()
            return
        self._name.setText(library.name)
        self._incoming.setText(library.incoming_path)
        self._staging.setText(library.staging_path)
        self._library.setText(library.library_path)
        self._archive.setText(library.archive_path)
        self._watch.setChecked(library.watch_enabled)
        self._threshold.setValue(library.auto_approve_threshold)

    def _clear_library_form(self) -> None:
        self._name.clear()
        self._incoming.clear()
        self._staging.clear()
        self._library.clear()
        self._archive.clear()
        self._watch.setChecked(False)
        self._threshold.setValue(0.90)

    def _new_library(self) -> None:
        self._editing_id = None
        self._clear_library_form()

    def _save_library(self) -> None:
        name = self._name.text().strip()
        incoming = self._incoming.text().strip()
        staging = self._staging.text().strip()
        library_path = self._library.text().strip()
        archive = self._archive.text().strip()
        if not name or not incoming or not staging or not library_path or not archive:
            QMessageBox.warning(self, "Settings", "Name and all four zone paths are required.")
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

        for path in (incoming, staging, library_path, archive):
            Path(path).mkdir(parents=True, exist_ok=True)

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

    def _save_preferences(self) -> None:
        updated = replace(
            self._container.config,
            log_level=self._log_level.currentText(),
            theme=self._theme.currentText(),
        )
        save_config(updated, self._container.paths.config_file)
        self.preferences_saved.emit(updated.theme)

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
        db_path = self._ms_db_path.text().strip() or None
        existing = [
            row
            for row in self._container.media_server_repo.list_by_library(self._editing_id)
            if row.plugin_id == plugin_id
        ]
        state_id = existing[0].id if existing else uuid7()
        self._container.media_server_repo.upsert(
            MediaServerState(
                id=state_id,
                library_id=self._editing_id,
                plugin_id=plugin_id,
                server_url=url,
                db_path=db_path,
                config=config,
            )
        )
        self._ms_status.setText(f"Saved {plugin_id} connection.")
        QMessageBox.information(self, "Settings", f"Media server “{plugin_id}” saved.")

"""Main application window — sidebar navigation + content stack."""

from __future__ import annotations

import os
from uuid import UUID

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from vaultseek import __version__
from vaultseek.core.container import Container
from vaultseek.gui.bridge.qt_event_bridge import QtEventBridge
from vaultseek.gui.theme import apply_theme
from vaultseek.gui.views.albums_page import AlbumsPage
from vaultseek.gui.views.artwork_page import ArtworkPage
from vaultseek.gui.views.artists_page import ArtistsPage
from vaultseek.gui.views.dashboard_page import DashboardPage
from vaultseek.gui.views.duplicates_page import DuplicatesPage
from vaultseek.gui.views.jobs_page import JobsPage
from vaultseek.gui.views.library_page import LibraryPage
from vaultseek.gui.views.logs_page import LogsPage
from vaultseek.gui.views.review_page import ReviewPage
from vaultseek.gui.views.rules_page import RulesPage
from vaultseek.gui.views.settings_page import SettingsPage
from vaultseek.gui.views.stub_page import StubPage
from vaultseek.gui.widgets.desktop import open_path
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone

_NAV = (
    ("Dashboard", "dashboard"),
    ("Library", "library"),
    ("Review", "review"),
    ("Artists", "artists"),
    ("Albums", "albums"),
    ("Artwork", "artwork"),
    ("Duplicates", "duplicates"),
    ("Jobs", "jobs"),
    ("Reports", "reports"),
    ("Rules", "rules"),
    ("Logs", "logs"),
    ("Settings", "settings"),
    ("Plugins", "plugins"),
)


class MainWindow(QMainWindow):
    """Shell described in docs/architecture/06-gui-architecture.md."""

    def __init__(self, container: Container) -> None:
        super().__init__()
        self._container = container
        self._library_id: UUID | None = None
        self._bridge = QtEventBridge(container.event_bus, parent=self)
        self._bridge.review_item_added.connect(self._on_review_event)

        self.setWindowTitle("VaultSeek")
        self.resize(1200, 800)
        # Allow smaller remote-desktop / laptop viewports; pages scroll instead of clipping.
        self.setMinimumSize(720, 480)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(12, 8, 12, 8)
        top.addWidget(QLabel("Library:"))
        self._library_combo = QComboBox()
        self._library_combo.setToolTip("Active library — zone paths and jobs are scoped to this.")
        self._library_combo.currentIndexChanged.connect(self._on_library_changed)
        top.addWidget(self._library_combo, stretch=1)
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._nav = QListWidget()
        self._nav.setFixedWidth(160)
        self._stack = QStackedWidget()
        body.addWidget(self._nav)
        body.addWidget(self._stack, stretch=1)
        outer.addLayout(body, stretch=1)

        self._pages: dict[str, QWidget] = {}
        self._dashboard_page = DashboardPage(container)
        self._dashboard_page.navigate_requested.connect(self._on_dashboard_navigate)
        self._review_page = ReviewPage(container)
        self._library_page = LibraryPage(container)
        self._artists_page = ArtistsPage(container)
        self._artists_page.navigate_to_albums.connect(self._on_artists_to_albums)
        self._albums_page = AlbumsPage(container)
        self._artwork_page = ArtworkPage(container)
        self._jobs_page = JobsPage(container)
        self._duplicates_page = DuplicatesPage(container)
        self._rules_page = RulesPage(container)
        self._settings_page = SettingsPage(container)
        self._settings_page.library_saved.connect(self._on_library_saved)
        self._settings_page.preferences_saved.connect(self._on_theme_changed)
        self._settings_page.scan_requested.connect(lambda: self._go_to("jobs"))
        self._logs_page = LogsPage(container)

        page_builders: dict[str, QWidget] = {
            "dashboard": self._dashboard_page,
            "library": self._library_page,
            "review": self._review_page,
            "artists": self._artists_page,
            "albums": self._albums_page,
            "duplicates": self._duplicates_page,
            "jobs": self._jobs_page,
            "artwork": self._artwork_page,
            "reports": StubPage(
                "Reports",
                "Report viewer UI is deferred. Library summary reports can still be "
                "generated as generate_report jobs; files land under the app reports folder "
                "(Open data folder in Settings).",
            ),
            "rules": self._rules_page,
            "logs": self._logs_page,
            "settings": self._settings_page,
            "plugins": StubPage(
                "Plugins",
                "Plugin manager UI is next on the polish list. Built-in media servers "
                "are already selectable in Settings: Navidrome, Jellyfin, Emby, Plex, "
                "Subsonic, Ampache, Koel, Funkwhale, and Lyrion. Metadata/artwork "
                "providers (tags, MusicBrainz, AcoustID, Cover Art Archive) run from "
                "the processing pipeline.",
            ),
        }

        self._nav_keys: list[str] = []
        for label, key in _NAV:
            self._nav.addItem(QListWidgetItem(label))
            page = page_builders[key]
            self._pages[key] = page
            self._nav_keys.append(key)
            self._stack.addWidget(page)

        self._nav.currentRowChanged.connect(self._on_nav_changed)
        self._nav.setCurrentRow(0)  # Dashboard home

        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel("Ready")
        status.addWidget(self._status_label, stretch=1)

        self._build_menus()

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.reload_libraries()
        self._tick()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        scan = QAction("Scan &Incoming", self)
        scan.setShortcut(QKeySequence("Ctrl+Shift+S"))
        scan.setToolTip(
            "Scan Incoming and only process new or changed files (size/mtime)."
        )
        scan.triggered.connect(lambda: self._scan_incoming(force=False))
        file_menu.addAction(scan)
        force_scan = QAction("Force &Rescan Incoming", self)
        force_scan.setToolTip(
            "Re-queue every audio file in Incoming, even if already scanned."
        )
        force_scan.triggered.connect(lambda: self._scan_incoming(force=True))
        file_menu.addAction(force_scan)
        file_menu.addSeparator()
        open_incoming = QAction("Open Incoming Folder", self)
        open_incoming.triggered.connect(self._open_incoming)
        file_menu.addAction(open_incoming)
        open_logs = QAction("Open &Log Folder", self)
        open_logs.triggered.connect(lambda: open_path(self._container.paths.logs_dir))
        file_menu.addAction(open_logs)
        open_data = QAction("Open &Data Folder", self)
        open_data.triggered.connect(lambda: open_path(self._container.paths.root))
        file_menu.addAction(open_data)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        go_dash = QAction("&Dashboard", self)
        go_dash.setShortcut(QKeySequence("Ctrl+D"))
        go_dash.triggered.connect(lambda: self._go_to("dashboard"))
        view_menu.addAction(go_dash)
        go_library = QAction("&Library", self)
        go_library.setShortcut(QKeySequence("Ctrl+L"))
        go_library.triggered.connect(lambda: self._go_to("library"))
        view_menu.addAction(go_library)
        go_review = QAction("&Review", self)
        go_review.setShortcut(QKeySequence("Ctrl+R"))
        go_review.triggered.connect(lambda: self._go_to("review"))
        view_menu.addAction(go_review)
        go_jobs = QAction("&Jobs", self)
        go_jobs.setShortcut(QKeySequence("Ctrl+J"))
        go_jobs.triggered.connect(lambda: self._go_to("jobs"))
        view_menu.addAction(go_jobs)
        go_settings = QAction("&Settings", self)
        go_settings.setShortcut(QKeySequence("Ctrl+,"))
        go_settings.triggered.connect(lambda: self._go_to("settings"))
        view_menu.addAction(go_settings)
        view_menu.addSeparator()
        refresh = QAction("&Refresh", self)
        refresh.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh.triggered.connect(self._refresh_current)
        view_menu.addAction(refresh)

        help_menu = self.menuBar().addMenu("&Help")
        about = QAction("&About VaultSeek", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)
        uninstall = QAction("&Uninstall VaultSeek…", self)
        uninstall.setToolTip("Remove the installed application via Windows Apps & Features.")
        uninstall.triggered.connect(self._uninstall)
        help_menu.addAction(uninstall)

    def _on_dashboard_navigate(self, key: str) -> None:
        if key == "scan":
            self._scan_incoming(force=False)
            return
        if key == "force_scan":
            self._scan_incoming(force=True)
            return
        self._go_to(key)

    def _scan_incoming(self, *, force: bool = False) -> None:
        library = self._current_library()
        if library is None:
            QMessageBox.warning(self, "VaultSeek", "Create or select a library in Settings first.")
            self._go_to("settings")
            return
        stats = self._container.job_queue.get_stats(library.id)
        if stats.by_type.get(JobType.SCAN_DIRECTORY.value, 0) > 0:
            QMessageBox.information(self, "VaultSeek", "A scan is already queued.")
            self._go_to("jobs")
            return
        payload: dict[str, object] = {
            "directory": library.incoming_path,
            "zone": LibraryZone.INCOMING.value,
        }
        if force:
            payload["force"] = True
        self._container.job_queue.enqueue(
            JobType.SCAN_DIRECTORY,
            library.id,
            payload,
        )
        self._go_to("jobs")
        self._jobs_page.refresh()
        label = "Force rescan" if force else "Scan"
        self.statusBar().showMessage(f"{label} queued: {library.incoming_path}", 5000)

    def _on_artists_to_albums(self, artist_id: object) -> None:
        aid = artist_id if isinstance(artist_id, UUID) else None
        self._albums_page.set_artist_filter(aid)
        self._go_to("albums")

    def _go_to(self, key: str) -> None:
        if key not in self._nav_keys:
            return
        self._nav.setCurrentRow(self._nav_keys.index(key))

    def _refresh_current(self) -> None:
        index = self._nav.currentRow()
        self._on_nav_changed(index)

    def _current_library(self) -> Library | None:
        if self._library_id is None:
            return None
        return self._container.library_repo.get(self._library_id)

    def _open_incoming(self) -> None:
        library = self._current_library()
        if library is None:
            QMessageBox.warning(self, "VaultSeek", "No library selected.")
            return
        open_path(library.incoming_path)

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About VaultSeek",
            f"<h3>VaultSeek {__version__}</h3>"
            "<p>Lightroom for music — scan Incoming, identify, review, "
            "organize to Library, fetch artwork, sync media servers.</p>"
            f"<p>Data folder:<br><code>{self._container.paths.root}</code></p>"
            f"<p>Logs:<br><code>{self._container.paths.logs_dir}</code></p>"
            "<p>Source: <a href='https://github.com/oceanmasterza/VaultSeek'>"
            "github.com/oceanmasterza/VaultSeek</a></p>",
        )

    def _uninstall(self) -> None:
        """Launch the Windows uninstaller when running from an installed copy."""
        import sys
        from pathlib import Path

        candidates = [
            Path(sys.executable).resolve().parent / "Uninstall.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "VaultSeek" / "Uninstall.exe",
        ]
        uninstall = next((p for p in candidates if p.is_file()), None)
        if uninstall is None:
            QMessageBox.information(
                self,
                "Uninstall VaultSeek",
                "No installer registration was found.\n\n"
                "If you installed with VaultSeek-Setup.exe, use:\n"
                "Settings → Apps → Installed apps → VaultSeek → Uninstall\n"
                "or Start Menu → VaultSeek → Uninstall VaultSeek.",
            )
            return
        if (
            QMessageBox.question(
                self,
                "Uninstall VaultSeek",
                "This will close VaultSeek and open the uninstaller.\n\nContinue?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        import subprocess

        subprocess.Popen([str(uninstall), "--uninstall"], cwd=str(uninstall.parent))
        self.close()

    def reload_libraries(self) -> None:
        current = self._library_id
        self._library_combo.blockSignals(True)
        self._library_combo.clear()
        libraries = self._container.library_repo.list_all()
        for library in libraries:
            self._library_combo.addItem(library.name, library.id)
        self._library_combo.blockSignals(False)

        if not libraries:
            self._set_library(None)
            return

        index = 0
        if current is not None:
            for i in range(self._library_combo.count()):
                if self._library_combo.itemData(i) == current:
                    index = i
                    break
        self._library_combo.setCurrentIndex(index)
        self._set_library(self._library_combo.currentData())

    def _on_nav_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        if index < 0 or index >= len(self._nav_keys):
            return
        key = self._nav_keys[index]
        if key == "dashboard":
            self._dashboard_page.refresh()
        elif key == "review":
            self._review_page.refresh()
            self._update_review_badge()
        elif key == "jobs":
            self._jobs_page.refresh()
        elif key == "library":
            self._library_page.refresh()
        elif key == "artists":
            self._artists_page.refresh()
        elif key == "albums":
            self._albums_page.refresh()
        elif key == "artwork":
            self._artwork_page.refresh()
        elif key == "duplicates":
            self._duplicates_page.refresh()
        elif key == "rules":
            self._rules_page.refresh()
        elif key == "settings":
            self._settings_page.refresh()

    def _on_library_changed(self, _index: int) -> None:
        self._set_library(self._library_combo.currentData())

    def _set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        for page in (
            self._dashboard_page,
            self._library_page,
            self._artists_page,
            self._albums_page,
            self._artwork_page,
            self._review_page,
            self._jobs_page,
            self._duplicates_page,
            self._rules_page,
            self._settings_page,
        ):
            page.set_library(library_id)
        self._update_review_badge()
        self._tick()

    def _on_library_saved(self, library_id: UUID) -> None:
        self._library_id = library_id
        self.reload_libraries()

    def _on_theme_changed(self, theme: str) -> None:
        from PySide6.QtWidgets import QApplication

        qapp = QApplication.instance()
        if isinstance(qapp, QApplication):
            apply_theme(qapp, theme)

    def _on_review_event(self, _event: object) -> None:
        self._review_page.refresh()
        self._update_review_badge()
        self._tick()

    def _update_review_badge(self) -> None:
        count = self._review_page.pending_count()
        for i, key in enumerate(self._nav_keys):
            if key != "review":
                continue
            item = self._nav.item(i)
            if item is not None:
                item.setText(f"Review ({count})" if count else "Review")

    def _tick(self) -> None:
        if self._library_id is None:
            self._status_label.setText("No library — create one in Settings")
            return
        stats = self._container.job_queue.get_stats(self._library_id)
        review = self._container.review_queue.count_pending(self._library_id)
        self._status_label.setText(
            f"Jobs: {stats.running} running · {stats.pending} pending · "
            f"{stats.failed} failed · Review: {review}"
        )
        self._update_review_badge()
        # Keep Dashboard live while it is visible (status-bar cadence).
        row = self._nav.currentRow()
        if self._nav_keys and 0 <= row < len(self._nav_keys) and self._nav_keys[row] == "dashboard":
            self._dashboard_page.refresh()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        self._timer.stop()
        self._bridge.close()
        super().closeEvent(event)

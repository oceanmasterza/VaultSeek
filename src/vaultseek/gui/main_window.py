"""Main application window — hub sidebar + content stack.

Navigation is grouped into four hubs (Home / Library / Find & get / System)
so first-time users see a short path. Every former flat page remains available
as a leaf under a hub — nothing is removed, only grouped.
"""

from __future__ import annotations

import os
from uuid import UUID

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek import __version__
from vaultseek.core.container import Container
from vaultseek.gui.bridge.qt_event_bridge import QtEventBridge
from vaultseek.gui.theme import apply_theme
from vaultseek.gui.views.acquisition_page import AcquisitionPage
from vaultseek.gui.views.albums_page import AlbumsPage
from vaultseek.gui.views.artwork_page import ArtworkPage
from vaultseek.gui.views.artists_page import ArtistsPage
from vaultseek.gui.views.dashboard_page import DashboardPage
from vaultseek.gui.views.duplicates_page import DuplicatesPage
from vaultseek.gui.views.find_music_page import FindMusicPage
from vaultseek.gui.views.jobs_page import JobsPage
from vaultseek.gui.views.library_page import LibraryPage
from vaultseek.gui.views.logs_page import LogsPage
from vaultseek.gui.views.reports_page import ReportsPage
from vaultseek.gui.views.review_page import ReviewPage
from vaultseek.gui.views.settings_page import SettingsPage
from vaultseek.gui.views.setup_wizard import SetupWizard
from vaultseek.gui.views.stub_page import StubPage
from vaultseek.gui.widgets.desktop import open_path
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone

# Hub → (label, page_key). page_key None = hub header only (not selectable).
_NAV_HUBS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Home",
        (("Dashboard", "dashboard"),),
    ),
    (
        "Library",
        (
            ("Files", "library"),
            ("Artists", "artists"),
            ("Albums", "albums"),
            ("Artwork", "artwork"),
            ("Duplicates", "duplicates"),
        ),
    ),
    (
        "Find & get",
        (
            ("Find music", "find"),
            ("Review", "review"),
            ("Wishlist", "acquisition"),
        ),
    ),
    (
        "System",
        (
            ("Jobs", "jobs"),
            ("Reports", "reports"),
            ("Logs", "logs"),
            ("Settings", "settings"),
            ("Plugins", "plugins"),
        ),
    ),
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
        self._nav = QTreeWidget()
        self._nav.setObjectName("navSidebar")
        self._nav.setHeaderHidden(True)
        self._nav.setFixedWidth(180)
        self._nav.setRootIsDecorated(True)
        self._nav.setAnimated(True)
        self._nav.setIndentation(14)
        self._nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stack = QStackedWidget()
        body.addWidget(self._nav)
        body.addWidget(self._stack, stretch=1)
        outer.addLayout(body, stretch=1)

        self._pages: dict[str, QWidget] = {}
        self._nav_items: dict[str, QTreeWidgetItem] = {}
        self._stack_index: dict[str, int] = {}

        self._dashboard_page = DashboardPage(container)
        self._dashboard_page.navigate_requested.connect(self._on_dashboard_navigate)
        self._review_page = ReviewPage(container)
        self._library_page = LibraryPage(container)
        self._library_page.navigate_requested.connect(self._on_dashboard_navigate)
        self._artists_page = ArtistsPage(container)
        self._artists_page.navigate_to_albums.connect(self._on_artists_to_albums)
        self._albums_page = AlbumsPage(container)
        self._albums_page.navigate_requested.connect(self._on_dashboard_navigate)
        self._artwork_page = ArtworkPage(container)
        self._jobs_page = JobsPage(container)
        self._duplicates_page = DuplicatesPage(container)
        self._acquisition_page = AcquisitionPage(container)
        self._acquisition_page.navigate_requested.connect(self._on_dashboard_navigate)
        self._find_page = FindMusicPage(container)
        self._find_page.navigate_requested.connect(self._on_dashboard_navigate)
        self._reports_page = ReportsPage(container)
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
            "find": self._find_page,
            "acquisition": self._acquisition_page,
            "jobs": self._jobs_page,
            "artwork": self._artwork_page,
            "reports": self._reports_page,
            "logs": self._logs_page,
            "settings": self._settings_page,
            "plugins": StubPage(
                "Plugins",
                "Plugin manager UI is next on the polish list. Built-in media servers "
                "are already selectable in Settings: Navidrome, Jellyfin, Emby, Plex, "
                "Subsonic, Ampache, Koel, Funkwhale, and Lyrion. Metadata/artwork "
                "providers (tags, MusicBrainz, AcoustID, Cover Art Archive, Discogs) run from "
                "the processing pipeline.",
            ),
        }

        for hub_label, children in _NAV_HUBS:
            hub_item = QTreeWidgetItem([hub_label])
            hub_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            hub_item.setData(0, Qt.ItemDataRole.UserRole, None)
            self._nav.addTopLevelItem(hub_item)
            hub_item.setExpanded(True)
            for child_label, key in children:
                page = page_builders[key]
                if key not in self._pages:
                    self._pages[key] = page
                    self._stack_index[key] = self._stack.count()
                    self._stack.addWidget(page)
                child = QTreeWidgetItem([child_label])
                child.setData(0, Qt.ItemDataRole.UserRole, key)
                hub_item.addChild(child)
                self._nav_items[key] = child

        self._nav.currentItemChanged.connect(self._on_nav_item_changed)
        # Start on Dashboard leaf.
        self._go_to("dashboard")

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
        QTimer.singleShot(0, self._maybe_show_setup_wizard)

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
        go_library = QAction("&Library files", self)
        go_library.setShortcut(QKeySequence("Ctrl+L"))
        go_library.triggered.connect(lambda: self._go_to("library"))
        view_menu.addAction(go_library)
        go_find = QAction("&Find music", self)
        go_find.setShortcut(QKeySequence("Ctrl+F"))
        go_find.triggered.connect(lambda: self._go_to("find"))
        view_menu.addAction(go_find)
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
        setup = QAction("Setup &wizard…", self)
        setup.setToolTip("Walk through folders, Nicotine+, and optional tokens.")
        setup.triggered.connect(lambda: self._show_setup_wizard(force=True))
        help_menu.addAction(setup)
        about = QAction("&About VaultSeek", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)
        uninstall = QAction("&Uninstall VaultSeek…", self)
        uninstall.setToolTip("Remove the installed application via Windows Apps & Features.")
        uninstall.triggered.connect(self._uninstall)
        help_menu.addAction(uninstall)

    def _maybe_show_setup_wizard(self) -> None:
        """Auto-open at most once: true first run only (never completed, no library)."""
        if self._container.config.setup_completed:
            return
        if self._container.library_repo.list_all():
            return
        self._show_setup_wizard()

    def _show_setup_wizard(self, *, force: bool = False) -> None:
        del force  # Always user-invoked or one-shot first run; same dialog either way.
        wizard = SetupWizard(self._container, parent=self)
        wizard.finished_setup.connect(self._on_setup_finished)
        wizard.exec()

    def _mark_setup_completed(self) -> None:
        """Stop auto-prompting the wizard (button / Help menu still reopen it)."""
        if self._container.config.setup_completed:
            return
        from dataclasses import replace

        from vaultseek.core.config import save_config

        updated = replace(self._container.config, setup_completed=True)
        save_config(updated, self._container.paths.config_file)
        self._container.config = updated

    def _on_setup_finished(self, library_id: object) -> None:
        if isinstance(library_id, UUID):
            self.reload_libraries()
            for index in range(self._library_combo.count()):
                if self._library_combo.itemData(index) == library_id:
                    self._library_combo.setCurrentIndex(index)
                    break
            self._dashboard_page.refresh()
            self._go_to("dashboard")
            self.statusBar().showMessage(
                "Setup complete — follow Getting started on the Dashboard.", 8000
            )
            return
        # Cancelled or unfinished — never force the wizard again.
        self._mark_setup_completed()
        self._dashboard_page.refresh()

    def _on_dashboard_navigate(self, key: str) -> None:
        if key == "setup_wizard":
            self._show_setup_wizard(force=True)
            return
        if key == "scan":
            self._scan_incoming(force=False)
            return
        if key == "force_scan":
            self._scan_incoming(force=True)
            return
        if key == "find_discogs":
            self._go_to("find")
            self._find_page.show_discogs_tab()
            return
        if key == "discogs":
            # Legacy deep-link from older tips — open Find music → Discogs tab.
            self._go_to("find")
            self._find_page.show_discogs_tab()
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
        item = self._nav_items.get(key)
        if item is None:
            return
        self._nav.setCurrentItem(item)
        # Ensure parent hub is expanded so the leaf is visible.
        parent = item.parent()
        if parent is not None:
            parent.setExpanded(True)

    def _refresh_current(self) -> None:
        item = self._nav.currentItem()
        if item is not None:
            self._on_nav_item_changed(item, None)

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

    def _on_nav_item_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(key, str):
            # Hub header clicked — keep previous leaf if any.
            return
        stack_i = self._stack_index.get(key)
        if stack_i is None:
            return
        self._stack.setCurrentIndex(stack_i)
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
        elif key == "find":
            self._find_page.refresh()
        elif key == "acquisition":
            self._acquisition_page.refresh()
        elif key == "reports":
            self._reports_page.refresh()
        elif key == "logs":
            self._logs_page.refresh()
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
            self._find_page,
            self._acquisition_page,
            self._reports_page,
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
        item = self._nav_items.get("review")
        if item is not None:
            item.setText(0, f"Review ({count})" if count else "Review")

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
        # Acquisition download polling runs in AcquisitionAutomationService.
        current = self._nav.currentItem()
        key = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if key == "dashboard":
            self._dashboard_page.refresh()
        elif key == "jobs":
            self._jobs_page.refresh()
        elif key == "acquisition":
            self._acquisition_page.poll_downloads()
        self._update_review_badge()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)

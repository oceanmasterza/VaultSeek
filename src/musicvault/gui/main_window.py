"""Main application window — sidebar navigation + content stack."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from musicvault.core.container import Container
from musicvault.gui.bridge.qt_event_bridge import QtEventBridge
from musicvault.gui.theme import apply_theme
from musicvault.gui.views.duplicates_page import DuplicatesPage
from musicvault.gui.views.jobs_page import JobsPage
from musicvault.gui.views.library_page import LibraryPage
from musicvault.gui.views.review_page import ReviewPage
from musicvault.gui.views.rules_page import RulesPage
from musicvault.gui.views.settings_page import SettingsPage
from musicvault.gui.views.stub_page import StubPage

_NAV = (
    ("Dashboard", "dashboard"),
    ("Library", "library"),
    ("Review", "review"),
    ("Artists", "artists"),
    ("Albums", "albums"),
    ("Duplicates", "duplicates"),
    ("Jobs", "jobs"),
    ("Artwork", "artwork"),
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

        self.setWindowTitle("MusicVault")
        self.resize(1200, 800)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(12, 8, 12, 8)
        top.addWidget(QLabel("Library:"))
        self._library_combo = QComboBox()
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
        self._review_page = ReviewPage(container)
        self._library_page = LibraryPage(container)
        self._jobs_page = JobsPage(container)
        self._duplicates_page = DuplicatesPage(container)
        self._rules_page = RulesPage(container)
        self._settings_page = SettingsPage(container)
        self._settings_page.library_saved.connect(self._on_library_saved)
        self._settings_page.preferences_saved.connect(self._on_theme_changed)

        page_builders: dict[str, QWidget] = {
            "dashboard": StubPage(
                "Dashboard",
                "Pipeline overview will land here. Use Jobs and Review for live status.",
            ),
            "library": self._library_page,
            "review": self._review_page,
            "artists": StubPage("Artists", "Artist browser deferred past the Phase 14 MVP."),
            "albums": StubPage("Albums", "Album grid deferred past the Phase 14 MVP."),
            "duplicates": self._duplicates_page,
            "jobs": self._jobs_page,
            "artwork": StubPage(
                "Artwork",
                "Artwork browser deferred — fetching runs in the pipeline.",
            ),
            "reports": StubPage(
                "Reports",
                "Report generation is available via generate_report jobs; GUI viewer deferred.",
            ),
            "rules": self._rules_page,
            "logs": StubPage("Logs", "Log viewer deferred — see AppPaths logs directory."),
            "settings": self._settings_page,
            "plugins": StubPage("Plugins", "Plugin manager UI deferred."),
        }

        self._nav_keys: list[str] = []
        for label, key in _NAV:
            self._nav.addItem(QListWidgetItem(label))
            page = page_builders[key]
            self._pages[key] = page
            self._nav_keys.append(key)
            self._stack.addWidget(page)

        self._nav.currentRowChanged.connect(self._on_nav_changed)
        self._nav.setCurrentRow(1)

        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel("Ready")
        status.addWidget(self._status_label, stretch=1)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.reload_libraries()
        self._tick()

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
        if key == "review":
            self._review_page.refresh()
            self._update_review_badge()
        elif key == "jobs":
            self._jobs_page.refresh()
        elif key == "library":
            self._library_page.refresh()
        elif key == "duplicates":
            self._duplicates_page.refresh()
        elif key == "rules":
            self._rules_page.refresh()

    def _on_library_changed(self, _index: int) -> None:
        self._set_library(self._library_combo.currentData())

    def _set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        for page in (
            self._library_page,
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
        # Full table rebuilds are event/page-driven — not on every poll —
        # so selection and scroll position stay stable while the user works.

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        self._timer.stop()
        self._bridge.close()
        super().closeEvent(event)

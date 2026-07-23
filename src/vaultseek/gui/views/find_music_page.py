"""Find music — one place for gap scans and Discogs browse.

Collapses the duplicated “Find missing / Find upgrades” toolbars and the
standalone Discogs tab into a single Find & get entry point. Acquisition
(wishlist) stays a sibling page for download progress.
"""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.views.discogs_page import DiscogsPage
from vaultseek.gui.widgets.empty_state import EmptyState
from vaultseek.services.library_scan_actions import run_missing_scan, run_quality_upgrade_scan


class FindMusicPage(QWidget):
    """Library gaps + Discogs catalog under one roof."""

    # Ask the shell to open Acquisition after queuing jobs.
    navigate_requested = Signal(str)

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Find music")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        help_lbl = QLabel(
            "Scan your library for missing or low-quality tracks, or browse Discogs "
            "and queue albums to download. Progress lives under Wishlist (Acquisition)."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addWidget(help_lbl)

        self._tabs = QTabWidget()
        self._gaps = _GapsTab(container)
        self._gaps.navigate_requested.connect(self.navigate_requested.emit)
        self._discogs = DiscogsPage(container)
        # Discogs page already has its own heading — hide duplicate chrome feel
        # by nesting it as the Discogs tab content.
        self._tabs.addTab(self._gaps, "Library gaps")
        self._tabs.addTab(self._discogs, "Discogs browse")
        layout.addWidget(self._tabs, stretch=1)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self._gaps.set_library(library_id)
        self._discogs.set_library(library_id)

    def refresh(self) -> None:
        self._gaps.refresh()
        self._discogs.refresh()

    def show_discogs_tab(self) -> None:
        self._tabs.setCurrentWidget(self._discogs)


class _GapsTab(QWidget):
    """Missing-track and quality-upgrade scans with a clear empty state."""

    navigate_requested = Signal(str)

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        actions = QHBoxLayout()
        self._btn_missing = QPushButton("Find missing songs")
        self._btn_missing.setToolTip(
            "Compare library albums to MusicBrainz tracklists and queue downloads."
        )
        self._btn_missing.clicked.connect(self._scan_missing)
        self._btn_upgrades = QPushButton("Find quality upgrades")
        self._btn_upgrades.setProperty("secondary", True)
        self._btn_upgrades.setToolTip(
            "Queue upgrades for tracks below Settings → Library quality prefs."
        )
        self._btn_upgrades.clicked.connect(self._scan_upgrades)
        self._btn_wishlist = QPushButton("Open wishlist")
        self._btn_wishlist.setProperty("secondary", True)
        self._btn_wishlist.clicked.connect(
            lambda: self.navigate_requested.emit("acquisition")
        )
        actions.addWidget(self._btn_missing)
        actions.addWidget(self._btn_upgrades)
        actions.addWidget(self._btn_wishlist)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._empty = EmptyState(
            "No gap scan yet",
            "Run Find missing songs after albums are identified, or browse Discogs "
            "to pick releases to download.",
            primary_label="Find missing songs",
            on_primary=self._scan_missing,
            secondary_label="Browse Discogs",
            on_secondary=lambda: self.navigate_requested.emit("find_discogs"),
        )
        layout.addWidget(self._empty, stretch=1)

        tip = QLabel(
            "Tip: orange rows on Albums / Library mean missing files or below quality prefs. "
            "Use those pages to inspect; use this page to queue downloads."
        )
        tip.setWordWrap(True)
        tip.setProperty("muted", True)
        layout.addWidget(tip)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        if self._library_id is None:
            self._status.setText("Select or create a library first (Setup wizard / Settings).")
            self._empty.setVisible(True)
            return
        jobs = self._container.acquisition_engine.list_jobs(library_id=self._library_id)
        active = sum(1 for job in jobs if not job.is_terminal)
        self._status.setText(
            f"{len(jobs)} wishlist job(s) · {active} active. "
            "Scan for gaps below, then open Wishlist to auto-acquire."
        )
        # Keep the empty panel as guidance even when jobs exist — it is the
        # primary CTA surface for this tab.
        self._empty.setVisible(len(jobs) == 0)

    def _scan_missing(self) -> None:
        if self._library_id is None:
            QMessageBox.information(self, "Find music", "Select a library first.")
            return
        count = run_missing_scan(self._container, self._library_id)
        QMessageBox.information(
            self,
            "Find missing songs",
            f"Created {count} acquisition job(s). Open Wishlist to download.",
        )
        self.refresh()
        if count:
            self.navigate_requested.emit("acquisition")

    def _scan_upgrades(self) -> None:
        if self._library_id is None:
            QMessageBox.information(self, "Find music", "Select a library first.")
            return
        count = run_quality_upgrade_scan(self._container, self._library_id)
        QMessageBox.information(
            self,
            "Find quality upgrades",
            f"Created {count} upgrade job(s). Open Wishlist to download.",
        )
        self.refresh()
        if count:
            self.navigate_requested.emit("acquisition")

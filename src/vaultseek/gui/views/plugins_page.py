"""Plugins page — enable and configure opt-in discovery/download plugins.

Keeps the core app lean: Last.fm similar-music, Spotify playlist sync, and
the Prowlarr+qBittorrent torrent backend are all off by default and only
appear in the acquisition pipeline once enabled here.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.config import (
    AcquisitionConfig,
    LastfmConfig,
    ProwlarrConfig,
    QbittorrentConfig,
    RecommendationConfig,
    SabnzbdConfig,
    SpotifyConfig,
    save_config,
)
from vaultseek.core.container import Container, _build_recommenders
from vaultseek.gui.async_task import run_in_background
from vaultseek.gui.widgets.scrollable import wrap_scrollable
from vaultseek.plugins.builtin.prowlarr_qbit import ProwlarrClient, QbittorrentClient
from vaultseek.plugins.builtin.sabnzbd import SabnzbdClient
from vaultseek.services.acquisition_bootstrap import connect_acquisition_providers
from vaultseek.services.recommendation_service import RecommendationService


class PluginsPage(QWidget):
    """Opt-in plugin manager: recommenders + torrent download backend."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None

        body = QWidget()
        wrap_scrollable(self, body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        heading = QLabel("Plugins")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        intro = QLabel(
            "Optional add-ons, all disabled by default. Discovery plugins fill your "
            "Wishlist with suggestions; download plugins add new sources alongside "
            "Nicotine+ (configured in Settings). Enable only what you want."
        )
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        layout.addWidget(intro)

        layout.addWidget(self._build_lastfm_box())
        layout.addWidget(self._build_spotify_box())
        layout.addWidget(self._build_recommender_actions())
        layout.addWidget(self._build_torrent_box())

        save_row = QHBoxLayout()
        save_btn = QPushButton("Save plugin settings")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        save_row.addWidget(save_btn)
        save_row.addStretch(1)
        layout.addLayout(save_row)
        layout.addStretch(1)

    # ------------------------------------------------------------------ UI --
    def _build_lastfm_box(self) -> QGroupBox:
        box = QGroupBox("Similar music (Last.fm)")
        form = QFormLayout(box)
        self._lastfm_enabled = QCheckBox("Enable similar-music recommendations")
        self._lastfm_enabled.setToolTip(
            "For each artist in your library, suggest albums by similar artists."
        )
        self._lastfm_api_key = QLineEdit()
        self._lastfm_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._lastfm_api_key.setPlaceholderText("Last.fm API key")
        self._lastfm_similar = QSpinBox()
        self._lastfm_similar.setRange(1, 20)
        self._lastfm_similar.setValue(5)
        self._lastfm_albums = QSpinBox()
        self._lastfm_albums.setRange(1, 10)
        self._lastfm_albums.setValue(2)
        form.addRow(self._lastfm_enabled)
        form.addRow("API key", self._lastfm_api_key)
        form.addRow("Similar artists per seed", self._lastfm_similar)
        form.addRow("Top albums per artist", self._lastfm_albums)
        help_label = QLabel(
            "Free key: https://www.last.fm/api/account/create. Suggestions land on "
            "your Wishlist as parked entries you can promote to download."
        )
        help_label.setWordWrap(True)
        help_label.setProperty("muted", True)
        help_label.setOpenExternalLinks(True)
        form.addRow(help_label)
        return box

    def _build_spotify_box(self) -> QGroupBox:
        box = QGroupBox("Spotify playlist sync")
        form = QFormLayout(box)
        self._spotify_enabled = QCheckBox("Mirror public playlists into the Wishlist")
        self._spotify_client_id = QLineEdit()
        self._spotify_client_id.setPlaceholderText("Spotify client ID")
        self._spotify_client_secret = QLineEdit()
        self._spotify_client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._spotify_client_secret.setPlaceholderText("Spotify client secret")
        self._spotify_playlists = QPlainTextEdit()
        self._spotify_playlists.setPlaceholderText(
            "One playlist link per line, e.g.\n"
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        )
        self._spotify_playlists.setFixedHeight(80)
        form.addRow(self._spotify_enabled)
        form.addRow("Client ID", self._spotify_client_id)
        form.addRow("Client secret", self._spotify_client_secret)
        form.addRow("Playlists", self._spotify_playlists)
        help_label = QLabel(
            "Create an app at https://developer.spotify.com/dashboard for the client "
            "ID/secret. Only public playlists are supported (no login needed). "
            "Albums referenced by playlist tracks are added to your Wishlist."
        )
        help_label.setWordWrap(True)
        help_label.setProperty("muted", True)
        help_label.setOpenExternalLinks(True)
        form.addRow(help_label)
        return box

    def _build_recommender_actions(self) -> QWidget:
        box = QGroupBox("Run discovery")
        row = QVBoxLayout(box)
        self._run_btn = QPushButton("Find recommendations now")
        self._run_btn.setToolTip(
            "Run enabled recommenders against the active library and add new "
            "suggestions to the Wishlist. Save settings first."
        )
        self._run_btn.clicked.connect(self._run_recommendations)
        self._run_status = QLabel("")
        self._run_status.setWordWrap(True)
        self._run_status.setProperty("muted", True)
        row.addWidget(self._run_btn)
        row.addWidget(self._run_status)
        return box

    def _build_torrent_box(self) -> QGroupBox:
        box = QGroupBox("Indexers — Prowlarr + qBittorrent / SABnzbd")
        form = QFormLayout(box)
        self._prowlarr_enabled = QCheckBox("Enable Prowlarr search")
        self._prowlarr_url = QLineEdit()
        self._prowlarr_url.setPlaceholderText("http://127.0.0.1:9696")
        self._prowlarr_key = QLineEdit()
        self._prowlarr_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._prowlarr_key.setPlaceholderText("Prowlarr API key (Settings → General)")
        self._prowlarr_seeders = QSpinBox()
        self._prowlarr_seeders.setRange(0, 1000)
        self._prowlarr_seeders.setValue(1)
        self._prowlarr_seeders.setToolTip(
            "Skip torrent results with fewer seeders than this (NZBs ignore seeders)."
        )
        self._qbit_enabled = QCheckBox("Enable qBittorrent downloads (torrents)")
        self._qbit_url = QLineEdit()
        self._qbit_url.setPlaceholderText("http://127.0.0.1:8081")
        self._qbit_url.setToolTip(
            "Use a port that does not conflict with SABnzbd (often 8080). Default 8081."
        )
        self._qbit_username = QLineEdit()
        self._qbit_username.setPlaceholderText("WebUI username")
        self._qbit_password = QLineEdit()
        self._qbit_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._qbit_password.setPlaceholderText("WebUI password")
        self._qbit_category = QLineEdit()
        self._qbit_category.setPlaceholderText("vaultseek")
        self._qbit_save_path = QLineEdit()
        self._qbit_save_path.setPlaceholderText("Optional save path (blank = qBittorrent default)")
        self._sab_enabled = QCheckBox("Enable SABnzbd downloads (Usenet / NZB)")
        self._sab_url = QLineEdit()
        self._sab_url.setPlaceholderText("http://127.0.0.1:8080")
        self._sab_key = QLineEdit()
        self._sab_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._sab_key.setPlaceholderText("SABnzbd API key (Config → General)")
        self._sab_category = QLineEdit()
        self._sab_category.setPlaceholderText("vaultseek")
        form.addRow(self._prowlarr_enabled)
        form.addRow("Prowlarr URL", self._prowlarr_url)
        form.addRow("Prowlarr API key", self._prowlarr_key)
        form.addRow("Minimum torrent seeders", self._prowlarr_seeders)
        form.addRow(self._qbit_enabled)
        form.addRow("qBittorrent URL", self._qbit_url)
        form.addRow("qBittorrent user", self._qbit_username)
        form.addRow("qBittorrent password", self._qbit_password)
        form.addRow("qBittorrent category", self._qbit_category)
        form.addRow("qBittorrent save path", self._qbit_save_path)
        form.addRow(self._sab_enabled)
        form.addRow("SABnzbd URL", self._sab_url)
        form.addRow("SABnzbd API key", self._sab_key)
        form.addRow("SABnzbd category", self._sab_category)
        test_row = QHBoxLayout()
        test_prowlarr = QPushButton("Test Prowlarr")
        test_prowlarr.setProperty("secondary", True)
        test_prowlarr.clicked.connect(self._test_prowlarr)
        test_qbit = QPushButton("Test qBittorrent")
        test_qbit.setProperty("secondary", True)
        test_qbit.clicked.connect(self._test_qbittorrent)
        test_sab = QPushButton("Test SABnzbd")
        test_sab.setProperty("secondary", True)
        test_sab.clicked.connect(self._test_sabnzbd)
        test_row.addWidget(test_prowlarr)
        test_row.addWidget(test_qbit)
        test_row.addWidget(test_sab)
        test_row.addStretch(1)
        form.addRow(test_row)
        help_label = QLabel(
            "Enable Prowlarr plus at least one download client. Torrents go to "
            "qBittorrent; NZBs go to SABnzbd. Completed downloads are verified and "
            "imported like Nicotine+. Prefer qBittorrent on port 8081 if SABnzbd "
            "already uses 8080."
        )
        help_label.setWordWrap(True)
        help_label.setProperty("muted", True)
        form.addRow(help_label)
        return box

    # ------------------------------------------------------------- lifecycle --
    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id

    def refresh(self) -> None:
        rec = self._container.config.recommendations
        enabled = set(rec.enabled_recommenders)
        self._lastfm_enabled.setChecked("lastfm_similar" in enabled)
        self._lastfm_api_key.setText(rec.lastfm.api_key)
        self._lastfm_similar.setValue(int(rec.lastfm.similar_artist_limit))
        self._lastfm_albums.setValue(int(rec.lastfm.top_albums_per_artist))
        self._spotify_enabled.setChecked("spotify_playlists" in enabled)
        self._spotify_client_id.setText(rec.spotify.client_id)
        self._spotify_client_secret.setText(rec.spotify.client_secret)
        self._spotify_playlists.setPlainText("\n".join(rec.spotify.playlist_urls))

        acq = self._container.config.acquisition
        self._prowlarr_enabled.setChecked(acq.prowlarr.enabled)
        self._prowlarr_url.setText(acq.prowlarr.base_url)
        self._prowlarr_key.setText(acq.prowlarr.api_key)
        self._prowlarr_seeders.setValue(int(acq.prowlarr.min_seeders))
        self._qbit_enabled.setChecked(acq.qbittorrent.enabled)
        self._qbit_url.setText(acq.qbittorrent.base_url)
        self._qbit_username.setText(acq.qbittorrent.username)
        self._qbit_password.setText(acq.qbittorrent.password)
        self._qbit_category.setText(acq.qbittorrent.category)
        self._qbit_save_path.setText(acq.qbittorrent.save_path)
        self._sab_enabled.setChecked(acq.sabnzbd.enabled)
        self._sab_url.setText(acq.sabnzbd.base_url)
        self._sab_key.setText(acq.sabnzbd.api_key)
        self._sab_category.setText(acq.sabnzbd.category)

    # --------------------------------------------------------------- actions --
    def _collect_recommendations(self) -> RecommendationConfig:
        enabled: list[str] = []
        if self._lastfm_enabled.isChecked():
            enabled.append("lastfm_similar")
        if self._spotify_enabled.isChecked():
            enabled.append("spotify_playlists")
        playlists = tuple(
            line.strip()
            for line in self._spotify_playlists.toPlainText().splitlines()
            if line.strip()
        )
        return replace(
            self._container.config.recommendations,
            enabled_recommenders=tuple(enabled),
            lastfm=LastfmConfig(
                enabled=self._lastfm_enabled.isChecked(),
                api_key=self._lastfm_api_key.text().strip(),
                similar_artist_limit=int(self._lastfm_similar.value()),
                top_albums_per_artist=int(self._lastfm_albums.value()),
            ),
            spotify=SpotifyConfig(
                enabled=self._spotify_enabled.isChecked(),
                client_id=self._spotify_client_id.text().strip(),
                client_secret=self._spotify_client_secret.text().strip(),
                playlist_urls=playlists,
            ),
        )

    def _collect_acquisition(self) -> AcquisitionConfig:
        acq = self._container.config.acquisition
        prowlarr = ProwlarrConfig(
            enabled=self._prowlarr_enabled.isChecked(),
            base_url=self._prowlarr_url.text().strip() or "http://127.0.0.1:9696",
            api_key=self._prowlarr_key.text().strip(),
            categories=acq.prowlarr.categories,
            min_seeders=int(self._prowlarr_seeders.value()),
        )
        qbittorrent = QbittorrentConfig(
            enabled=self._qbit_enabled.isChecked(),
            base_url=self._qbit_url.text().strip() or "http://127.0.0.1:8081",
            username=self._qbit_username.text().strip(),
            password=self._qbit_password.text(),
            category=self._qbit_category.text().strip() or "vaultseek",
            save_path=self._qbit_save_path.text().strip(),
        )
        sabnzbd = SabnzbdConfig(
            enabled=self._sab_enabled.isChecked(),
            base_url=self._sab_url.text().strip() or "http://127.0.0.1:8080",
            api_key=self._sab_key.text().strip(),
            category=self._sab_category.text().strip() or "vaultseek",
        )
        enabled = [
            p
            for p in acq.enabled_providers
            if p not in ("stub", "prowlarr", "prowlarr_qbit")
        ]
        if prowlarr.enabled and (qbittorrent.enabled or sabnzbd.enabled):
            enabled.append("prowlarr")
        if not enabled:
            enabled = ["stub"]
        order = ["prowlarr" if p == "prowlarr_qbit" else p for p in acq.provider_order]
        if "prowlarr" not in order:
            order = ["prowlarr", *order]
        return replace(
            acq,
            enabled_providers=tuple(dict.fromkeys(enabled)),
            provider_order=tuple(dict.fromkeys(order)),
            prowlarr=prowlarr,
            qbittorrent=qbittorrent,
            sabnzbd=sabnzbd,
        )

    def _save(self) -> None:
        recommendations = self._collect_recommendations()
        acquisition = self._collect_acquisition()
        updated = replace(
            self._container.config,
            recommendations=recommendations,
            acquisition=acquisition,
        )
        save_config(updated, self._container.paths.config_file)
        self._container.config = updated
        # Reconnect providers and rebuild recommenders so changes apply live.
        connect_acquisition_providers(acquisition, self._container.provider_manager)
        self._container.acquisition_automation_service.set_acquisition_config(acquisition)
        self._container.recommendation_service = RecommendationService(
            acquisition_engine=self._container.acquisition_engine,
            artist_repo=self._container.artist_repo,
            album_repo=self._container.album_repo,
            recommenders=_build_recommenders(recommendations),
            max_new_per_run=recommendations.max_new_per_run,
        )
        QMessageBox.information(
            self,
            "Plugins",
            "Plugin settings saved. Restart VaultSeek so torrent downloads and "
            "search fully take effect.",
        )

    def _run_recommendations(self) -> None:
        if self._library_id is None:
            QMessageBox.warning(self, "Plugins", "Select a library first.")
            return
        service = self._container.recommendation_service
        if not any(r.is_configured() for r in service.available_recommenders()):
            QMessageBox.information(
                self,
                "Plugins",
                "No recommenders are enabled and configured. Enable Last.fm or "
                "Spotify above, fill in credentials, and Save first.",
            )
            return
        library_id = self._library_id
        self._run_btn.setEnabled(False)
        self._run_status.setText("Finding recommendations…")

        run_in_background(
            lambda: service.run(library_id),
            on_finished=self._on_recommendations_done,
            on_failed=self._on_recommendations_failed,
        )

    def _on_recommendations_done(self, result: object) -> None:
        self._run_btn.setEnabled(True)
        added = getattr(result, "added", 0)
        owned = getattr(result, "skipped_owned", 0)
        duplicate = getattr(result, "skipped_duplicate", 0)
        errors = getattr(result, "errors", {}) or {}
        message = (
            f"Added {added} new Wishlist entr{'y' if added == 1 else 'ies'} "
            f"({owned} already owned, {duplicate} already listed)."
        )
        if errors:
            message += "\n\nSome recommenders reported errors:\n" + "\n".join(
                f"• {name}: {err}" for name, err in errors.items()
            )
        self._run_status.setText(message)
        QMessageBox.information(self, "Recommendations", message)

    def _on_recommendations_failed(self, error: str) -> None:
        self._run_btn.setEnabled(True)
        self._run_status.setText("")
        QMessageBox.warning(self, "Recommendations", f"Could not run recommenders:\n{error}")

    def _test_prowlarr(self) -> None:
        client = ProwlarrClient(
            base_url=self._prowlarr_url.text().strip() or "http://127.0.0.1:9696",
            api_key=self._prowlarr_key.text().strip(),
        )
        if client.probe():
            QMessageBox.information(self, "Prowlarr", "Connected to Prowlarr.")
        else:
            QMessageBox.warning(
                self,
                "Prowlarr",
                "Could not reach Prowlarr. Check the URL and API key "
                "(Prowlarr → Settings → General → API Key).",
            )

    def _test_qbittorrent(self) -> None:
        client = QbittorrentClient(
            base_url=self._qbit_url.text().strip() or "http://127.0.0.1:8081",
            username=self._qbit_username.text().strip(),
            password=self._qbit_password.text(),
        )
        if client.probe():
            QMessageBox.information(self, "qBittorrent", "Logged in to qBittorrent WebUI.")
        else:
            QMessageBox.warning(
                self,
                "qBittorrent",
                "Could not log in. Enable the qBittorrent WebUI "
                "(Tools → Options → Web UI), use a free port (e.g. 8081 if "
                "SABnzbd owns 8080), and check the URL/credentials.",
            )

    def _test_sabnzbd(self) -> None:
        client = SabnzbdClient(
            base_url=self._sab_url.text().strip() or "http://127.0.0.1:8080",
            api_key=self._sab_key.text().strip(),
        )
        if client.probe():
            QMessageBox.information(self, "SABnzbd", "Connected to SABnzbd.")
        else:
            QMessageBox.warning(
                self,
                "SABnzbd",
                "Could not reach SABnzbd. Check the URL and API key "
                "(SABnzbd → Config → General → API Key).",
            )

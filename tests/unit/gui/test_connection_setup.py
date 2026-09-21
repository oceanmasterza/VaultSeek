"""Protect configuration round trips and non-blocking diagnostic interactions."""

from dataclasses import replace
from threading import Event

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QLineEdit, QMessageBox

from vaultseek.core.config import AcoustIdEndpointConfig, load_config
from vaultseek.gui.user_help import HelpDialog
from vaultseek.gui.views.plugins_page import PluginsPage
from vaultseek.gui.views.settings_page import SettingsPage


def test_all_acoustid_rows_survive_save(qtbot, container, monkeypatch):
    endpoints = tuple(
        AcoustIdEndpointConfig(api_key=f"key-{i}", label=f"Account {i}") for i in range(5)
    )
    container.config = replace(
        container.config, metadata=replace(container.config.metadata, acoustid_endpoints=endpoints)
    )
    page = SettingsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    assert len(page._acoustid_rows) == 5
    page._add_acoustid_row()
    page._acoustid_rows[-1][1].setText("sixth")
    assert page._acoustid_rows[0][1].text() == "key-0"
    assert page._acoustid_rows[0][2].echoMode() == QLineEdit.EchoMode.Password
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    monkeypatch.setattr(
        "vaultseek.gui.views.settings_page.connect_acquisition_providers", lambda *a: None
    )
    page._save_preferences()
    from PySide6.QtCore import QThreadPool

    button = page._save_prefs_button
    assert button is not None
    qtbot.waitUntil(lambda: button.isEnabled(), timeout=5000)
    QThreadPool.globalInstance().waitForDone(5000)
    saved = load_config(container.paths.config_file)
    assert len(saved.metadata.acoustid_endpoints) == 6
    assert saved.metadata.acoustid_endpoints[:5] == endpoints
    assert saved.acquisition.prowlarr == container.config.acquisition.prowlarr


def test_pipeline_worker_counts_survive_save(qtbot, container, monkeypatch):
    page = SettingsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    page._hash_processes.setValue(4)
    page._metadata_threads.setValue(6)
    page._scanner_threads.setValue(2)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    monkeypatch.setattr(
        "vaultseek.gui.views.settings_page.connect_acquisition_providers", lambda *a: None
    )
    page._save_preferences()
    from PySide6.QtCore import QThreadPool

    button = page._save_prefs_button
    assert button is not None
    qtbot.waitUntil(lambda: button.isEnabled(), timeout=5000)
    QThreadPool.globalInstance().waitForDone(5000)
    saved = load_config(container.paths.config_file)
    assert saved.pipeline.hash_worker_processes == 4
    assert saved.pipeline.metadata_worker_threads == 6
    assert saved.pipeline.scanner_worker_threads == 2
    assert saved.acquisition.prowlarr == container.config.acquisition.prowlarr


def test_dashboard_music_tools_uses_waterfall_ids(qtbot, container, monkeypatch):
    from vaultseek.gui.views.dashboard_page import DashboardPage

    container.config = replace(
        container.config,
        acquisition=replace(
            container.config.acquisition,
            nicotine_plus=replace(container.config.acquisition.nicotine_plus, enabled=True),
            prowlarr=replace(container.config.acquisition.prowlarr, enabled=True),
            sabnzbd=replace(container.config.acquisition.sabnzbd, enabled=True),
        ),
        metadata=replace(container.config.metadata, discogs_user_token="discogs-secret-xyz"),
    )
    monkeypatch.setattr(
        container.provider_manager,
        "connected_provider_ids",
        lambda: ("usenet", "nicotine_plus"),
    )
    monkeypatch.setattr(container.connection_checks, "probe_dashboard_clients", lambda _config: {})
    page = DashboardPage(container)
    qtbot.addWidget(page)
    page.refresh()
    tiles = page._status_tiles
    assert tiles["Nicotine+"].status().state == "connected"
    assert tiles["Prowlarr"].status().state == "connected"
    assert tiles["SABnzbd"].status().state == "configured"
    assert tiles["NZBGet"].status().state == "off"
    blob = " ".join(tile.toolTip() for tile in tiles.values())
    assert "discogs-secret-xyz" not in blob
    assert "Connected — Usenet" not in blob


def test_download_test_keeps_ui_event_loop_running(qtbot, container, monkeypatch):
    page = PluginsPage(container)
    qtbot.addWidget(page)
    release = Event()
    completed = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: completed.append(True))
    try:
        page._test_connection("Test", lambda: release.wait(5), "Failure")
        assert not page._test_buttons[0].isEnabled()
        # Non-credential edit keeps the UI responsive while the probe waits.
        page._lastfm_similar.setValue(11)
        qtbot.wait(30)
        assert not completed
        release.set()
        qtbot.waitUntil(lambda: bool(completed), timeout=3000)
        assert page._test_buttons[0].isEnabled()
    finally:
        release.set()
        QThreadPool.globalInstance().waitForDone(6000)


def test_download_test_drops_stale_dialog_when_credentials_change(qtbot, container, monkeypatch):
    page = PluginsPage(container)
    qtbot.addWidget(page)
    release = Event()
    completed = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: completed.append(True))
    try:
        page._test_connection("Test", lambda: release.wait(5), "Failure")
        page._prowlarr_url.setText("http://edited-during-probe")
        release.set()
        qtbot.waitUntil(lambda: page._test_buttons[0].isEnabled(), timeout=3000)
        assert not completed
    finally:
        release.set()
        QThreadPool.globalInstance().waitForDone(6000)


def test_help_search_wraps_and_reports_missing(qtbot):
    dialog = HelpDialog(topic="connection-setup")
    qtbot.addWidget(dialog)
    dialog._search.setText("AcoustID")
    dialog._find()
    assert dialog._browser.textCursor().selectedText().lower() == "acoustid"
    dialog._search.setText("no-such-setting-123456")
    dialog._find()
    assert dialog._search_status.text() == "No match"

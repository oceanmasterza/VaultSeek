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
    saved = load_config(container.paths.config_file)
    assert len(saved.metadata.acoustid_endpoints) == 6
    assert saved.metadata.acoustid_endpoints[:5] == endpoints
    assert saved.acquisition.prowlarr == container.config.acquisition.prowlarr


def test_download_test_keeps_ui_event_loop_running(qtbot, container, monkeypatch):
    page = PluginsPage(container)
    qtbot.addWidget(page)
    release = Event()
    completed = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: completed.append(True))
    try:
        page._test_connection("Test", lambda: release.wait(5), "Failure")
        assert not page._test_buttons[0].isEnabled()
        # This edit is handled while the network stand-in is still waiting.
        page._prowlarr_url.setText("http://edited")
        qtbot.wait(30)
        assert not completed
        release.set()
        qtbot.waitUntil(lambda: bool(completed), timeout=3000)
        assert page._test_buttons[0].isEnabled()
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

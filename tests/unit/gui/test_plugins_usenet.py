"""Plugins owns NZBGet fields and keeps test buttons readable when narrow."""

from dataclasses import replace

from PySide6.QtWidgets import QMessageBox

from vaultseek.core.config import load_config
from vaultseek.gui.views.plugins_page import PluginsPage


def test_plugin_save_selects_nzbget_without_wiping_sab(qtbot, container, monkeypatch) -> None:
    container.config = replace(
        container.config,
        acquisition=replace(
            container.config.acquisition,
            nicotine_plus=replace(container.config.acquisition.nicotine_plus, password="soul-keep"),
            sabnzbd=replace(container.config.acquisition.sabnzbd, api_key="sab-keep", enabled=True),
        ),
    )
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    page._prowlarr_enabled.setChecked(True)
    page._prowlarr_key.setText("prowlarr-key")
    page._nzb_enabled.setChecked(True)
    page._nzb_username.setText("control")
    page._nzb_password.setText("hidden")
    page._usenet_client.setCurrentIndex(page._usenet_client.findData("nzbget"))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(
        "vaultseek.gui.views.plugins_page.connect_acquisition_providers", lambda *args: None
    )
    page._save()
    qtbot.waitUntil(lambda: page._save_btn.isEnabled(), timeout=3000)
    saved = load_config(container.paths.config_file)
    assert saved.acquisition.sabnzbd.api_key == "sab-keep"
    assert saved.acquisition.nicotine_plus.password == "soul-keep"
    assert saved.acquisition.nzbget.username == "control"
    assert saved.acquisition.nzbget.password == "hidden"
    assert saved.acquisition.usenet_download_client == "nzbget"
    assert "usenet" in saved.acquisition.enabled_providers
    assert "nzbget" not in saved.acquisition.provider_order


def test_plugin_test_buttons_stay_fully_visible_when_narrow(qtbot, container) -> None:
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.resize(320, 900)
    page.show()
    qtbot.wait(50)
    assert page._test_buttons
    for button in page._test_buttons:
        assert button.text()
        assert button.width() >= button.sizeHint().width()
        assert button.height() >= button.sizeHint().height()
        origin = button.mapTo(page, button.rect().topLeft())
        assert origin.x() >= 0
        assert origin.y() >= 0
        assert origin.x() + button.width() <= page.width() + 1

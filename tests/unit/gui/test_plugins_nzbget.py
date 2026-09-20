"""Plugins NZBGet fields stay on this page and action buttons keep their labels."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QMessageBox

from vaultseek.core.config import NicotinePlusConfig, SabnzbdConfig, load_config
from vaultseek.gui.views.plugins_page import PluginsPage
from vaultseek.gui.widgets.flow_host import FlowHost


def test_plugin_save_keeps_sab_and_nicotine_when_nzbget_is_selected(
    qtbot, container, monkeypatch
) -> None:
    container.config = replace(
        container.config,
        acquisition=replace(
            container.config.acquisition,
            sabnzbd=SabnzbdConfig(enabled=True, api_key="sab-keep", category="music"),
            nicotine_plus=NicotinePlusConfig(enabled=True, password="soul-keep"),
        ),
    )
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    page._prowlarr_enabled.setChecked(True)
    page._usenet_client.setCurrentIndex(page._usenet_client.findData("nzbget"))
    page._nzb_enabled.setChecked(True)
    page._nzb_username.setText("control")
    page._nzb_password.setText("hidden")
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(
        "vaultseek.gui.views.plugins_page.connect_acquisition_providers", lambda *args: None
    )
    page._save()
    saved = load_config(container.paths.config_file)
    assert saved.acquisition.usenet_download_client == "nzbget"
    assert saved.acquisition.nzbget.enabled is True
    assert saved.acquisition.nzbget.username == "control"
    assert saved.acquisition.sabnzbd.api_key == "sab-keep"
    assert saved.acquisition.sabnzbd.category == "music"
    assert saved.acquisition.nicotine_plus.password == "soul-keep"
    assert "usenet" in saved.acquisition.enabled_providers
    assert "hidden" not in repr(saved.acquisition.nzbget)


def test_nzbget_selected_without_enable_does_not_use_sab_as_fallback(
    qtbot, container, monkeypatch
) -> None:
    container.config = replace(
        container.config,
        acquisition=replace(
            container.config.acquisition,
            prowlarr=replace(container.config.acquisition.prowlarr, enabled=True),
            sabnzbd=SabnzbdConfig(enabled=True, api_key="sab-keep"),
        ),
    )
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    page._prowlarr_enabled.setChecked(True)
    page._sab_enabled.setChecked(True)
    page._usenet_client.setCurrentIndex(page._usenet_client.findData("nzbget"))
    page._nzb_enabled.setChecked(False)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(
        "vaultseek.gui.views.plugins_page.connect_acquisition_providers", lambda *args: None
    )
    page._save()
    saved = load_config(container.paths.config_file)
    assert "usenet" not in saved.acquisition.enabled_providers
    assert saved.acquisition.sabnzbd.api_key == "sab-keep"


def test_plugin_test_buttons_wrap_without_clipping_labels(qtbot, container) -> None:
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)
    bar = page._test_actions
    assert isinstance(bar, FlowHost)
    widest = max(button.sizeHint().width() for button in page._test_buttons)
    assert bar.heightForWidth(widest) > bar.heightForWidth(4000)
    for button in page._test_buttons:
        assert button.text()
        assert button.isEnabled()

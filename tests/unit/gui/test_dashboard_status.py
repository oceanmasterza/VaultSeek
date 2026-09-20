"""Dashboard integration tiles stay honest and usable when the window is narrow."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from vaultseek.gui.views.dashboard_page import DashboardPage

pytest.importorskip("pytestqt")


def test_status_tiles_navigation_and_narrow_layout(qtbot, container, monkeypatch) -> None:
    container.config = replace(
        container.config,
        acquisition=replace(
            container.config.acquisition,
            nicotine_plus=replace(container.config.acquisition.nicotine_plus, enabled=True),
            prowlarr=replace(container.config.acquisition.prowlarr, enabled=True),
            sabnzbd=replace(
                container.config.acquisition.sabnzbd, enabled=True, api_key="sab-secret"
            ),
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
    navigated: list[str] = []
    page.navigate_requested.connect(navigated.append)
    page.resize(420, 720)
    page.show()
    page.refresh()

    tiles = page._status_tiles
    assert tiles["Nicotine+"].status().state == "connected"
    assert tiles["Prowlarr"].status().state == "connected"
    assert tiles["SABnzbd"].status().state == "configured"
    assert tiles["NZBGet"].status().state == "off"
    assert tiles["NZBGet"].status().location == "plugins"
    assert tiles["Discogs"].status().location == "settings"
    assert "sab-secret" not in tiles["SABnzbd"].toolTip()
    assert "discogs-secret-xyz" not in tiles["Discogs"].toolTip()
    assert "Connected" in tiles["Nicotine+"].accessibleName()

    qtbot.mouseClick(tiles["NZBGet"], Qt.MouseButton.LeftButton)
    assert navigated[-1] == "plugins"
    tiles["AcoustID"].setFocus()
    qtbot.keyClick(tiles["AcoustID"], Qt.Key.Key_Space)
    assert navigated[-1] == "settings"

    qtbot.waitUntil(
        lambda: page._btn_force_scan.width() >= page._btn_force_scan.sizeHint().width() - 2,
        timeout=2000,
    )
    content_width = page._body.width()
    assert content_width <= 420
    for button in page.findChildren(QPushButton):
        assert button.text()
        assert button.width() + 2 >= button.sizeHint().width()
        assert button.x() + button.width() <= content_width + 8
    narrow = page._pipeline_kpi_host.heightForWidth(240)
    wide = page._pipeline_kpi_host.heightForWidth(960)
    assert narrow > wide
    assert page._tools_host.heightForWidth(240) > page._tools_host.heightForWidth(960)


def test_dashboard_applies_background_client_probes(qtbot, container, monkeypatch) -> None:
    import threading

    from PySide6.QtCore import QThreadPool

    from vaultseek.services.connection_status import (
        PROBE_PROWLARR,
        PROBE_QBITTORRENT,
        PROBE_SABNZBD,
    )

    container.config = replace(
        container.config,
        acquisition=replace(
            container.config.acquisition,
            nicotine_plus=replace(container.config.acquisition.nicotine_plus, enabled=True),
            prowlarr=replace(container.config.acquisition.prowlarr, enabled=True, api_key="p"),
            qbittorrent=replace(
                container.config.acquisition.qbittorrent, enabled=True, password="q"
            ),
            sabnzbd=replace(container.config.acquisition.sabnzbd, enabled=True, api_key="s"),
            provider_order=("nicotine_plus", "usenet", "prowlarr_public", "prowlarr_private"),
        ),
        metadata=replace(container.config.metadata, discogs_user_token="discogs-secret-xyz"),
    )
    order = container.config.acquisition.provider_order
    monkeypatch.setattr(
        container.provider_manager,
        "connected_provider_ids",
        lambda: ("nicotine_plus",),
    )
    calls = {"n": 0, "thread": None}

    def probe(_config: object) -> dict[str, bool]:
        calls["n"] += 1
        calls["thread"] = threading.current_thread()
        return {PROBE_SABNZBD: True, PROBE_PROWLARR: False, PROBE_QBITTORRENT: True}

    monkeypatch.setattr(container.connection_checks, "probe_dashboard_clients", probe)
    page = DashboardPage(container)
    qtbot.addWidget(page)
    try:
        page.refresh()
        qtbot.waitUntil(
            lambda: page._status_tiles["SABnzbd"].status().state == "connected",
            timeout=3000,
        )
        tiles = page._status_tiles
        assert calls["thread"] is not threading.current_thread()
        assert tiles["Prowlarr"].status().state == "failed"
        assert tiles["qBittorrent"].status().state == "connected"
        assert tiles["NZBGet"].status().state == "off"
        assert tiles["Nicotine+"].status().state == "connected"
        assert tiles["Discogs"].status().state == "configured"
        assert "Not live-checked" in tiles["Discogs"].toolTip()
        assert "discogs-secret-xyz" not in tiles["Discogs"].toolTip()
        assert container.config.acquisition.provider_order == order
        page.refresh()
        qtbot.wait(30)
        assert calls["n"] == 1
        page.refresh(reprobe=True)
        qtbot.waitUntil(lambda: calls["n"] == 2, timeout=3000)
    finally:
        QThreadPool.globalInstance().waitForDone(3000)


def test_dashboard_ignores_stale_probe_after_settings_change(qtbot, container, monkeypatch) -> None:
    from threading import Event

    from PySide6.QtCore import QThreadPool

    from vaultseek.services.connection_status import PROBE_SABNZBD

    container.config = replace(
        container.config,
        acquisition=replace(
            container.config.acquisition,
            sabnzbd=replace(
                container.config.acquisition.sabnzbd, enabled=True, api_key="first-key"
            ),
        ),
    )
    started = Event()
    release = Event()
    keys: list[str] = []

    def probe(config: object) -> dict[str, bool]:
        key = getattr(getattr(config, "sabnzbd", None), "api_key", "")
        keys.append(str(key))
        if key == "first-key":
            started.set()
            release.wait(5)
            return {PROBE_SABNZBD: True}
        return {PROBE_SABNZBD: False}

    monkeypatch.setattr(container.connection_checks, "probe_dashboard_clients", probe)
    page = DashboardPage(container)
    qtbot.addWidget(page)
    try:
        page.refresh()
        qtbot.waitUntil(lambda: started.is_set(), timeout=3000)
        page.refresh()
        assert keys == ["first-key"]
        container.config = replace(
            container.config,
            acquisition=replace(
                container.config.acquisition,
                sabnzbd=replace(
                    container.config.acquisition.sabnzbd, enabled=True, api_key="second-key"
                ),
            ),
        )
        page.refresh()
        assert page._status_tiles["SABnzbd"].status().state == "configured"
        release.set()
        qtbot.waitUntil(
            lambda: page._status_tiles["SABnzbd"].status().state == "failed",
            timeout=3000,
        )
        assert keys == ["first-key", "second-key"]
        assert "first-key" not in page._status_tiles["SABnzbd"].toolTip()
        assert "second-key" not in page._status_tiles["SABnzbd"].toolTip()
    finally:
        release.set()
        QThreadPool.globalInstance().waitForDone(3000)

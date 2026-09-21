"""Settings page save/reload, dirty edits, and non-blocking provider reconnect."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QMessageBox

from vaultseek.core.config import (
    ProwlarrConfig,
    SabnzbdConfig,
    load_config,
)
from vaultseek.core.container import Container
from vaultseek.gui.views.settings_page import SettingsPage
from vaultseek.models.entities.library import Library

pytest.importorskip("pytestqt")


def _wait_prefs_idle(qtbot, page: SettingsPage) -> None:
    button = page._save_prefs_button  # noqa: SLF001
    assert button is not None
    qtbot.waitUntil(lambda: button.isEnabled(), timeout=5000)
    QThreadPool.globalInstance().waitForDone(5000)


def test_save_preferences_reconnects_off_gui_thread(
    qtbot, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = SettingsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    release = Event()
    started = Event()
    edited: list[str] = []

    def slow_connect(*_args: object) -> None:
        started.set()
        release.wait(5)

    monkeypatch.setattr(
        "vaultseek.gui.views.settings_page.connect_acquisition_providers",
        slow_connect,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: edited.append("info"))
    page._wishlist_hours.setValue(6.0)  # noqa: SLF001
    page._save_preferences()  # noqa: SLF001
    assert (
        page._save_prefs_button is not None and not page._save_prefs_button.isEnabled()
    )  # noqa: SLF001
    qtbot.waitUntil(started.is_set, timeout=2000)
    # UI stays interactive while provider probes run.
    page._wishlist_hours.setValue(12.0)  # noqa: SLF001
    assert page._wishlist_hours.value() == 12.0  # noqa: SLF001
    assert not edited
    release.set()
    _wait_prefs_idle(qtbot, page)
    assert edited == ["info"]
    saved = load_config(container.paths.config_file)
    assert saved.acquisition.wishlist_search_interval_hours == 6.0


def test_dirty_preferences_survive_refresh(qtbot, container: Container) -> None:
    page = SettingsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    page._wishlist_hours.setValue(9.5)  # noqa: SLF001
    assert page._preferences_dirty is True  # noqa: SLF001
    page.refresh()
    assert page._wishlist_hours.value() == 9.5  # noqa: SLF001


def test_new_library_clears_media_server_form(
    qtbot, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    library = Library(
        id=uuid4(),
        name="A",
        incoming_path="C:/tmp/in",
        staging_path="C:/tmp/st",
        library_path="C:/tmp/lib",
        archive_path="C:/tmp/ar",
        created_at=now,
        updated_at=now,
    )
    container.library_repo.upsert(library)
    page = SettingsPage(container)
    qtbot.addWidget(page)
    page.set_library(library.id)
    page._ms_url.setText("https://navidrome.example")  # noqa: SLF001
    page._ms_username.setText("user")  # noqa: SLF001
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page._new_library()  # noqa: SLF001
    assert page._editing_id is None  # noqa: SLF001
    assert page._ms_url.text() == ""  # noqa: SLF001
    assert page._ms_username.text() == ""  # noqa: SLF001


def test_repeated_preference_save_keeps_plugins_credentials(
    qtbot, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    acquisition = replace(
        container.config.acquisition,
        prowlarr=ProwlarrConfig(enabled=True, base_url="http://prowlarr:9696", api_key="keep-me"),
        sabnzbd=SabnzbdConfig(enabled=True, base_url="http://sab:8080", api_key="sab-secret"),
    )
    container.config = replace(container.config, acquisition=acquisition)
    page = SettingsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(
        "vaultseek.gui.views.settings_page.connect_acquisition_providers",
        lambda *a, **k: None,
    )
    page._acq_threshold.setValue(0.55)  # noqa: SLF001
    page._save_preferences()  # noqa: SLF001
    _wait_prefs_idle(qtbot, page)
    page._theme.setCurrentText("light")  # noqa: SLF001
    page._save_preferences()  # noqa: SLF001
    _wait_prefs_idle(qtbot, page)
    saved = load_config(container.paths.config_file)
    assert saved.acquisition.prowlarr.api_key == "keep-me"
    assert saved.acquisition.sabnzbd.api_key == "sab-secret"
    assert saved.acquisition.auto_acquire_threshold == 0.55
    assert saved.theme == "light"


def test_detect_applies_to_form_without_saving(
    qtbot, container: Container, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from pathlib import Path

    from vaultseek.services.local_setup import LocalConnection

    page = SettingsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    original = container.config.acquisition.nicotine_plus.host
    connections = [
        LocalConnection(
            name="Nicotine+",
            source=Path(tmp_path / "nicotine"),
            values={"host": "10.9.8.7", "api_port": "12340", "api_token": "tok"},
            note="",
            listening=True,
        )
    ]

    class _Accepted:
        def exec(self) -> object:
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def selected(self) -> list[LocalConnection]:
            return connections

    monkeypatch.setattr(
        "vaultseek.gui.views.settings_page.LocalSetupDialog",
        lambda *a, **k: _Accepted(),
    )
    page._local_detected(connections)  # noqa: SLF001
    assert page._nicotine_host.text() == "10.9.8.7"  # noqa: SLF001
    assert page._nicotine_api_port.value() == 12340  # noqa: SLF001
    assert container.config.acquisition.nicotine_plus.host == original


def test_field_ranges_match_product_bounds(qtbot, container: Container) -> None:
    page = SettingsPage(container)
    qtbot.addWidget(page)
    assert page._threshold.minimum() == 0.0  # noqa: SLF001
    assert page._threshold.maximum() == 1.0  # noqa: SLF001
    assert page._acq_threshold.minimum() == 0.0  # noqa: SLF001
    assert page._acq_threshold.maximum() == 1.0  # noqa: SLF001
    assert page._wishlist_hours.maximum() == 168.0  # noqa: SLF001
    assert page._search_delay.maximum() == 300.0  # noqa: SLF001
    assert page._nicotine_port.minimum() == 1  # noqa: SLF001
    assert page._nicotine_api_port.minimum() == 1024  # noqa: SLF001
    assert page._fingerprint_sample_min.maximum() == 20  # noqa: SLF001
    assert page._hash_processes.minimum() == 0  # noqa: SLF001
    assert page._metadata_threads.minimum() == 1  # noqa: SLF001
    assert page._scanner_threads.maximum() == 8  # noqa: SLF001


def test_media_plugin_switch_confirms_before_discard(
    qtbot, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    library = Library(
        id=uuid4(),
        name="A",
        incoming_path="C:/tmp/in",
        staging_path="C:/tmp/st",
        library_path="C:/tmp/lib",
        archive_path="C:/tmp/ar",
        created_at=now,
        updated_at=now,
    )
    container.library_repo.upsert(library)
    page = SettingsPage(container)
    qtbot.addWidget(page)
    page.set_library(library.id)
    page._ms_plugin.setCurrentText("jellyfin")  # noqa: SLF001
    page._ms_url.setText("https://jellyfin.example")  # noqa: SLF001
    assert page._media_dirty is True  # noqa: SLF001
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_a, **_k: next(answers),
    )
    page._ms_plugin.setCurrentText("plex")  # noqa: SLF001
    assert page._ms_plugin.currentText() == "jellyfin"  # noqa: SLF001
    assert page._ms_url.text() == "https://jellyfin.example"  # noqa: SLF001
    page._ms_plugin.setCurrentText("plex")  # noqa: SLF001
    assert page._ms_plugin.currentText() == "plex"  # noqa: SLF001
    assert page._ms_url.text() == ""  # noqa: SLF001
    assert page._media_dirty is False  # noqa: SLF001


def test_baseline_settings_actions_still_reachable(qtbot, container: Container) -> None:
    """7125ee7 action inventory must remain reachable after simplification."""
    from PySide6.QtWidgets import QPushButton

    page = SettingsPage(container)
    qtbot.addWidget(page)
    labels = {button.text() for button in page.findChildren(QPushButton)}
    for required in (
        "Save library",
        "New library",
        "Save preferences",
        "Save media server",
        "Detect local Nicotine+ and media-server settings",
        "Test Nicotine+ connection",
        "Test media server connection",
        "Scan incoming now",
        "Move up",
        "Move down",
        "Add another account / connection",
        "Open data folder",
        "Open log folder",
        "Clear job & review queues",
        "Clear catalog records…",
    ):
        assert required in labels
    assert page._rules_page is not None  # noqa: SLF001

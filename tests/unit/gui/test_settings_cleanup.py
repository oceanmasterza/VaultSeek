"""Regression tests for Settings / wizard / dashboard cleanup."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from vaultseek.core.config import AcoustIdEndpointConfig, NicotinePlusConfig
from vaultseek.core.container import Container
from vaultseek.gui.theme import apply_theme
from vaultseek.gui.views.dashboard_page import DashboardPage
from vaultseek.gui.views.settings_page import SettingsPage
from vaultseek.gui.views.setup_wizard import SetupWizard
from vaultseek.gui.widgets.quality_fields import QualityFields
from vaultseek.services.quality_presets import PRESET_COLLECTOR

pytest.importorskip("pytestqt")


def test_settings_preserves_nicotine_username_password(
    qtbot, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    nicotine = NicotinePlusConfig(
        enabled=True,
        host="10.0.0.8",
        transport="socket",
        username="keep-user",
        password="keep-pass",
        api_token="tok",
    )
    container.config = replace(
        container.config,
        acquisition=replace(container.config.acquisition, nicotine_plus=nicotine),
    )
    page = SettingsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    monkeypatch.setattr(
        "vaultseek.gui.views.settings_page.QMessageBox.information",
        lambda *args, **kwargs: None,
    )
    page._save_preferences()  # noqa: SLF001
    saved = container.config.acquisition.nicotine_plus
    assert saved.username == "keep-user"
    assert saved.password == "keep-pass"
    assert saved.transport == "socket"
    assert saved.host == "10.0.0.8"


def test_wizard_writes_acoustid_endpoints(container: Container, tmp_path: Path) -> None:
    incoming = tmp_path / "Incoming"
    library = tmp_path / "Library"
    incoming.mkdir()
    library.mkdir()
    wizard = SetupWizard(container)
    wizard._folders.incoming.setText(str(incoming))  # noqa: SLF001
    wizard._folders.library.setText(str(library))  # noqa: SLF001
    wizard._tokens.acoustid.setText("fresh-key")  # noqa: SLF001
    wizard._persist()  # noqa: SLF001
    assert container.config.metadata.acoustid_api_key == "fresh-key"
    assert container.config.metadata.acoustid_endpoints
    assert container.config.metadata.acoustid_endpoints[0].api_key == "fresh-key"


def test_wizard_can_disable_nicotine(container: Container, tmp_path: Path) -> None:
    incoming = tmp_path / "Incoming"
    library = tmp_path / "Library"
    incoming.mkdir()
    library.mkdir()
    nicotine = NicotinePlusConfig(enabled=True, transport="socket", port=22025)
    container.config = replace(
        container.config,
        acquisition=replace(
            container.config.acquisition,
            enabled_providers=("nicotine_plus",),
            nicotine_plus=nicotine,
        ),
    )
    wizard = SetupWizard(container)
    wizard._folders.incoming.setText(str(incoming))  # noqa: SLF001
    wizard._folders.library.setText(str(library))  # noqa: SLF001
    wizard._nicotine.enabled.setChecked(False)  # noqa: SLF001
    wizard._persist()  # noqa: SLF001
    assert container.config.acquisition.nicotine_plus.enabled is False
    assert "nicotine_plus" not in container.config.acquisition.enabled_providers
    assert container.config.acquisition.nicotine_plus.transport == "socket"
    assert container.config.acquisition.nicotine_plus.port == 22025


def test_wizard_updates_existing_acoustid_endpoint(
    container: Container, tmp_path: Path
) -> None:
    incoming = tmp_path / "Incoming"
    library = tmp_path / "Library"
    incoming.mkdir()
    library.mkdir()
    container.config = replace(
        container.config,
        metadata=replace(
            container.config.metadata,
            acoustid_api_key="old",
            acoustid_endpoints=(
                AcoustIdEndpointConfig(api_key="old", proxy_url="http://proxy:1", label="A"),
            ),
        ),
    )
    wizard = SetupWizard(container)
    wizard._folders.incoming.setText(str(incoming))  # noqa: SLF001
    wizard._folders.library.setText(str(library))  # noqa: SLF001
    wizard._tokens.acoustid.setText("rotated")  # noqa: SLF001
    wizard._persist()  # noqa: SLF001
    endpoint = container.config.metadata.acoustid_endpoints[0]
    assert endpoint.api_key == "rotated"
    assert endpoint.proxy_url == "http://proxy:1"
    assert endpoint.label == "A"


def test_dashboard_does_not_edit_wishlist_hours(qtbot, container: Container) -> None:
    page = DashboardPage(container)
    qtbot.addWidget(page)
    page.refresh()
    assert not hasattr(page, "_wishlist_hours")
    assert "Settings" in page._wishlist_hint.text()  # noqa: SLF001


def test_quality_fields_load_collector(qapp) -> None:
    del qapp
    fields = QualityFields()
    fields.select_preset(PRESET_COLLECTOR)
    assert fields.preset_id() == PRESET_COLLECTOR
    assert fields.prefer_lossless.isChecked()
    assert fields.min_bitrate.value() == 320


def test_apply_theme_light_covers_forms(qapp) -> None:
    apply_theme(qapp, "light")
    sheet = qapp.styleSheet()
    assert "QGroupBox" in sheet
    assert "QSpinBox" in sheet
    assert "QTabBar" in sheet


def test_wishlist_cancel_requires_selection(
    qtbot, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from vaultseek.gui.views.acquisition_page import AcquisitionPage

    page = AcquisitionPage(container)
    qtbot.addWidget(page)
    page._job_ids = [uuid4()]  # noqa: SLF001
    cancelled: list[object] = []
    monkeypatch.setattr(
        container.acquisition_engine,
        "cancel",
        lambda job_id: cancelled.append(job_id),
    )
    monkeypatch.setattr(
        "vaultseek.gui.views.acquisition_page.QMessageBox.information",
        lambda *args, **kwargs: None,
    )
    page._cancel_selected()  # noqa: SLF001
    assert cancelled == []

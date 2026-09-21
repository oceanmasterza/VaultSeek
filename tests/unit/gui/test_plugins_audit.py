"""Plugins page audit: validation, credential preserve, async reconnect/tests."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QMessageBox

from vaultseek.core.config import (
    LastfmConfig,
    NicotinePlusConfig,
    RecommendationConfig,
    SabnzbdConfig,
    SpotifyConfig,
    load_config,
)
from vaultseek.gui.views.plugins_page import PluginsPage, _http_url_ok


def test_http_url_ok_accepts_defaults_and_rejects_junk() -> None:
    assert _http_url_ok("") is True
    assert _http_url_ok("http://127.0.0.1:9696") is True
    assert _http_url_ok("https://prowlarr.example/base") is True
    assert _http_url_ok("ftp://127.0.0.1:9696") is False
    assert _http_url_ok("not-a-url") is False
    assert _http_url_ok("", allow_empty=False) is False


def test_save_rejects_enabled_lastfm_without_key(qtbot, container, monkeypatch) -> None:
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    page._lastfm_enabled.setChecked(True)
    page._lastfm_api_key.clear()
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _p, _t, text: warnings.append(str(text)) or 0
    )
    monkeypatch.setattr(
        "vaultseek.gui.views.plugins_page.connect_acquisition_providers",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not reconnect")),
    )
    page._save()
    assert warnings
    assert "API key" in warnings[0]


def test_save_rejects_bad_prowlarr_url(qtbot, container, monkeypatch) -> None:
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    page._prowlarr_enabled.setChecked(True)
    page._prowlarr_url.setText("not-a-url")
    page._prowlarr_key.setText("key")
    page._qbit_enabled.setChecked(True)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _p, _t, text: warnings.append(str(text)) or 0
    )
    page._save()
    assert any("Prowlarr URL" in text for text in warnings)


def test_save_rejects_spotify_bad_playlist(qtbot, container, monkeypatch) -> None:
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    page._spotify_enabled.setChecked(True)
    page._spotify_client_id.setText("id")
    page._spotify_client_secret.setText("secret")
    page._spotify_playlists.setPlainText("https://example.com/not-a-playlist")
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _p, _t, text: warnings.append(str(text)) or 0
    )
    page._save()
    assert any("playlist" in text.casefold() for text in warnings)


def test_plugin_save_preserves_lastfm_spotify_and_nicotine(qtbot, container, monkeypatch) -> None:
    container.config = replace(
        container.config,
        recommendations=RecommendationConfig(
            enabled_recommenders=("lastfm_similar",),
            lastfm=LastfmConfig(
                enabled=True,
                api_key="lfm-keep",
                similar_artist_limit=7,
                top_albums_per_artist=3,
            ),
            spotify=SpotifyConfig(
                enabled=False,
                client_id="spot-id",
                client_secret="spot-secret",
                playlist_urls=("https://open.spotify.com/playlist/abc123",),
            ),
        ),
        acquisition=replace(
            container.config.acquisition,
            nicotine_plus=NicotinePlusConfig(enabled=True, password="soul-keep"),
            sabnzbd=SabnzbdConfig(enabled=True, api_key="sab-keep"),
        ),
    )
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    page._prowlarr_enabled.setChecked(True)
    page._prowlarr_key.setText("prowlarr-key")
    page._qbit_enabled.setChecked(True)
    page._qbit_password.setText("qbit-pass")
    page._spotify_enabled.setChecked(True)
    page._spotify_client_id.setText("spot-id")
    page._spotify_client_secret.setText("spot-secret")
    page._spotify_playlists.setPlainText("https://open.spotify.com/playlist/abc123")
    infos: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, _t, text: infos.append(str(text)) or 0
    )
    monkeypatch.setattr(
        "vaultseek.gui.views.plugins_page.connect_acquisition_providers", lambda *args: None
    )
    page._save()
    qtbot.waitUntil(lambda: page._save_btn.isEnabled(), timeout=3000)
    saved = load_config(container.paths.config_file)
    assert saved.recommendations.lastfm.api_key == "lfm-keep"
    assert saved.recommendations.lastfm.similar_artist_limit == 7
    assert saved.recommendations.spotify.client_secret == "spot-secret"
    assert saved.recommendations.spotify.playlist_urls == (
        "https://open.spotify.com/playlist/abc123",
    )
    assert saved.acquisition.nicotine_plus.password == "soul-keep"
    assert saved.acquisition.sabnzbd.api_key == "sab-keep"
    assert saved.acquisition.qbittorrent.password == "qbit-pass"
    assert "soul-keep" not in repr(infos)
    assert "spot-secret" not in repr(infos)
    assert "qbit-pass" not in repr(infos)


def test_save_reconnect_runs_off_gui_thread(qtbot, container, monkeypatch) -> None:
    import threading

    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    threads: list[str] = []

    def fake_connect(*_args: object, **_kwargs: object) -> None:
        threads.append(threading.current_thread().name)

    monkeypatch.setattr(
        "vaultseek.gui.views.plugins_page.connect_acquisition_providers", fake_connect
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    page._save()
    qtbot.waitUntil(lambda: bool(threads), timeout=3000)
    qtbot.waitUntil(lambda: page._save_btn.isEnabled(), timeout=3000)
    assert threads
    assert all(name != "MainThread" for name in threads)


def test_stale_connection_test_is_dropped_after_edit(qtbot, container, monkeypatch) -> None:
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.refresh()
    page._prowlarr_url.setText("http://127.0.0.1:9696")
    page._prowlarr_key.setText("key")
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, title, _t: shown.append(str(title)) or 0
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, title, _t: shown.append(str(title)) or 0)

    release = threading_event()

    def slow_probe() -> bool:
        release.wait(timeout=2.0)
        return True

    monkeypatch.setattr(
        container.connection_checks,
        "download",
        lambda name, config: slow_probe(),
    )
    page._test_prowlarr()
    page._prowlarr_url.setText("http://127.0.0.1:9697")
    release.set()
    qtbot.waitUntil(lambda: all(b.isEnabled() for b in page._test_buttons), timeout=3000)
    assert shown == []


def threading_event():  # type: ignore[no-untyped-def]
    import threading

    return threading.Event()


def test_spin_ranges_match_product_limits(qtbot, container) -> None:
    page = PluginsPage(container)
    qtbot.addWidget(page)
    assert page._lastfm_similar.minimum() == 1
    assert page._lastfm_similar.maximum() == 20
    assert page._lastfm_albums.minimum() == 1
    assert page._lastfm_albums.maximum() == 10
    assert page._prowlarr_seeders.minimum() == 0
    assert page._prowlarr_seeders.maximum() == 1000
    assert page._usenet_client.itemData(0) == "sabnzbd"
    assert page._usenet_client.itemData(1) == "nzbget"
    assert page._spotify_playlists.accessibleName() == "Playlists"
    assert page._lastfm_similar.accessibleName() == "Similar artists per seed"
    assert page._prowlarr_seeders.accessibleName() == "Minimum torrent seeders"


def test_numeric_fields_stay_compact_after_range_change(qtbot, container) -> None:
    page = PluginsPage(container)
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)
    box = page._prowlarr_seeders
    before = box.width()
    box.setRange(0, 9)
    from vaultseek.gui.widgets.numeric_fields import fit_numeric_spinbox

    fit_numeric_spinbox(box)
    assert box.width() <= before
    box.setRange(0, 100000)
    fit_numeric_spinbox(box)
    assert box.width() >= box.sizeHint().width() - 1
    assert box.width() < page.width() * 0.45

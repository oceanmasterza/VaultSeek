"""Smoke tests for Emby / Ampache / Koel / Funkwhale / Lyrion plugins."""

from __future__ import annotations

from uuid import UUID

import responses

from vaultseek.models.interfaces.media_server import MediaServerConfig
from vaultseek.plugins.builtin.ampache import AmpachePlugin
from vaultseek.plugins.builtin.emby import EmbyPlugin
from vaultseek.plugins.builtin.funkwhale import FunkwhalePlugin
from vaultseek.plugins.builtin.koel import KoelPlugin
from vaultseek.plugins.builtin.lyrion import LyrionPlugin

_LIB = UUID(int=1)


def _cfg(**kwargs: object) -> MediaServerConfig:
    base = {
        "library_id": _LIB,
        "plugin_id": "x",
        "server_url": "http://example.test",
        "token": "tok",
        "username": "user",
        "password": "pass",
    }
    base.update(kwargs)
    return MediaServerConfig(**base)  # type: ignore[arg-type]


@responses.activate
def test_emby_connect_and_rescan() -> None:
    responses.add(responses.GET, "http://example.test/System/Info/Public", status=200)
    responses.add(responses.POST, "http://example.test/Library/Refresh", status=204)
    plugin = EmbyPlugin()
    assert plugin.connect(_cfg(plugin_id="emby")) is True
    assert plugin.trigger_rescan() is True


@responses.activate
def test_koel_connect_via_overview() -> None:
    responses.add(responses.GET, "http://example.test/api/overview", json={}, status=200)
    responses.add(responses.POST, "http://example.test/api/sync", status=202)
    plugin = KoelPlugin()
    assert plugin.connect(_cfg(plugin_id="koel")) is True
    assert plugin.trigger_rescan() is True


@responses.activate
def test_funkwhale_instance_ping() -> None:
    responses.add(responses.GET, "http://example.test/api/v1/instance/", json={}, status=200)
    responses.add(
        responses.POST, "http://example.test/api/v1/manage/libraries/scan/", status=202
    )
    plugin = FunkwhalePlugin()
    assert plugin.connect(_cfg(plugin_id="funkwhale")) is True
    assert plugin.trigger_rescan() is True


@responses.activate
def test_lyrion_jsonrpc_version_and_rescan() -> None:
    responses.add(
        responses.POST,
        "http://example.test/jsonrpc.js",
        json={"result": {"_version": "9.0"}},
        status=200,
    )
    plugin = LyrionPlugin()
    assert plugin.connect(_cfg(plugin_id="lyrion", token="")) is True
    assert plugin.trigger_rescan() is True


@responses.activate
def test_ampache_uses_subsonic_ping() -> None:
    responses.add(
        responses.GET,
        "http://example.test/rest/ping.view",
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}},
        status=200,
    )
    responses.add(
        responses.GET,
        "http://example.test/rest/startScan.view",
        json={"subsonic-response": {"status": "ok"}},
        status=200,
    )
    plugin = AmpachePlugin()
    assert plugin.connect(_cfg(plugin_id="ampache")) is True
    assert plugin.trigger_rescan() is True

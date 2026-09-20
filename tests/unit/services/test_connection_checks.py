"""Connection checks validate credentials without adding downloads or rescanning."""

from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import responses

from vaultseek.core.config import AcquisitionConfig, NzbgetConfig, ProwlarrConfig, SabnzbdConfig
from vaultseek.models.interfaces.media_server import MediaServerConfig
from vaultseek.plugins.builtin.jellyfin import JellyfinPlugin
from vaultseek.services.connection_checks import ConnectionChecks
from vaultseek.services.connection_status import (
    PROBE_NZBGET,
    PROBE_PROWLARR,
    PROBE_QBITTORRENT,
    PROBE_SABNZBD,
)


@responses.activate
def test_sab_requires_authenticated_queue():
    config = replace(
        AcquisitionConfig(), sabnzbd=SabnzbdConfig(base_url="http://sab", api_key="key")
    )
    responses.get("http://sab/api", json={"version": "5"})
    assert not ConnectionChecks(lambda: []).download("SABnzbd", config)
    responses.replace(responses.GET, "http://sab/api", json={"queue": {"slots": []}})
    assert ConnectionChecks(lambda: []).download("SABnzbd", config)
    assert "mode=queue" in responses.calls[-1].request.url


@responses.activate
def test_nzbget_add_only_is_not_connected():
    from dataclasses import replace as dc_replace

    from vaultseek.core.config import NzbgetConfig

    config = dc_replace(
        AcquisitionConfig(),
        nzbget=NzbgetConfig(base_url="http://nzb", username="add", password="secret"),
    )
    responses.post("http://nzb/jsonrpc", json={"result": "26.3"})
    responses.post("http://nzb/jsonrpc", json={"error": {"message": "Access denied"}})
    checks = ConnectionChecks(lambda: [])
    assert checks.download("NZBGet", config) is False
    responses.post("http://nzb/jsonrpc", json={"result": "26.3"})
    responses.post("http://nzb/jsonrpc", json={"error": {"message": "Access denied"}})
    access = checks.nzbget_access(config)
    assert access.level == "add_only"
    assert "secret" not in access.message


def test_media_uses_disposable_instance_and_does_not_rescan():
    plugin = Mock(plugin_id="test")
    plugin.connect.return_value = True
    config = MediaServerConfig(library_id=uuid4(), plugin_id="test")
    assert ConnectionChecks(lambda: [plugin]).media(config)
    plugin.connect.assert_called_once_with(config)
    plugin.disconnect.assert_called_once()
    plugin.trigger_rescan.assert_not_called()


@responses.activate
def test_jellyfin_checks_authenticated_endpoint():
    responses.get("http://jelly/System/Info/Public", json={"ServerName": "Public"})
    responses.get("http://jelly/System/Info", status=401)
    config = MediaServerConfig(
        library_id=uuid4(), plugin_id="jellyfin", server_url="http://jelly", token="incorrect"
    )
    assert not ConnectionChecks(lambda: [JellyfinPlugin()]).media(config)
    assert responses.calls[-1].request.headers["X-Emby-Token"] == "incorrect"


def test_dashboard_probes_keep_clients_independent(monkeypatch) -> None:
    checks = ConnectionChecks(lambda: [])
    seen: list[str] = []

    def download(name: str, _config: AcquisitionConfig) -> bool:
        seen.append(name)
        if name == "Prowlarr":
            raise RuntimeError("down")
        if name == "qBittorrent":
            return True
        if name == "SABnzbd":
            return False
        raise AssertionError(name)

    monkeypatch.setattr(checks, "download", download)
    config = replace(
        AcquisitionConfig(),
        prowlarr=ProwlarrConfig(enabled=True, api_key="pkey"),
        qbittorrent=replace(AcquisitionConfig().qbittorrent, enabled=True, password="qpass"),
        sabnzbd=SabnzbdConfig(enabled=True, api_key="skey"),
    )
    result = checks.probe_dashboard_clients(config)
    assert seen == ["Prowlarr", "qBittorrent", "SABnzbd"]
    assert result[PROBE_PROWLARR] is False
    assert result[PROBE_QBITTORRENT] is True
    assert result[PROBE_SABNZBD] is False
    assert PROBE_NZBGET not in result


@responses.activate
def test_dashboard_probe_uses_read_only_endpoints_for_configured_clients() -> None:
    config = replace(
        AcquisitionConfig(),
        prowlarr=ProwlarrConfig(enabled=True, base_url="http://prowlarr", api_key="pkey"),
        sabnzbd=SabnzbdConfig(enabled=True, base_url="http://sab", api_key="skey"),
        nzbget=NzbgetConfig(enabled=False),
    )
    responses.get("http://prowlarr/api/v1/system/status", json={"version": "1"})
    responses.get("http://sab/api", json={"queue": {"slots": []}})
    result = ConnectionChecks(lambda: []).probe_dashboard_clients(config)
    assert result == {PROBE_PROWLARR: True, PROBE_SABNZBD: True}
    urls = [call.request.url for call in responses.calls]
    assert any(url.startswith("http://prowlarr/api/v1/system/status") for url in urls)
    assert any("mode=queue" in url for url in urls)
    assert not any("mode=addurl" in url or "/torrents/add" in url for url in urls)
    assert PROBE_NZBGET not in result
    assert PROBE_QBITTORRENT not in result

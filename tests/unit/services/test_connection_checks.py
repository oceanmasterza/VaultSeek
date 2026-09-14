"""Connection checks validate credentials without adding downloads or rescanning."""

from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import responses

from vaultseek.core.config import AcquisitionConfig, SabnzbdConfig
from vaultseek.models.interfaces.media_server import MediaServerConfig
from vaultseek.plugins.builtin.jellyfin import JellyfinPlugin
from vaultseek.services.connection_checks import ConnectionChecks


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

"""NZBGet discovery, connection classification, and Usenet enablement."""

from __future__ import annotations

import responses

from vaultseek.core.config import AcquisitionConfig, NzbgetConfig, ProwlarrConfig, SabnzbdConfig
from vaultseek.services.acquisition_bootstrap import resolve_enabled_acquisition_providers
from vaultseek.services.connection_checks import ConnectionChecks
from vaultseek.services.local_setup import LocalSetupService


def test_nzbget_conf_discovery_hides_password(tmp_path) -> None:
    path = tmp_path / "NZBGet" / "nzbget.conf"
    path.parent.mkdir()
    path.write_text(
        "\n".join(
            [
                "# ControlPassword must stay out of logs",
                "ControlIP=0.0.0.0",
                "ControlPort=6790",
                "SecureControl=no",
                "ControlUsername=vault",
                "ControlPassword=not-for-logs",
                "Category1.Name=vaultseek",
            ]
        ),
        encoding="utf-8",
    )
    service = LocalSetupService(
        roaming=tmp_path,
        local=tmp_path,
        program_data=tmp_path,
        port_probe=lambda _host, _port: False,
    )
    item = next(row for row in service.discover() if row.name == "NZBGet")
    assert item.values["url"] == "http://127.0.0.1:6790"
    assert item.values["username"] == "vault"
    assert item.values["password"] == "not-for-logs"
    assert item.values["category"] == "vaultseek"
    assert "not-for-logs" not in repr(item)
    before = path.read_bytes()
    service.discover()
    assert path.read_bytes() == before


def test_usenet_follows_selected_client_only() -> None:
    sab = AcquisitionConfig(
        prowlarr=ProwlarrConfig(enabled=True),
        sabnzbd=SabnzbdConfig(enabled=True),
        nzbget=NzbgetConfig(enabled=False),
        usenet_download_client="sabnzbd",
    )
    assert "usenet" in resolve_enabled_acquisition_providers(sab)
    switched = AcquisitionConfig(
        prowlarr=ProwlarrConfig(enabled=True),
        sabnzbd=SabnzbdConfig(enabled=True),
        nzbget=NzbgetConfig(enabled=False),
        usenet_download_client="nzbget",
    )
    assert "usenet" not in resolve_enabled_acquisition_providers(switched)
    nzb = AcquisitionConfig(
        prowlarr=ProwlarrConfig(enabled=True),
        sabnzbd=SabnzbdConfig(enabled=False),
        nzbget=NzbgetConfig(enabled=True),
        usenet_download_client="nzbget",
    )
    assert "usenet" in resolve_enabled_acquisition_providers(nzb)


@responses.activate
def test_connection_check_requires_queue_history() -> None:
    config = AcquisitionConfig(
        nzbget=NzbgetConfig(base_url="http://nzb", username="nzbget", password="secret")
    )

    def callback(request):  # noqa: ANN001
        import json

        data = json.loads(request.body)
        if data["method"] == "version":
            body = {"result": "26.3", "id": 1}
        else:
            body = {"error": {"code": 3, "message": "Access denied"}, "id": 1}
        return 200, {}, json.dumps(body)

    responses.add_callback(responses.POST, "http://nzb/jsonrpc", callback=callback)
    checks = ConnectionChecks(lambda: [])
    access = checks.nzbget_access(config)
    assert access.level == "add_only"
    assert access.ok is False
    assert checks.download("NZBGet", config) is False
    assert "append" not in "".join(
        (
            call.request.body.decode()
            if isinstance(call.request.body, bytes)
            else str(call.request.body)
        )
        for call in responses.calls
    )

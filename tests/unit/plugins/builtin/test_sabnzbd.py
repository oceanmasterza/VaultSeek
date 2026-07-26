"""Tests for the SABnzbd client."""

from __future__ import annotations

import responses

from vaultseek.plugins.builtin.sabnzbd import SabnzbdClient

_BASE = "http://sab:8080"


@responses.activate
def test_sabnzbd_probe_and_add_url() -> None:
    responses.add(
        responses.GET,
        f"{_BASE}/api",
        json={"version": "4.3.0"},
        match=[responses.matchers.query_param_matcher({"mode": "version"}, strict_match=False)],
    )
    responses.add(
        responses.GET,
        f"{_BASE}/api",
        json={"status": True, "nzo_ids": ["SABnzbd_nzo_abc"]},
        match=[responses.matchers.query_param_matcher({"mode": "addurl"}, strict_match=False)],
    )
    client = SabnzbdClient(_BASE, "key")
    assert client.probe() is True
    assert client.add_url("http://x/file.nzb", category="vaultseek") == "SABnzbd_nzo_abc"


@responses.activate
def test_sabnzbd_map_completed_from_history() -> None:
    responses.add(
        responses.GET,
        f"{_BASE}/api",
        json={"queue": {"slots": []}},
        match=[responses.matchers.query_param_matcher({"mode": "queue"}, strict_match=False)],
    )
    responses.add(
        responses.GET,
        f"{_BASE}/api",
        json={
            "history": {
                "slots": [
                    {
                        "nzo_id": "SABnzbd_nzo_abc",
                        "status": "Completed",
                        "name": "Album",
                        "storage": "C:/Downloads/complete/Album",
                    }
                ]
            }
        },
        match=[responses.matchers.query_param_matcher({"mode": "history"}, strict_match=False)],
    )
    client = SabnzbdClient(_BASE, "key")
    slot = client.find_slot("SABnzbd_nzo_abc")
    assert slot is not None
    mapped = client.map_status(slot)
    assert mapped.state == "completed"

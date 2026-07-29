"""Contract tests for the last-pull breadcrumb on /update/status (#357).

scripts/deploy/fleet-update.sh records which address families a device-side pull
tried; the endpoint surfaces it so a failed update is diagnosable without SSHing
into the device.

Run with:
    pytest tests/contract/test_update_pull_outcome.py -m contract -v
"""
import json

import pytest

from aquila_web import main as web_main


@pytest.mark.contract
def test_status_reports_no_pull_when_breadcrumb_absent(client, tmp_path, monkeypatch):
    """The normal case on a device that has never run a scripted update."""
    monkeypatch.setattr(web_main, "_PULL_OUTCOME_PATH", str(tmp_path / "missing.json"))

    assert client.get("/update/status").json()["last_pull"] is None


@pytest.mark.contract
def test_status_names_the_families_tried(client, tmp_path, monkeypatch):
    """The field case: IPv4 couldn't carry the transfer and IPv6 finished it."""
    path = tmp_path / "last_pull.json"
    path.write_text(
        json.dumps(
            {
                "result": "ok",
                "families_tried": "ipv4,ipv6",
                "detail": "IPv4 failed; completed over IPv6",
                "at": "2026-07-28T10:00:00Z",
            }
        )
    )
    monkeypatch.setattr(web_main, "_PULL_OUTCOME_PATH", str(path))

    last_pull = client.get("/update/status").json()["last_pull"]

    assert last_pull["families_tried"] == "ipv4,ipv6"
    assert last_pull["result"] == "ok"


@pytest.mark.contract
def test_status_survives_a_truncated_breadcrumb(client, tmp_path, monkeypatch):
    """A device killed mid-write must not break the endpoint the UI polls."""
    path = tmp_path / "last_pull.json"
    path.write_text('{"result":"ok","families_tr')
    monkeypatch.setattr(web_main, "_PULL_OUTCOME_PATH", str(path))

    response = client.get("/update/status")

    assert response.status_code == 200
    assert response.json()["last_pull"] is None


@pytest.mark.contract
def test_status_ignores_a_breadcrumb_that_is_not_an_object(client, tmp_path, monkeypatch):
    """Valid JSON of the wrong shape must not reach the UI as a pull outcome."""
    path = tmp_path / "last_pull.json"
    path.write_text('["not", "an", "object"]')
    monkeypatch.setattr(web_main, "_PULL_OUTCOME_PATH", str(path))

    assert client.get("/update/status").json()["last_pull"] is None

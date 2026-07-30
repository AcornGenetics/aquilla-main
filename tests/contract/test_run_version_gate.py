"""
Contract test: the run gate blocks an assay when the api/ui containers run
different builds (am#360 — the sn04 matched-pair invariant), and does not block
when they match.

Uses the FastAPI TestClient; the running container SHAs are injected via
_running_container_shas so the test controls the version state without hardware.
"""
import pytest

from aquila_web import main as web_main

pytestmark = pytest.mark.contract


def test_run_blocked_on_version_mismatch(client, monkeypatch):
    monkeypatch.setattr(web_main, "_running_container_shas", lambda: ("api-OLD", "ui-NEW"))

    body = client.post("/button/run").json()

    assert body["ok"] is False
    assert "match" in body["message"].lower()  # blocked for the version reason


def test_run_not_blocked_for_version_when_matched(client, monkeypatch):
    monkeypatch.setattr(web_main, "_running_container_shas", lambda: ("same-sha", "same-sha"))

    body = client.post("/button/run").json()

    # A matched pair is never blocked for a version reason (it may still fail an
    # unrelated precondition like "select a profile").
    assert "do not match" not in body.get("message", "").lower()

"""
Unit tests for run_complete event emission into the SQLite queue.

Behaviors tested:
  1. POST /events/run_complete enqueues exactly one run_complete event
  2. Event payload contains run_name and profile
  3. Event payload includes a non-empty result field
  4. state_requests.emit_run_complete() posts to the correct endpoint
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

# serial is a hardware-only package not installed in CI; stub it so that
# aq_lib.state_requests (which transitively imports config_module) can be
# imported without a physical device present.
for _hw_mod in ("serial", "serial.tools", "serial.tools.list_ports"):
    sys.modules.setdefault(_hw_mod, MagicMock())

# config_module.Config reads a hardware-specific host_config.json that maps
# device hostnames to hardware settings — not present on dev machines.
# Stub the whole module so Config() construction doesn't raise KeyError.
sys.modules.setdefault("aq_lib.config_module", MagicMock())

import pytest
from fastapi.testclient import TestClient

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures"
DETECTED_RESULTS = FIXTURES_DIR / "results" / "detected.json"


@pytest.fixture
def db_client(tmp_path, monkeypatch):
    """TestClient backed by an isolated, temporary SQLite DB."""
    db_path = tmp_path / "test_events.db"
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(db_path))
    from aquila_web import local_db, main as web_main
    local_db.init_local_db()
    with TestClient(web_main.app) as c:
        yield c, local_db


class TestRunCompleteEndpoint:
    """POST /events/run_complete stores an event in the SQLite queue."""

    def test_enqueues_run_complete_event(self, db_client):
        client, local_db = db_client
        response = client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(DETECTED_RESULTS),
        })
        assert response.status_code == 200
        events = local_db.get_pending_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "run_complete"

    def test_event_payload_has_run_name_and_profile(self, db_client):
        client, local_db = db_client
        client.post("/events/run_complete", json={
            "run_name": "Run 2",
            "profile": "hotstart.json",
            "results_path": str(DETECTED_RESULTS),
        })
        payload = local_db.get_pending_events()[0]["payload"]
        assert payload["run_name"] == "Run 2"
        assert payload["profile"] == "hotstart.json"

    def test_payload_carries_supplied_run_timestamp(self, db_client):
        client, local_db = db_client
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(DETECTED_RESULTS),
            "run_timestamp": "2026-07-02T14:03:11Z",
        })
        payload = local_db.get_pending_events()[0]["payload"]
        assert payload["run_timestamp"] == "2026-07-02T14:03:11Z"

    def test_payload_defaults_run_timestamp_when_omitted(self, db_client):
        client, local_db = db_client
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(DETECTED_RESULTS),
        })
        payload = local_db.get_pending_events()[0]["payload"]
        assert payload.get("run_timestamp")

    def test_event_payload_includes_non_empty_result(self, db_client):
        client, local_db = db_client
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(DETECTED_RESULTS),
        })
        payload = local_db.get_pending_events()[0]["payload"]
        assert payload.get("result")


class TestEmitRunComplete:
    """state_requests.emit_run_complete() calls the correct HTTP endpoint."""

    def test_posts_to_events_run_complete_endpoint(self, monkeypatch):
        import aq_lib.state_requests as sr

        calls = []

        class _FakeResponse:
            status_code = 200

        def fake_post(url, json=None, timeout=None):
            calls.append({"url": url, "json": json})
            return _FakeResponse()

        monkeypatch.setattr("aq_lib.state_requests.requests.post", fake_post)
        sr.emit_run_complete("Run 1", "basic_pcr.json", "/logs/results/run1.json")
        assert len(calls) == 1
        assert calls[0]["url"].endswith("/events/run_complete")
        assert calls[0]["json"]["run_name"] == "Run 1"
        assert calls[0]["json"]["profile"] == "basic_pcr.json"
        assert calls[0]["json"]["results_path"] == "/logs/results/run1.json"

    def test_forwards_canonical_run_timestamp(self, monkeypatch):
        import aq_lib.state_requests as sr

        calls = []

        class _FakeResponse:
            status_code = 200

        def fake_post(url, json=None, timeout=None):
            calls.append({"url": url, "json": json})
            return _FakeResponse()

        monkeypatch.setattr("aq_lib.state_requests.requests.post", fake_post)
        sr.emit_run_complete(
            "Run 1", "basic_pcr.json", "/logs/results/run1.json",
            run_timestamp="2026-07-02T14:03:11Z",
        )
        assert calls[0]["json"]["run_timestamp"] == "2026-07-02T14:03:11Z"

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

    def test_event_payload_carries_request_tube_names_keyed_to_well(self, db_client):
        client, local_db = db_client
        # The device snapshots tube names at run completion and sends them with
        # the event (#296), mirroring how run_name/run_timestamp are captured
        # with the run rather than re-read from live server state.
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(DETECTED_RESULTS),
            "tube_names": ["Patient A", "Patient B", "NTC", "Positive Ctrl"],
        })
        payload = local_db.get_pending_events()[0]["payload"]
        assert payload["sample_names"] == {
            "1": "Patient A",
            "2": "Patient B",
            "3": "NTC",
            "4": "Positive Ctrl",
        }
        # No regression: run_name still travels alongside the sample names.
        assert payload["run_name"] == "Run 1"

    def test_request_tube_names_win_over_live_global(self, db_client):
        client, local_db = db_client
        # The run's snapshot must win even if the shared global mutates between
        # run completion and enqueue (e.g. another client edits names, or a
        # reset fires). The event must ship the labels captured with the run.
        client.post("/tube_names", json={"names": ["STALE 1", "STALE 2", "STALE 3", "STALE 4"]})
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(DETECTED_RESULTS),
            "tube_names": ["Patient A", "Patient B", "NTC", "Positive Ctrl"],
        })
        payload = local_db.get_pending_events()[0]["payload"]
        assert payload["sample_names"]["1"] == "Patient A"
        assert payload["sample_names"]["3"] == "NTC"

    def test_defaults_sample_names_when_tube_names_omitted(self, db_client):
        client, local_db = db_client
        # Legacy/sim callers that don't send a snapshot fall back to the live
        # global, which defaults to "Tube 1".."Tube 4".
        client.post("/results/clear")
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(DETECTED_RESULTS),
        })
        payload = local_db.get_pending_events()[0]["payload"]
        assert payload["sample_names"] == {
            "1": "Tube 1",
            "2": "Tube 2",
            "3": "Tube 3",
            "4": "Tube 4",
        }


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

    def test_forwards_tube_names_snapshot(self, monkeypatch):
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
            tube_names=["Patient A", "Patient B", "NTC", "Positive Ctrl"],
        )
        assert calls[0]["json"]["tube_names"] == [
            "Patient A", "Patient B", "NTC", "Positive Ctrl",
        ]

"""
Unit tests for optics_readings outbox wiring (#288).

Behaviors tested:
  1. POST /events/optics_readings enqueues one optics_readings event whose
     payload is the frozen contract, carrying the supplied run_timestamp
  2. An aborted-with-no-capture request enqueues no event
  3. A path outside the optics log dir is rejected and enqueues no event
     (the endpoint is not an arbitrary-file read -> cloud exfil, #288 review)
  4. state_requests.emit_optics_readings() posts to the correct endpoint
"""
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock

# serial is hardware-only; stub so aq_lib.state_requests imports without a device.
for _hw_mod in ("serial", "serial.tools", "serial.tools.list_ports"):
    sys.modules.setdefault(_hw_mod, MagicMock())
sys.modules.setdefault("aq_lib.config_module", MagicMock())

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parents[1] / "fixtures" / "optics"
SAMPLE_LOG = FIXTURES / "sample.log"


@pytest.fixture
def db_client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_events.db"
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(db_path))
    from aquila_web import local_db, main as web_main
    # Confine reads to a temp optics dir and drop the shared fixture inside it.
    optics_dir = tmp_path / "logs" / "optics"
    optics_dir.mkdir(parents=True)
    monkeypatch.setattr(web_main, "OPTICS_LOG_DIR", optics_dir.resolve())
    shutil.copy(SAMPLE_LOG, optics_dir / "sample.log")
    local_db.init_local_db()
    with TestClient(web_main.app) as c:
        yield c, local_db, optics_dir


class TestOpticsReadingsEndpoint:
    def test_enqueues_optics_readings_with_run_timestamp(self, db_client):
        client, local_db, optics_dir = db_client
        response = client.post("/events/optics_readings", json={
            "optics_path": str(optics_dir / "sample.log"),
            "run_timestamp": "2026-07-02T14:03:11Z",
            "expected_lines": 960,
            "aborted": False,
        })
        assert response.status_code == 200
        events = local_db.get_pending_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "optics_readings"
        payload = events[0]["payload"]
        assert payload["run_timestamp"] == "2026-07-02T14:03:11Z"
        assert payload["filename"] == "sample.log"
        assert payload["line_count"] == 960
        assert payload["complete"] is True

    def test_aborted_with_no_capture_enqueues_no_event(self, db_client):
        client, local_db, optics_dir = db_client
        response = client.post("/events/optics_readings", json={
            "optics_path": str(optics_dir / "never_written.log"),
            "run_timestamp": "2026-07-02T14:03:11Z",
            "expected_lines": 960,
            "aborted": True,
        })
        assert response.status_code == 200
        assert response.json()["event_id"] is None
        assert local_db.get_pending_events() == []

    def test_rejects_path_outside_optics_dir(self, db_client, tmp_path):
        # The exfil case: a secret file outside logs/optics must not be read.
        client, local_db, _ = db_client
        secret = tmp_path / "device.env"
        secret.write_text("AQ_SYNC_CLIENT_KEY=super-secret")
        response = client.post("/events/optics_readings", json={
            "optics_path": str(secret),
            "run_timestamp": "2026-07-02T14:03:11Z",
            "expected_lines": 960,
            "aborted": False,
        })
        assert response.status_code == 400
        assert local_db.get_pending_events() == []


class TestEmitOpticsReadings:
    def test_posts_to_events_optics_readings_endpoint(self, monkeypatch):
        import aq_lib.state_requests as sr

        calls = []

        class _FakeResponse:
            status_code = 200

        def fake_post(url, json=None, timeout=None):
            calls.append({"url": url, "json": json})
            return _FakeResponse()

        monkeypatch.setattr("aq_lib.state_requests.requests.post", fake_post)
        sr.emit_optics_readings(
            "/logs/optics/run1.log",
            run_timestamp="2026-07-02T14:03:11Z",
            expected_lines=19680,
            aborted=False,
        )
        assert len(calls) == 1
        assert calls[0]["url"].endswith("/events/optics_readings")
        assert calls[0]["json"]["optics_path"] == "/logs/optics/run1.log"
        assert calls[0]["json"]["run_timestamp"] == "2026-07-02T14:03:11Z"
        assert calls[0]["json"]["expected_lines"] == 19680
        assert calls[0]["json"]["aborted"] is False

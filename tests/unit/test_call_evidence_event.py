"""
Unit tests for the summary call_evidence event emission (#297).

A call_evidence event is enqueued at Run completion ALONGSIDE run_complete (a
separate event type, as optics_readings is separate from run_complete), sharing
the Run's run_timestamp so both derive the same run_id cloud-side.

Behaviors tested:
  1. POST /events/run_complete enqueues a call_evidence event carrying the
     summary evidence records the analysis wrote to the results file.
  2. call_evidence.run_timestamp matches the run_complete run_timestamp.
  3. call_evidence carries an algo_version.
  4. A ROX-Unavailable results file yields fam-only evidence (no rox record).
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

# serial is hardware-only; stub so aq_lib.state_requests imports without a device.
for _hw_mod in ("serial", "serial.tools", "serial.tools.list_ports"):
    sys.modules.setdefault(_hw_mod, MagicMock())
sys.modules.setdefault("aq_lib.config_module", MagicMock())

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


# A results file exactly as Curve.results_to_json writes it: the "evidence" block
# holds the summary records, including a rox curve (well 1) whose engine verdict
# was Detected but whose final call was suppressed to Not Detected.
_RESULTS_WITH_EVIDENCE = {
    "1": {"1": "Detected", "2": "Not Detected", "3": "Not Detected", "4": "Not Detected"},
    "2": {"1": "Not Detected", "2": "Not Detected", "3": "Not Detected", "4": "Not Detected"},
    "cq": {"1": {"1": 22.5, "2": None, "3": None, "4": None},
           "2": {"1": None, "2": None, "3": None, "4": None}},
    "evidence": [
        {"well": 1, "channel": "fam", "raw_status": "Detected", "call": "Detected"},
        {"well": 2, "channel": "fam", "raw_status": "Not Detected", "call": "Not Detected"},
        {"well": 3, "channel": "fam", "raw_status": "Not Detected", "call": "Not Detected"},
        {"well": 4, "channel": "fam", "raw_status": "Not Detected", "call": "Not Detected"},
        {"well": 1, "channel": "rox", "raw_status": "Detected", "call": "Not Detected"},
        {"well": 2, "channel": "rox", "raw_status": "Not Detected", "call": "Not Detected"},
        {"well": 3, "channel": "rox", "raw_status": "Not Detected", "call": "Not Detected"},
        {"well": 4, "channel": "rox", "raw_status": "Not Detected", "call": "Not Detected"},
    ],
}

# A ROX-Unavailable run: only the fam channel ran a curve.
_RESULTS_ROX_UNAVAILABLE = {
    "1": {"1": "Detected", "2": "Not Detected", "3": "Not Detected", "4": "Not Detected"},
    "2": {"1": "ROX Unavailable", "2": "ROX Unavailable", "3": "ROX Unavailable", "4": "ROX Unavailable"},
    "cq": {"1": {"1": 22.5, "2": None, "3": None, "4": None},
           "2": {"1": None, "2": None, "3": None, "4": None}},
    "evidence": [
        {"well": 1, "channel": "fam", "raw_status": "Detected", "call": "Detected"},
        {"well": 2, "channel": "fam", "raw_status": "Not Detected", "call": "Not Detected"},
        {"well": 3, "channel": "fam", "raw_status": "Not Detected", "call": "Not Detected"},
        {"well": 4, "channel": "fam", "raw_status": "Not Detected", "call": "Not Detected"},
    ],
}


@pytest.fixture
def db_client(tmp_path, monkeypatch):
    """TestClient backed by an isolated, temporary SQLite DB."""
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "test_events.db"))
    from aquila_web import local_db, main as web_main
    local_db.init_local_db()
    with TestClient(web_main.app) as c:
        yield c, local_db


def _write_results(tmp_path, data) -> Path:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data))
    return path


def _events_of_type(local_db, event_type):
    return [e for e in local_db.get_pending_events() if e["event_type"] == event_type]


class TestCallEvidenceEmission:
    def test_run_completion_enqueues_a_call_evidence_event(self, db_client, tmp_path):
        client, local_db = db_client
        results = _write_results(tmp_path, _RESULTS_WITH_EVIDENCE)
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(results),
        })
        call_evidence = _events_of_type(local_db, "call_evidence")
        assert len(call_evidence) == 1
        payload = call_evidence[0]["payload"]
        # One summary record per evaluated Call (4 fam + 4 rox).
        assert len(payload["evidence"]) == 8
        assert all(r["call"] != "undetected" for r in payload["evidence"])

    def test_call_evidence_captures_rox_suppression_divergence(self, db_client, tmp_path):
        client, local_db = db_client
        results = _write_results(tmp_path, _RESULTS_WITH_EVIDENCE)
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(results),
        })
        payload = _events_of_type(local_db, "call_evidence")[0]["payload"]
        rox1 = next(r for r in payload["evidence"]
                    if r["channel"] == "rox" and r["well"] == 1)
        assert rox1["raw_status"] == "Detected"
        assert rox1["call"] == "Not Detected"

    def test_call_evidence_run_timestamp_matches_run_complete(self, db_client, tmp_path):
        client, local_db = db_client
        results = _write_results(tmp_path, _RESULTS_WITH_EVIDENCE)
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(results),
            "run_timestamp": "2026-07-02T14:03:11Z",
        })
        run_complete = _events_of_type(local_db, "run_complete")[0]["payload"]
        call_evidence = _events_of_type(local_db, "call_evidence")[0]["payload"]
        assert call_evidence["run_timestamp"] == run_complete["run_timestamp"]
        assert call_evidence["run_timestamp"] == "2026-07-02T14:03:11Z"

    def test_call_evidence_carries_algo_version(self, db_client, tmp_path):
        client, local_db = db_client
        results = _write_results(tmp_path, _RESULTS_WITH_EVIDENCE)
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(results),
        })
        payload = _events_of_type(local_db, "call_evidence")[0]["payload"]
        assert payload.get("algo_version")

    def test_rox_unavailable_run_emits_fam_only_evidence(self, db_client, tmp_path):
        client, local_db = db_client
        results = _write_results(tmp_path, _RESULTS_ROX_UNAVAILABLE)
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(results),
        })
        payload = _events_of_type(local_db, "call_evidence")[0]["payload"]
        assert {r["channel"] for r in payload["evidence"]} == {"fam"}
        assert all(r["call"] != "ROX Unavailable" for r in payload["evidence"])

    def test_results_without_evidence_enqueues_no_call_evidence(self, db_client, tmp_path):
        # A legacy results file with no evidence block must not enqueue an empty
        # call_evidence event (mirrors optics_readings skipping an empty capture).
        client, local_db = db_client
        legacy = {"1": {"1": "Detected"}, "2": {"1": "Not Detected"}}
        results = _write_results(tmp_path, legacy)
        client.post("/events/run_complete", json={
            "run_name": "Run 1",
            "profile": "basic_pcr.json",
            "results_path": str(results),
        })
        assert _events_of_type(local_db, "run_complete")  # run_complete still emitted
        assert _events_of_type(local_db, "call_evidence") == []

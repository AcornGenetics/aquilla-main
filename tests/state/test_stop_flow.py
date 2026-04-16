"""
State tests: stop button flow and _monitor_stop_request thread logic.
"""
import time
from threading import Event
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

import state_run_assay


# ---------------------------------------------------------------------------
# TestClient-based tests
# ---------------------------------------------------------------------------

@pytest.mark.state
class TestStopFlowHTTP:
    """HTTP-level stop button behaviour."""

    def test_stop_sets_stop_requested(self, client):
        """POST /button/stop sets stop_requested=True in /button_status."""
        client.post("/button/stop")
        status = client.get("/button_status").json()
        assert status["stop_requested"] is True

    def test_stop_returns_ok(self, client):
        """POST /button/stop returns {"ok": true}."""
        response = client.post("/button/stop")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_stop_reset_clears_stop_requested(self, client):
        """POST /stop/reset clears stop_requested to False."""
        client.post("/button/stop")
        client.post("/stop/reset")
        status = client.get("/button_status").json()
        assert status["stop_requested"] is False

    def test_stop_requested_starts_false(self, client):
        """stop_requested is False on fresh (reset) state."""
        status = client.get("/button_status").json()
        assert status["stop_requested"] is False

    def test_run_after_stop_clears_stop_requested(self, client):
        """POST /button/run clears stop_requested (it resets it before guard checks)."""
        client.post("/button/stop")
        status = client.get("/button_status").json()
        assert status["stop_requested"] is True

        # /button/run resets stop_requested at the top of the handler
        client.post("/button/run")
        status = client.get("/button_status").json()
        assert status["stop_requested"] is False

    def test_double_stop_is_idempotent(self, client):
        """Two consecutive POST /button/stop calls don't crash and stay True."""
        r1 = client.post("/button/stop")
        r2 = client.post("/button/stop")
        assert r1.status_code == 200
        assert r2.status_code == 200
        status = client.get("/button_status").json()
        assert status["stop_requested"] is True


# ---------------------------------------------------------------------------
# Threading / unit tests for _monitor_stop_request
# ---------------------------------------------------------------------------

@pytest.mark.state
class TestMonitorStopRequestThread:
    """Direct unit tests for the AssayInterface._monitor_stop_request method."""

    def _make_interface_stub(self):
        """Return an AssayInterface instance with hardware init skipped."""
        obj = object.__new__(state_run_assay.AssayInterface)
        return obj

    def test_monitor_exits_when_stop_monitor_event_set(self):
        """Thread exits cleanly when stop_monitor_event is set (no stop detected)."""
        iface = self._make_interface_stub()
        stop_event = Event()
        stop_monitor_event = Event()
        stop_monitor_event.set()  # signal the thread to exit immediately

        with patch("state_run_assay.sr.check_stop_request", return_value=False) as mock_check:
            iface._monitor_stop_request(stop_event, stop_monitor_event)

        # Thread returned — stop_event should NOT have been set
        assert not stop_event.is_set()

    def test_monitor_sets_stop_event_when_check_returns_true(self):
        """When sr.check_stop_request() returns True, stop_event is set."""
        iface = self._make_interface_stub()
        stop_event = Event()
        stop_monitor_event = Event()

        call_count = [0]

        def fake_check():
            # Return True on the first call so the monitor fires immediately
            call_count[0] += 1
            return True

        with patch("state_run_assay.sr.check_stop_request", side_effect=fake_check):
            with patch("state_run_assay.sr.reset_stop_request") as mock_reset:
                iface._monitor_stop_request(stop_event, stop_monitor_event)

        assert stop_event.is_set()
        mock_reset.assert_called_once()

    def test_monitor_calls_reset_after_detecting_stop(self):
        """sr.reset_stop_request() is called exactly once after a stop is detected."""
        iface = self._make_interface_stub()
        stop_event = Event()
        stop_monitor_event = Event()

        with patch("state_run_assay.sr.check_stop_request", return_value=True):
            with patch("state_run_assay.sr.reset_stop_request") as mock_reset:
                iface._monitor_stop_request(stop_event, stop_monitor_event)

        mock_reset.assert_called_once()

    def test_monitor_exits_when_stop_event_already_set(self):
        """Thread exits without checking stop when stop_event is pre-set."""
        iface = self._make_interface_stub()
        stop_event = Event()
        stop_event.set()  # already stopped from the outside
        stop_monitor_event = Event()

        with patch("state_run_assay.sr.check_stop_request", return_value=False) as mock_check:
            iface._monitor_stop_request(stop_event, stop_monitor_event)

        # Loop condition is False on first iteration; check_stop_request never called
        mock_check.assert_not_called()

    def test_monitor_loops_until_stop_detected(self):
        """Monitor calls check_stop_request multiple times before detecting stop."""
        iface = self._make_interface_stub()
        stop_event = Event()
        stop_monitor_event = Event()

        responses = [False, False, True]
        call_index = [0]

        def fake_check():
            val = responses[call_index[0]]
            call_index[0] += 1
            return val

        with patch("state_run_assay.sr.check_stop_request", side_effect=fake_check):
            with patch("state_run_assay.sr.reset_stop_request"):
                with patch("state_run_assay.time.sleep"):  # skip real sleep
                    iface._monitor_stop_request(stop_event, stop_monitor_event)

        assert stop_event.is_set()
        assert call_index[0] == 3

"""
State tests: backend correctly blocks invalid run requests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.mark.state
class TestRunGuards:
    """POST /button/run guard logic."""

    def test_cannot_run_with_no_profile(self, client):
        """Run is blocked when no profile is selected."""
        # Ensure no profile is selected (conftest reset clears it via /run_status/reset)
        response = client.post("/button/run")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False

    def test_cannot_run_with_no_run_name(self, client, monkeypatch):
        """Run is blocked when run_name is blank.

        The /run/name endpoint intentionally rejects whitespace-only values, so
        we monkeypatch the module global directly to exercise the guard code.
        """
        from aquila_web import main as web_main
        monkeypatch.setattr(web_main, "run_name", "")
        client.post("/profile/select", json={"profile": "test_profile.json"})
        response = client.post("/button/run")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False

    def test_cannot_run_with_drawer_open(self, client):
        """Run is blocked when the drawer is open."""
        client.post("/profile/select", json={"profile": "test_profile.json"})
        client.post("/run/name", json={"name": "run1"})
        # Open the drawer via the drawer/state endpoint
        client.post("/drawer/state", json={"open": True, "closed": False})
        response = client.post("/button/run")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        # Restore drawer state so teardown is clean
        client.post("/drawer/state", json={"open": False, "closed": False})

    def test_can_run_when_all_conditions_met(self, client):
        """Run succeeds when profile selected, run_name set, drawer closed."""
        client.post("/profile/select", json={"profile": "test_profile.json"})
        client.post("/run/name", json={"name": "run1"})
        client.post("/drawer/state", json={"open": False, "closed": True})
        response = client.post("/button/run")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        # Restore drawer state
        client.post("/drawer/state", json={"open": False, "closed": False})

    def test_run_requested_cleared_after_reset(self, client):
        """run_requested is False after /run_status/reset."""
        client.post("/profile/select", json={"profile": "test_profile.json"})
        client.post("/drawer/state", json={"open": False, "closed": True})
        client.post("/button/run")
        # Now reset
        client.post("/run_status/reset")
        status = client.get("/button_status").json()
        assert status["run_requested"] is False
        client.post("/drawer/state", json={"open": False, "closed": False})

    def test_selected_profile_cleared_after_reset(self, client):
        """selected_profile is None after /run_status/reset."""
        client.post("/profile/select", json={"profile": "test_profile.json"})
        client.post("/drawer/state", json={"open": False, "closed": True})
        client.post("/button/run")
        client.post("/run_status/reset")
        status = client.get("/button_status").json()
        assert status["profile"] is None
        client.post("/drawer/state", json={"open": False, "closed": False})

    def test_double_run_while_run_requested(self, client):
        """
        A second POST /button/run while run_requested is already True is
        either idempotent (returns ok: true) or blocked (ok: false), but must
        not crash — we just assert a valid 200 with an 'ok' key.
        """
        client.post("/profile/select", json={"profile": "test_profile.json"})
        client.post("/drawer/state", json={"open": False, "closed": True})
        first = client.post("/button/run")
        assert first.status_code == 200
        assert first.json()["ok"] is True

        second = client.post("/button/run")
        assert second.status_code == 200
        assert "ok" in second.json()
        client.post("/drawer/state", json={"open": False, "closed": False})

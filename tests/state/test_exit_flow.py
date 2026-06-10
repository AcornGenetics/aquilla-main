"""
State tests: exit button and force-exit flow.
"""
import pytest


@pytest.mark.state
class TestExitFlow:
    """Exit button HTTP behaviour."""

    def test_exit_button_sets_exit_button_status(self, client):
        """POST /button/exit sets exit_button_status=True."""
        client.post("/button/exit")
        status = client.get("/button_status").json()
        assert status["exit_button_status"] is True

    def test_exit_reset_clears_exit_button_status(self, client):
        """POST /exit/reset clears exit_button_status to False."""
        client.post("/button/exit")
        client.post("/exit/reset")
        status = client.get("/button_status").json()
        assert status["exit_button_status"] is False

    def test_force_exit_sets_force_exit(self, client):
        """POST /button/exit/force sets force_exit=True."""
        client.post("/button/exit/force")
        status = client.get("/button_status").json()
        assert status["force_exit"] is True

    def test_force_exit_reset_clears_force_exit(self, client):
        """POST /exit/force/reset clears force_exit to False."""
        client.post("/button/exit/force")
        client.post("/exit/force/reset")
        status = client.get("/button_status").json()
        assert status["force_exit"] is False

    def test_exit_button_status_starts_false(self, client):
        """exit_button_status is False on fresh (reset) state."""
        status = client.get("/button_status").json()
        assert status["exit_button_status"] is False

    def test_force_exit_starts_false(self, client):
        """force_exit is False on fresh (reset) state."""
        status = client.get("/button_status").json()
        assert status["force_exit"] is False

    def test_double_exit_press_is_idempotent(self, client):
        """Two consecutive POST /button/exit calls don't crash; status stays True."""
        r1 = client.post("/button/exit")
        r2 = client.post("/button/exit")
        assert r1.status_code == 200
        assert r2.status_code == 200
        status = client.get("/button_status").json()
        assert status["exit_button_status"] is True

    def test_force_exit_returns_ok(self, client):
        """POST /button/exit/force returns {"ok": true}."""
        response = client.post("/button/exit/force")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_exit_reset_returns_ok(self, client):
        """POST /exit/reset returns {"ok": true}."""
        response = client.post("/exit/reset")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_exit_force_reset_returns_ok(self, client):
        """POST /exit/force/reset returns {"ok": true}."""
        response = client.post("/exit/force/reset")
        assert response.status_code == 200
        assert response.json()["ok"] is True

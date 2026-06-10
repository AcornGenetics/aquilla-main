"""
State tests: drawer open/close flow and run guards.
"""
import pytest


@pytest.mark.state
class TestDrawerFlow:
    """Drawer button HTTP behaviour."""

    def test_button_open_sets_drawer_open_status(self, client):
        """POST /button/open sets drawer_open_status=True."""
        client.post("/button/open")
        status = client.get("/button_status").json()
        assert status["drawer_open_status"] is True

    def test_button_close_sets_drawer_close_status(self, client):
        """POST /button/close sets drawer_close_status=True."""
        client.post("/button/close")
        status = client.get("/button_status").json()
        assert status["drawer_close_status"] is True

    def test_drawer_state_open_true_closed_false(self, client):
        """POST /drawer/state {open:True, closed:False} sets correct drawer_state values."""
        client.post("/drawer/state", json={"open": True, "closed": False})
        state = client.get("/drawer/state").json()
        assert state["open"] is True
        assert state["closed"] is False
        # Restore
        client.post("/drawer/state", json={"open": False, "closed": False})

    def test_drawer_state_open_false_closed_true(self, client):
        """POST /drawer/state {open:False, closed:True} sets correct drawer_state values."""
        client.post("/drawer/state", json={"open": False, "closed": True})
        state = client.get("/drawer/state").json()
        assert state["open"] is False
        assert state["closed"] is True
        # Restore
        client.post("/drawer/state", json={"open": False, "closed": False})

    def test_drawer_status_reset_clears_flags(self, client):
        """POST /drawer_status/reset clears both drawer_open_status and drawer_close_status."""
        client.post("/button/open")
        client.post("/drawer_status/reset")
        status = client.get("/button_status").json()
        assert status["drawer_open_status"] is False
        assert status["drawer_close_status"] is False

    def test_drawer_status_reset_clears_close_flag(self, client):
        """POST /drawer_status/reset after close press clears drawer_close_status."""
        client.post("/button/close")
        client.post("/drawer_status/reset")
        status = client.get("/button_status").json()
        assert status["drawer_close_status"] is False

    def test_drawer_state_open_and_closed_not_both_true(self, client):
        """
        After any single valid drawer/state operation, open and closed are not
        simultaneously True.
        """
        for payload in [
            {"open": True, "closed": False},
            {"open": False, "closed": True},
            {"open": False, "closed": False},
        ]:
            client.post("/drawer/state", json=payload)
            state = client.get("/drawer/state").json()
            assert not (state["open"] and state["closed"]), (
                f"Both open and closed were True after setting {payload}"
            )
        # Restore
        client.post("/drawer/state", json={"open": False, "closed": False})

    def test_drawer_open_blocks_run(self, client):
        """POST /button/run returns ok:false when drawer_state is open."""
        client.post("/profile/select", json={"profile": "test_profile.json"})
        client.post("/run/name", json={"name": "run1"})
        client.post("/drawer/state", json={"open": True, "closed": False})

        response = client.post("/button/run")
        assert response.status_code == 200
        assert response.json()["ok"] is False

        # Restore
        client.post("/drawer/state", json={"open": False, "closed": False})

    def test_drawer_closed_allows_run(self, client):
        """POST /button/run returns ok:true when drawer is closed (not open)."""
        client.post("/profile/select", json={"profile": "test_profile.json"})
        client.post("/run/name", json={"name": "run1"})
        client.post("/drawer/state", json={"open": False, "closed": True})

        response = client.post("/button/run")
        assert response.status_code == 200
        assert response.json()["ok"] is True

        # Restore
        client.post("/drawer/state", json={"open": False, "closed": False})

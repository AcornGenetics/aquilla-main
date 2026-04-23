"""
Contract tests: profile-select → run sequence as a user would perform it
on the ready screen.

Covers the bug where selecting a profile from the dropdown did not always
sync to the backend before pressing Run (the frontend now re-POSTs
/profile/select inside notifyRun() — these tests verify the backend
behaves correctly for that pattern).

Run with:
    pytest tests/contract/test_ready_screen_run_flow.py -v
"""
import pytest


MINIMAL_PROFILE = {
    "name": "Ready Screen Test Profile",
    "steps": [
        {"setpoint": 95, "duration": 1},
        {"setpoint": 60, "duration": 1},
    ],
}


def _create_profile(client, name="Ready Screen Test Profile") -> str:
    resp = client.post("/profiles", json={**MINIMAL_PROFILE, "name": name})
    assert resp.status_code == 200
    assert resp.json().get("ok") is True
    return resp.json()["id"]


def _delete_profile(client, profile_id: str) -> None:
    client.post("/profiles/delete", json={"profiles": [profile_id]})


# ---------------------------------------------------------------------------
# Happy path: select then run
# ---------------------------------------------------------------------------

@pytest.mark.contract
class TestSelectThenRun:
    """Simulate the exact sequence the ready screen performs."""

    def test_select_profile_then_run_succeeds(self, client):
        """
        POST /profile/select → POST /button/run must return ok=True.
        This is the core ready-screen flow.
        """
        profile_id = _create_profile(client, "Select Then Run")
        try:
            client.post("/run/name", json={"name": "run1"})
            client.post("/drawer/state", json={"open": False, "closed": True})

            client.post("/profile/select", json={"profile": profile_id})
            resp = client.post("/button/run")

            assert resp.status_code == 200
            assert resp.json()["ok"] is True
        finally:
            _delete_profile(client, profile_id)
            client.post("/run_status/reset")
            client.post("/drawer/state", json={"open": False, "closed": False})

    def test_run_sets_run_requested_true(self, client):
        """After select → run, /button_status shows run_requested=True."""
        profile_id = _create_profile(client, "Run Requested Flag")
        try:
            client.post("/run/name", json={"name": "run1"})
            client.post("/drawer/state", json={"open": False, "closed": True})
            client.post("/profile/select", json={"profile": profile_id})
            client.post("/button/run")

            status = client.get("/button_status").json()
            assert status["run_requested"] is True
            assert status["profile"] == profile_id
        finally:
            _delete_profile(client, profile_id)
            client.post("/run_status/reset")
            client.post("/drawer/state", json={"open": False, "closed": False})

    def test_repost_profile_select_before_run_is_idempotent(self, client):
        """
        Frontend re-POSTs /profile/select inside notifyRun() as a sync guard.
        A second identical POST must not break anything — run must still succeed.
        """
        profile_id = _create_profile(client, "Repost Select Idempotent")
        try:
            client.post("/run/name", json={"name": "run1"})
            client.post("/drawer/state", json={"open": False, "closed": True})

            # First select (dropdown change event)
            client.post("/profile/select", json={"profile": profile_id})
            # Second select (re-sync inside notifyRun)
            client.post("/profile/select", json={"profile": profile_id})

            resp = client.post("/button/run")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True
        finally:
            _delete_profile(client, profile_id)
            client.post("/run_status/reset")
            client.post("/drawer/state", json={"open": False, "closed": False})

    def test_profile_synced_late_before_run_still_works(self, client):
        """
        Simulates the page-load case: profile was pre-selected visually but
        the server state was cleared (e.g. server restart). The frontend
        re-POSTs /profile/select in notifyRun() — this must restore state
        and allow the run.
        """
        profile_id = _create_profile(client, "Late Sync Before Run")
        try:
            client.post("/run/name", json={"name": "run1"})
            client.post("/drawer/state", json={"open": False, "closed": True})

            # Simulate server losing state (e.g. restart clears in-memory global)
            client.post("/run_status/reset")

            # Frontend re-syncs the profile just before calling /button/run
            client.post("/profile/select", json={"profile": profile_id})

            resp = client.post("/button/run")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True
        finally:
            _delete_profile(client, profile_id)
            client.post("/run_status/reset")
            client.post("/drawer/state", json={"open": False, "closed": False})


# ---------------------------------------------------------------------------
# Guard: run must still fail without a profile (no select at all)
# ---------------------------------------------------------------------------

@pytest.mark.contract
class TestRunGuardsOnReadyScreen:

    def test_run_without_any_select_fails(self, client):
        """If /profile/select was never called, run must be blocked."""
        client.post("/run_status/reset")  # ensure clean slate
        client.post("/run/name", json={"name": "run1"})
        client.post("/drawer/state", json={"open": False, "closed": True})

        resp = client.post("/button/run")
        assert resp.status_code == 200
        assert resp.json()["ok"] is False

        client.post("/drawer/state", json={"open": False, "closed": False})

    def test_run_after_profile_reset_fails(self, client):
        """
        Profile selected, then reset (e.g. user hits Reset button),
        then run pressed without re-selecting — must be blocked.
        """
        profile_id = _create_profile(client, "Reset Then Run Blocked")
        try:
            client.post("/run/name", json={"name": "run1"})
            client.post("/drawer/state", json={"open": False, "closed": True})
            client.post("/profile/select", json={"profile": profile_id})

            # User hits Reset
            client.post("/run_status/reset")

            # User immediately hits Run without re-selecting
            resp = client.post("/button/run")
            assert resp.status_code == 200
            assert resp.json()["ok"] is False
        finally:
            _delete_profile(client, profile_id)
            client.post("/drawer/state", json={"open": False, "closed": False})

    def test_button_status_profile_field_matches_selected(self, client):
        """
        /button_status always reflects the most recently POSTed profile,
        not a stale value.
        """
        profile_a = _create_profile(client, "Profile A")
        profile_b = _create_profile(client, "Profile B")
        try:
            client.post("/profile/select", json={"profile": profile_a})
            assert client.get("/button_status").json()["profile"] == profile_a

            # Switch to profile B (user changes dropdown)
            client.post("/profile/select", json={"profile": profile_b})
            assert client.get("/button_status").json()["profile"] == profile_b
        finally:
            _delete_profile(client, profile_a)
            _delete_profile(client, profile_b)
            client.post("/run_status/reset")

"""
Contract tests: a completed run clears the selected profile (#275 follow-up).

After the fix that keeps selected_profile alive for the whole run, it must be
cleared once the run completes so the ready screen returns to "Select a profile"
for the next run — without the operator pressing reset. The completion signal is
POST /run/complete/ack (frontend script.js; the device reads run_complete_ack).
"""
import pytest

pytestmark = pytest.mark.contract

PROFILE_ID = "local/verification_profile.json"


def test_run_complete_ack_clears_selected_profile(client):
    client.post("/profile/select", json={"profile": PROFILE_ID})

    client.post("/run/complete/ack")

    assert client.get("/button_status").json()["profile"] in (None, "")


def test_cleared_profile_stays_cleared_after_restart(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main

    monkeypatch.setattr(web_main, "RUN_STATE_PATH", tmp_path / "run_state.json")

    client.post("/profile/select", json={"profile": PROFILE_ID})
    client.post("/run/complete/ack")

    # A backend restart after completion must not resurrect the cleared profile.
    web_main.selected_profile = None
    web_main._init_selected_profile()

    assert client.get("/button_status").json()["profile"] in (None, "")

"""
Contract tests for /run_requested/ack — the run-request edge-ack that must
preserve the selected profile (#275).

Root cause of #275: the device state loop consumed the run press by calling
/run_status/reset, which also cleared selected_profile. The Run-card header
sources profile_name from selected_profile via the /ws panel, so it fell back
to the "--" no-profile sentinel the instant a run started (device only — dev's
DEV_SIMULATE path never calls this).

/run_requested/ack must clear only run_requested and leave selected_profile
intact, while /run_status/reset keeps its full-reset semantics.
"""
import pytest

pytestmark = pytest.mark.contract

PROFILE_ID = "local/verification_profile.json"


def test_ack_preserves_selected_profile(client):
    # Operator selects a profile, then presses Run.
    client.post("/profile/select", json={"profile": PROFILE_ID})

    # The device loop consumes the run-press edge.
    resp = client.post("/run_requested/ack")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # The profile must survive so the header keeps showing it during the run.
    assert client.get("/button_status").json()["profile"] == PROFILE_ID


def test_ack_clears_run_requested_flag(client):
    from aquila_web import main as web_main

    client.post("/profile/select", json={"profile": PROFILE_ID})
    web_main.run_requested = True

    client.post("/run_requested/ack")

    # The run-press edge is consumed so it is not handled twice.
    assert web_main.run_requested is False


def test_run_status_reset_still_clears_profile(client):
    # /run_status/reset keeps its full-reset semantics (used for test isolation
    # and a genuine cancel/reset).
    client.post("/profile/select", json={"profile": PROFILE_ID})
    client.post("/run_status/reset")
    assert client.get("/button_status").json()["profile"] in (None, "")

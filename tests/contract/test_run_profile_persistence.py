"""
Contract tests for running-profile durability across a backend restart.

Follow-up to #272: on the device the backend process is replaced mid-run
(watchtower / container restarts). ``run_name`` survives because it is rebuilt
from ``history.json`` on startup, but ``selected_profile`` was in-memory only and
reset to ``None`` — so the Run-card header (which reads it via the ``/ws`` panel's
``profile_name``) showed the ``"--"`` no-profile sentinel while ``run_name`` still
showed correctly.

The selected profile must be persisted to disk and restored on startup, mirroring
``run_name``, so the running profile survives a restart.
"""
import pytest

pytestmark = pytest.mark.contract

PROFILE_ID = "local/verification_profile.json"


def test_selected_profile_survives_backend_restart(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main

    # Isolate the persisted-state file so the test never touches real device state.
    monkeypatch.setattr(web_main, "RUN_STATE_PATH", tmp_path / "run_state.json")

    # Operator selects a profile before starting a run.
    client.post("/profile/select", json={"profile": PROFILE_ID})

    # Simulate a backend restart: the fresh process loses every in-memory global,
    # then the startup restore runs (mirrors _init_run_name at module load).
    web_main.selected_profile = None
    web_main._init_selected_profile()

    # The restored process still knows which profile is running.
    assert client.get("/button_status").json()["profile"] == PROFILE_ID


def test_run_status_reset_clears_persisted_profile(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main

    monkeypatch.setattr(web_main, "RUN_STATE_PATH", tmp_path / "run_state.json")

    client.post("/profile/select", json={"profile": PROFILE_ID})
    client.post("/run_status/reset")

    # A restart after a reset must not resurrect the cleared profile.
    web_main.selected_profile = None
    web_main._init_selected_profile()

    assert client.get("/button_status").json()["profile"] in (None, "")

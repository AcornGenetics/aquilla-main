"""Contract tests for the run-guard warnings (issue #422).

The same three refusals are worded in two places — the client checks them before
POSTing, and the server checks them again — and the two copies had drifted apart
by a trailing full stop. The operator saw slightly different punctuation
depending on which layer caught the problem.
"""
from pathlib import Path

import pytest

SCRIPT_JS = Path(__file__).parents[2] / "aquila_web" / "static" / "script.js"

NO_PROFILE = "Select a profile before running."
NO_RUN_NAME = "Enter a run name before running."
DRAWER_OPEN = "Close the drawer before running."


@pytest.mark.contract
def test_run_without_a_profile_is_refused_with_the_full_message(client):
    body = client.post("/button/run").json()
    assert body["ok"] is False
    assert body["message"] == NO_PROFILE


@pytest.mark.contract
def test_run_without_a_run_name_is_refused_with_the_full_message(client, monkeypatch):
    """The run name is set through module state, not the API.

    POST /run/name ignores an empty value and run_name always carries an
    auto-generated default, so this guard cannot be reached over HTTP — the
    client-side check is what fires in practice. Reaching it directly is the
    only way to pin its wording.
    """
    from aquila_web import main as web_main

    client.post("/profile/select", json={"profile": "anything.json"})
    monkeypatch.setattr(web_main, "run_name", "")
    body = client.post("/button/run").json()
    assert body["ok"] is False
    assert body["message"] == NO_RUN_NAME


@pytest.mark.contract
def test_run_with_the_drawer_open_is_refused_with_the_full_message(client):
    client.post("/profile/select", json={"profile": "anything.json"})
    client.post("/run/name", json={"name": "run1"})
    client.post("/drawer/state", json={"open": True, "closed": False})
    body = client.post("/button/run").json()
    assert body["ok"] is False
    assert body["message"] == DRAWER_OPEN


@pytest.mark.contract
def test_client_and_server_word_the_refusals_identically():
    """Both layers guard the same three rules; they must say the same thing."""
    script = SCRIPT_JS.read_text(encoding="utf-8")
    for message in (NO_PROFILE, NO_RUN_NAME, DRAWER_OPEN):
        assert f'"{message}"' in script, f"client copy drifted from {message!r}"

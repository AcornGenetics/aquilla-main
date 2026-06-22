"""
Contract tests for button / status / reset endpoints.

All tests use the `client` fixture from tests/contract/conftest.py and carry
the `@pytest.mark.contract` marker so they run with:

    pytest tests/contract/ -m contract
"""
import pytest


# ---------------------------------------------------------------------------
# /button/run
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_button_run_no_profile_returns_ok_false(client):
    """POST /button/run with no profile selected must return {"ok": false}."""
    # ensure no profile is selected
    client.post("/run_status/reset")
    response = client.post("/button/run")
    assert response.status_code == 200
    assert response.json()["ok"] is False


@pytest.mark.contract
def test_button_run_no_run_name_returns_ok_false(client):
    """POST /button/run with empty run name must return {"ok": false}.

    The API's _set_run_name() ignores blank strings, so we patch the module
    global directly to simulate the run_name-empty condition.
    """
    from sentri_web import main as web_main

    client.post("/profile/select", json={"profile": "some_profile.json"})
    original = web_main.run_name
    try:
        web_main.run_name = ""
        response = client.post("/button/run")
        assert response.status_code == 200
        assert response.json()["ok"] is False
    finally:
        web_main.run_name = original


@pytest.mark.contract
def test_button_run_drawer_open_returns_ok_false(client):
    """POST /button/run while drawer is open must return {"ok": false}."""
    client.post("/profile/select", json={"profile": "some_profile.json"})
    client.post("/run/name", json={"name": "run1"})
    # force drawer into open state
    client.post("/drawer/state", json={"open": True, "closed": False})
    response = client.post("/button/run")
    assert response.status_code == 200
    assert response.json()["ok"] is False


@pytest.mark.contract
def test_button_run_valid_state_returns_ok_true(client_with_profile):
    """POST /button/run with profile selected, run name set, drawer closed returns {"ok": true}."""
    client, _profile_id = client_with_profile
    response = client.post("/button/run")
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.contract
def test_button_run_sets_run_requested(client_with_profile):
    """POST /button/run in a valid state sets run_requested=True in /button_status."""
    client, _profile_id = client_with_profile
    client.post("/button/run")
    status = client.get("/button_status").json()
    assert status["run_requested"] is True


# ---------------------------------------------------------------------------
# /button/stop
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_button_stop_sets_stop_requested(client):
    """POST /button/stop sets stop_requested=True."""
    client.post("/button/stop")
    status = client.get("/button_status").json()
    assert status["stop_requested"] is True


@pytest.mark.contract
def test_button_stop_returns_200(client):
    """POST /button/stop returns HTTP 200."""
    response = client.post("/button/stop")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# /button/open, /button/close
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_button_open_sets_drawer_open_status(client):
    """POST /button/open sets drawer_open_status=True."""
    client.post("/button/open")
    status = client.get("/button_status").json()
    assert status["drawer_open_status"] is True


@pytest.mark.contract
def test_button_close_sets_drawer_close_status(client):
    """POST /button/close sets drawer_close_status=True."""
    # put drawer in open state first so close has something to act on
    client.post("/button/open")
    client.post("/button/close")
    status = client.get("/button_status").json()
    assert status["drawer_close_status"] is True


# ---------------------------------------------------------------------------
# /button/exit, /button/exit/force
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_button_exit_sets_exit_button_status(client):
    """POST /button/exit sets exit_button_status=True."""
    client.post("/button/exit")
    status = client.get("/button_status").json()
    assert status["exit_button_status"] is True


@pytest.mark.contract
def test_button_exit_force_sets_force_exit(client):
    """POST /button/exit/force sets force_exit=True."""
    client.post("/button/exit/force")
    status = client.get("/button_status").json()
    assert status["force_exit"] is True


# ---------------------------------------------------------------------------
# GET /button_status — required keys
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_button_status_has_required_keys(client):
    """GET /button_status returns all required keys."""
    required_keys = {
        "run_requested",
        "stop_requested",
        "exit_button_status",
        "force_exit",
        "drawer_open_status",
        "drawer_close_status",
        "run_complete_ack",
        "profile",
        "run_name",
    }
    status = client.get("/button_status").json()
    missing = required_keys - status.keys()
    assert not missing, f"Missing keys in /button_status: {missing}"


# ---------------------------------------------------------------------------
# Reset endpoints
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_run_status_reset_clears_run_requested_and_profile(client):
    """POST /run_status/reset clears run_requested and selected_profile."""
    # set them first
    client.post("/profile/select", json={"profile": "any_profile.json"})
    client.post("/run_status/reset")
    status = client.get("/button_status").json()
    assert status["run_requested"] is False
    assert status["profile"] is None


@pytest.mark.contract
def test_stop_reset_clears_stop_requested(client):
    """POST /stop/reset clears stop_requested."""
    client.post("/button/stop")
    client.post("/stop/reset")
    status = client.get("/button_status").json()
    assert status["stop_requested"] is False


@pytest.mark.contract
def test_exit_reset_clears_exit_button(client):
    """POST /exit/reset clears exit_button_status."""
    client.post("/button/exit")
    client.post("/exit/reset")
    status = client.get("/button_status").json()
    assert status["exit_button_status"] is False


@pytest.mark.contract
def test_exit_force_reset_clears_force_exit(client):
    """POST /exit/force/reset clears force_exit."""
    client.post("/button/exit/force")
    client.post("/exit/force/reset")
    status = client.get("/button_status").json()
    assert status["force_exit"] is False


# ---------------------------------------------------------------------------
# /run/complete/ack, /run/complete/ack/reset
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_run_complete_ack_sets_flag(client):
    """POST /run/complete/ack sets run_complete_ack=True."""
    client.post("/run/complete/ack")
    status = client.get("/button_status").json()
    assert status["run_complete_ack"] is True


@pytest.mark.contract
def test_run_complete_ack_reset_clears_flag(client):
    """POST /run/complete/ack/reset clears run_complete_ack."""
    client.post("/run/complete/ack")
    client.post("/run/complete/ack/reset")
    status = client.get("/button_status").json()
    assert status["run_complete_ack"] is False

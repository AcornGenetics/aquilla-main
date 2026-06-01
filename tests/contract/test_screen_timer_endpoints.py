"""
Contract tests for screen, timer, run-name, tube-name, WebSocket, and health endpoints.

Run with:
    pytest tests/contract/ -m contract
"""
import pytest


# ---------------------------------------------------------------------------
# POST /change_screen/ — accepts Item body with a screen field
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_change_screen_init_returns_200(client):
    """POST /change_screen/ with screen='init' returns 200."""
    resp = client.post("/change_screen/", json={"screen": "init"})
    assert resp.status_code == 200


@pytest.mark.contract
def test_change_screen_ready_returns_200(client):
    """POST /change_screen/ with screen='ready' returns 200."""
    resp = client.post("/change_screen/", json={"screen": "ready"})
    assert resp.status_code == 200


@pytest.mark.contract
def test_change_screen_running_returns_200(client):
    """POST /change_screen/ with screen='running' returns 200."""
    resp = client.post("/change_screen/", json={"screen": "running"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# WebSocket /ws
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_websocket_accepts_connection_and_sends_json(client):
    """WebSocket /ws accepts a connection and sends a JSON message containing 'screen'."""
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
    assert isinstance(data, dict)
    assert "screen" in data, f"Expected 'screen' key in WebSocket message, got: {data}"


# ---------------------------------------------------------------------------
# POST /timer
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_timer_start_sets_timer_running(client):
    """POST /timer with action='start' succeeds and timer_running becomes True."""
    resp = client.post("/timer", json={"action": "start"})
    assert resp.status_code == 200
    assert "Timer" in resp.json().get("message", "")


@pytest.mark.contract
def test_timer_stop_returns_200(client):
    """POST /timer with action='stop' returns 200."""
    client.post("/timer", json={"action": "start"})
    resp = client.post("/timer", json={"action": "stop"})
    assert resp.status_code == 200


@pytest.mark.contract
def test_timer_reset_sets_elapsed_to_zero(client):
    """POST /timer with action='reset' returns 200 and resets state."""
    client.post("/timer", json={"action": "start"})
    resp = client.post("/timer", json={"action": "reset"})
    assert resp.status_code == 200
    data = resp.json()
    assert "reset" in data.get("message", "").lower()


@pytest.mark.contract
def test_timer_invalid_action_returns_400(client):
    """POST /timer with an invalid action returns 400."""
    resp = client.post("/timer", json={"action": "fly_to_moon"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /run/name, POST /run/name, POST /run/name/advance
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_get_run_name_returns_name_key(client):
    """GET /run/name returns a dict with a 'name' key."""
    resp = client.get("/run/name")
    assert resp.status_code == 200
    assert "name" in resp.json()


@pytest.mark.contract
def test_set_run_name_then_get_returns_updated_value(client):
    """POST /run/name sets the name; GET /run/name returns the updated value."""
    client.post("/run/name", json={"name": "contract_run_99"})
    resp = client.get("/run/name")
    assert resp.json()["name"] == "contract_run_99"


@pytest.mark.contract
def test_advance_run_name_increments(client):
    """POST /run/name/advance returns a new name (does not crash)."""
    before = client.get("/run/name").json()["name"]
    resp = client.post("/run/name/advance")
    assert resp.status_code == 200
    after = resp.json()["name"]
    assert isinstance(after, str)
    assert after  # non-empty


# ---------------------------------------------------------------------------
# GET /tube_names, POST /tube_names
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_get_tube_names_returns_array_of_4_strings(client):
    """GET /tube_names returns an array of exactly 4 strings."""
    resp = client.get("/tube_names")
    assert resp.status_code == 200
    names = resp.json().get("names")
    assert isinstance(names, list)
    assert len(names) == 4
    for name in names:
        assert isinstance(name, str)


@pytest.mark.contract
def test_post_tube_names_updates_all_four(client):
    """POST /tube_names updates tube names; GET /tube_names reflects the change."""
    new_names = ["Alpha", "Beta", "Gamma", "Delta"]
    resp = client.post("/tube_names", json={"names": new_names})
    assert resp.status_code == 200
    returned = resp.json()["names"]
    assert returned == new_names

    fetched = client.get("/tube_names").json()["names"]
    assert fetched == new_names


@pytest.mark.contract
def test_post_tube_names_empty_string_uses_default_fallback(client):
    """POST /tube_names with an empty string entry falls back to the default name."""
    resp = client.post("/tube_names", json={"names": ["", "Custom", "", ""]})
    assert resp.status_code == 200
    names = resp.json()["names"]
    assert len(names) == 4
    # Empty slots must have been replaced with non-empty defaults
    assert names[0] != ""   # "Tube 1" default
    assert names[1] == "Custom"
    assert names[2] != ""   # "Tube 3" default
    assert names[3] != ""   # "Tube 4" default


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_health_returns_200(client):
    """GET /health returns HTTP 200."""
    resp = client.get("/health")
    assert resp.status_code == 200


@pytest.mark.contract
def test_health_returns_status_ok(client):
    """GET /health returns {"status": "ok"}."""
    resp = client.get("/health")
    assert resp.json().get("status") == "ok"

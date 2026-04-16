"""
Contract tests for history endpoints.

Run with:
    pytest tests/contract/ -m contract
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HISTORY_ENTRY = {
    "profile": "Test Profile",
    "run_name": "run42",
    "results_path": None,
    "graph_path": "/plots/test_profile_run42.png",
    "tube_names": ["Tube 1", "Tube 2", "Tube 3", "Tube 4"],
}


def _clear(client) -> None:
    client.post("/history/clear")


# ---------------------------------------------------------------------------
# GET /history/data
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_history_data_returns_list(client):
    """GET /history/data returns a list."""
    resp = client.get("/history/data")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.contract
def test_history_data_empty_when_cleared(client):
    """GET /history/data returns an empty list after clearing."""
    _clear(client)
    resp = client.get("/history/data")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /history/append
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_history_append_adds_entry(client):
    """POST /history/append adds an entry; GET /history/data returns it."""
    _clear(client)
    resp = client.post("/history/append", json=HISTORY_ENTRY)
    assert resp.status_code == 200
    assert resp.json().get("ok") is True

    history = client.get("/history/data").json()
    assert len(history) == 1


@pytest.mark.contract
def test_history_append_stores_all_fields(client):
    """POST /history/append stores profile, run_name, graph_path, tube_names."""
    _clear(client)
    client.post("/history/append", json=HISTORY_ENTRY)
    entry = client.get("/history/data").json()[0]

    assert entry["profile"] == HISTORY_ENTRY["profile"]
    assert entry["run_name"] == HISTORY_ENTRY["run_name"]
    assert entry["graph_path"] == HISTORY_ENTRY["graph_path"]
    assert entry["tube_names"] == HISTORY_ENTRY["tube_names"]


@pytest.mark.contract
def test_history_entry_has_expected_keys(client):
    """History entry contains: timestamp, profile, run_name, results_path, graph_path, tube_names."""
    _clear(client)
    client.post("/history/append", json=HISTORY_ENTRY)
    entry = client.get("/history/data").json()[0]

    required_keys = {"timestamp", "profile", "run_name", "results_path", "graph_path", "tube_names"}
    missing = required_keys - entry.keys()
    assert not missing, f"Missing keys in history entry: {missing}"


# ---------------------------------------------------------------------------
# POST /history/delete
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_history_delete_removes_entry_at_index(client):
    """POST /history/delete removes the entry at the given index."""
    _clear(client)
    client.post("/history/append", json={**HISTORY_ENTRY, "run_name": "runA"})
    client.post("/history/append", json={**HISTORY_ENTRY, "run_name": "runB"})

    # delete the first entry (index 0)
    resp = client.post("/history/delete", json={"indices": [0]})
    assert resp.status_code == 200

    history = client.get("/history/data").json()
    assert len(history) == 1
    assert history[0]["run_name"] == "runB"


@pytest.mark.contract
def test_history_delete_invalid_index_handled_gracefully(client):
    """POST /history/delete with an out-of-range index does not crash."""
    _clear(client)
    resp = client.post("/history/delete", json={"indices": [9999]})
    # Must not 500 — either 200 or a 4xx
    assert resp.status_code < 500


# ---------------------------------------------------------------------------
# POST /history/clear
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_history_clear_empties_all_entries(client):
    """POST /history/clear empties history; GET /history/data returns []."""
    client.post("/history/append", json=HISTORY_ENTRY)
    client.post("/history/append", json=HISTORY_ENTRY)
    client.post("/history/clear")
    history = client.get("/history/data").json()
    assert history == []


@pytest.mark.contract
def test_history_data_after_clear_is_empty(client):
    """GET /history/data after clear returns empty list."""
    client.post("/history/clear")
    assert client.get("/history/data").json() == []


# ---------------------------------------------------------------------------
# Concurrent appends
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_concurrent_appends_both_present(client):
    """Appending twice in sequence preserves both entries."""
    _clear(client)
    entry_a = {**HISTORY_ENTRY, "run_name": "concurrentA"}
    entry_b = {**HISTORY_ENTRY, "run_name": "concurrentB"}

    r1 = client.post("/history/append", json=entry_a)
    r2 = client.post("/history/append", json=entry_b)
    assert r1.json()["ok"] is True
    assert r2.json()["ok"] is True

    history = client.get("/history/data").json()
    run_names = [e["run_name"] for e in history]
    assert "concurrentA" in run_names
    assert "concurrentB" in run_names

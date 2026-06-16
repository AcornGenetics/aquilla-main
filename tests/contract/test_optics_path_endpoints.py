"""
Contract tests for the dev optics-path endpoints and server-stored history.

GET/POST /dev/optics_path persist a most-recent-first, deduped, capped history
of optics paths used to back the custom optics-path dropdown on the run page.

Run with:

    pytest tests/contract/ -m contract
"""
import pytest


@pytest.fixture
def optics_client(client, tmp_path, monkeypatch):
    """Client whose optics-path history is isolated to a temp file."""
    from aquila_web import main as web_main

    monkeypatch.setattr(web_main, "OPTICS_PATHS_PATH", tmp_path / "optics_paths.json")
    return client


@pytest.mark.contract
def test_get_optics_path_returns_path_and_history(optics_client):
    """GET /dev/optics_path must return both the current path and a history list."""
    response = optics_client.get("/dev/optics_path")
    assert response.status_code == 200
    body = response.json()
    assert "path" in body
    assert isinstance(body["history"], list)


@pytest.mark.contract
def test_post_optics_path_records_history(optics_client):
    """POST /dev/optics_path stores the path and adds it to the history."""
    response = optics_client.post("/dev/optics_path", json={"path": "/data/a.log"})
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "/data/a.log"
    assert "/data/a.log" in body["history"]


@pytest.mark.contract
def test_post_optics_path_most_recent_first(optics_client):
    """Newly entered paths appear at the front of the history."""
    optics_client.post("/dev/optics_path", json={"path": "/data/first.log"})
    body = optics_client.post("/dev/optics_path", json={"path": "/data/second.log"}).json()
    assert body["history"][0] == "/data/second.log"
    assert body["history"][1] == "/data/first.log"


@pytest.mark.contract
def test_post_optics_path_deduplicates(optics_client):
    """Re-entering a path moves it to the front without duplicating it."""
    optics_client.post("/dev/optics_path", json={"path": "/data/a.log"})
    optics_client.post("/dev/optics_path", json={"path": "/data/b.log"})
    body = optics_client.post("/dev/optics_path", json={"path": "/data/a.log"}).json()
    assert body["history"].count("/data/a.log") == 1
    assert body["history"][0] == "/data/a.log"


@pytest.mark.contract
def test_post_blank_path_does_not_record(optics_client):
    """An empty path clears the current selection and is not added to history."""
    optics_client.post("/dev/optics_path", json={"path": "/data/a.log"})
    body = optics_client.post("/dev/optics_path", json={"path": ""}).json()
    assert body["path"] is None
    assert "" not in body["history"]


@pytest.mark.contract
def test_history_persists_across_requests(optics_client):
    """History written by POST is readable by a later GET."""
    optics_client.post("/dev/optics_path", json={"path": "/data/persist.log"})
    body = optics_client.get("/dev/optics_path").json()
    assert "/data/persist.log" in body["history"]

"""
Contract tests for the /dev/optics_path endpoints.

GET  /dev/optics_path -> {"path": str|null, "history": string[]}
POST /dev/optics_path  {"path": str} -> same shape

History is server-stored, most-recent-first, deduped, capped. A blank path
clears the current selection but leaves history intact.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_optics_storage(monkeypatch, tmp_path):
    """Point optics-history persistence at a throwaway file per test."""
    from aquila_web import main as web_main
    monkeypatch.setattr(
        web_main, "OPTICS_PATHS_PATH", tmp_path / "optics_paths.json", raising=False
    )
    monkeypatch.setattr(web_main, "dev_optics_path", None, raising=False)


def test_posted_path_appears_in_get_history(client):
    client.post("/dev/optics_path", json={"path": "/tmp/scope.log"})

    data = client.get("/dev/optics_path").json()

    assert "/tmp/scope.log" in data["history"]


def test_blank_path_clears_selection_but_keeps_history(client):
    client.post("/dev/optics_path", json={"path": "/tmp/scope.log"})

    resp = client.post("/dev/optics_path", json={"path": ""}).json()

    assert resp["path"] is None
    assert "/tmp/scope.log" in resp["history"]

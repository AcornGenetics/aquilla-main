"""
Unit tests for the background sync task and manual flush endpoint.

Behaviors tested:
  1. POST /sync/flush syncs pending events and returns the count
  2. POST /sync/flush returns {"synced": 0} when no endpoint is configured
  3. Network errors are swallowed — flush returns {"synced": 0}, events stay pending
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def db_client(tmp_path, monkeypatch):
    """TestClient with an isolated SQLite DB and a fake sync endpoint."""
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "test_sync.db"))
    from aquila_web import local_db, main as web_main
    local_db.init_local_db()
    with TestClient(web_main.app) as c:
        yield c, local_db


def _seed_event(local_db, tmp_path):
    """Insert one run_complete event so there is something to sync."""
    local_db.enqueue_event("run_complete", {"run_name": "Run 1", "profile": "p.json", "result": "ok"})


class TestSyncFlushEndpoint:
    """POST /sync/flush behaviour."""

    def test_syncs_pending_events_and_returns_count(self, db_client, tmp_path, monkeypatch):
        client, local_db = db_client
        _seed_event(local_db, tmp_path)
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        monkeypatch.setattr("aquila_web.sync.requests.post", lambda *a, **kw: _OK())
        response = client.post("/sync/flush")
        assert response.status_code == 200
        assert response.json()["synced"] == 1

    def test_returns_zero_when_no_endpoint_configured(self, db_client, tmp_path, monkeypatch):
        client, local_db = db_client
        _seed_event(local_db, tmp_path)
        monkeypatch.delenv("AQ_SYNC_ENDPOINT", raising=False)
        response = client.post("/sync/flush")
        assert response.status_code == 200
        assert response.json()["synced"] == 0

    def test_network_error_swallowed_returns_zero(self, db_client, tmp_path, monkeypatch):
        import requests as _requests
        client, local_db = db_client
        _seed_event(local_db, tmp_path)
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setattr(
            "aquila_web.sync.requests.post",
            lambda *a, **kw: (_ for _ in ()).throw(_requests.exceptions.ConnectionError("offline")),
        )
        response = client.post("/sync/flush")
        assert response.status_code == 200
        assert response.json()["synced"] == 0
        # event must still be pending — not lost
        assert len(local_db.get_pending_events()) == 1

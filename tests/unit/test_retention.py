"""
Retention of the local Event outbox (#304, ADR-020).

The device SQLite is a thin outbox: Events are pruned only once they are safely
synced AND old enough. `synced_at` means "accepted by the Ingest Endpoint (2xx)",
not "in the warehouse" — S3 is the source of truth, so the 30-day window is a
safety buffer. Pending and quarantined Events are never pruned.
"""
import sqlite3
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "retention.db"))
    from aquila_web import local_db
    local_db.init_local_db()
    return local_db


@pytest.fixture
def client_db(tmp_path, monkeypatch):
    """App TestClient sharing an isolated DB; no sync endpoint (flush pushes nothing)."""
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "retention.db"))
    monkeypatch.delenv("AQ_SYNC_ENDPOINT", raising=False)
    from fastapi.testclient import TestClient
    from aquila_web import local_db, main as web_main
    local_db.init_local_db()
    with TestClient(web_main.app) as client:
        yield client, local_db


def _backdate_sync(db, event_id: int, days_ago: int) -> None:
    """Arrange a row that was synced `days_ago` days ago (no public backdate API)."""
    ts = (datetime.utcnow() - timedelta(days=days_ago)).isoformat(timespec="seconds") + "Z"
    with sqlite3.connect(db.get_db_path()) as conn:
        conn.execute("UPDATE events SET synced_at = ? WHERE id = ?", (ts, event_id))


def _backdate_created(db, event_id: int, days_ago: int) -> None:
    ts = (datetime.utcnow() - timedelta(days=days_ago)).isoformat(timespec="seconds") + "Z"
    with sqlite3.connect(db.get_db_path()) as conn:
        conn.execute("UPDATE events SET created_at = ? WHERE id = ?", (ts, event_id))


def _ids(db) -> set[int]:
    with sqlite3.connect(db.get_db_path()) as conn:
        return {row[0] for row in conn.execute("SELECT id FROM events")}


def test_synced_row_within_window_is_retained(db):
    eid = db.enqueue_event("run_complete", {"run": 1})
    db.mark_event_synced([eid])
    _backdate_sync(db, eid, days_ago=29)

    db.cleanup_synced_events()  # default window

    assert eid in _ids(db)


def test_synced_row_past_window_is_pruned(db):
    eid = db.enqueue_event("run_complete", {"run": 1})
    db.mark_event_synced([eid])
    _backdate_sync(db, eid, days_ago=31)

    db.cleanup_synced_events()  # default window

    assert eid not in _ids(db)


def test_pending_row_is_never_pruned(db):
    # An undelivered Event is retained regardless of age -- never drop data the
    # cloud has not acknowledged.
    eid = db.enqueue_event("run_complete", {"run": 1})
    _backdate_created(db, eid, days_ago=100)  # ancient, but never synced

    db.cleanup_synced_events()

    assert eid in _ids(db)


def test_flush_prunes_old_synced_rows(client_db):
    # One sync cycle both pushes pending Events and prunes long-since-synced ones.
    client, db = client_db
    eid = db.enqueue_event("run_complete", {"run": 1})
    db.mark_event_synced([eid])
    _backdate_sync(db, eid, days_ago=31)

    resp = client.post("/sync/flush")

    assert resp.status_code == 200
    assert eid not in _ids(db)


def test_quarantined_row_is_never_pruned(db):
    # Quarantined Events are retained for diagnosis, never auto-deleted.
    eid = db.enqueue_event("call_evidence", {"run": 1})
    db.mark_event_quarantined(eid, "too big to split")
    _backdate_created(db, eid, days_ago=100)

    db.cleanup_synced_events()

    assert eid in _ids(db)

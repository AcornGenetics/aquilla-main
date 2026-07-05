"""
Unit tests for the Event quarantine seam (#289).

The size guard quarantines an Event too large to Sync even alone: it is left in
the local queue (never dropped or truncated), excluded from the flush path so it
can't take a batch slot or be re-fetched every interval, and kept discoverable
for diagnosis. Additive, idempotent migration so existing device DBs upgrade in
place without data loss.
"""
import pytest


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "quarantine.db"))
    from aquila_web import local_db as db
    db.init_local_db()
    return db


def test_quarantined_event_is_excluded_from_pending_but_retained(local_db):
    kept = local_db.enqueue_event("run_complete", {"ok": True})
    poison = local_db.enqueue_event("optics_readings", {"line_count": 1})

    local_db.mark_event_quarantined(poison, reason="exceeds SQS ceiling alone")

    # Excluded from the flush path -- no batch slot, not re-fetched every interval.
    assert [e["id"] for e in local_db.get_pending_events()] == [kept]
    # Retained and discoverable -- fail loud, never silently dropped.
    quarantined = local_db.get_quarantined_events()
    assert [e["id"] for e in quarantined] == [poison]
    assert quarantined[0]["quarantine_reason"] == "exceeds SQS ceiling alone"


def test_requeue_returns_a_quarantined_event_to_the_pending_queue(local_db):
    # A recovery seam so an event quarantined by transient misconfiguration is
    # not stuck forever short of manual SQL.
    event = local_db.enqueue_event("optics_readings", {"line_count": 1})
    local_db.mark_event_quarantined(event, reason="cap misconfigured")
    assert local_db.get_pending_events() == []

    changed = local_db.requeue_quarantined_event(event)

    assert changed == 1
    assert [e["id"] for e in local_db.get_pending_events()] == [event]  # back in the queue
    assert local_db.get_quarantined_events() == []                      # no longer quarantined


def test_requeue_is_a_noop_for_an_event_that_is_not_quarantined(local_db):
    event = local_db.enqueue_event("run_complete", {"ok": True})
    assert local_db.requeue_quarantined_event(event) == 0     # nothing to clear
    assert [e["id"] for e in local_db.get_pending_events()] == [event]


def test_migration_upgrades_a_pre_quarantine_db_without_data_loss(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(db_path))
    # A device DB created before #289: events table without quarantine columns.
    with sqlite3.connect(db_path) as legacy:
        legacy.execute(
            """
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                device_id TEXT,
                created_at TEXT NOT NULL,
                synced_at TEXT
            )
            """
        )
        legacy.execute(
            "INSERT INTO events (event_type, payload, created_at) VALUES (?, ?, ?)",
            ("run_complete", '{"ok": true}', "2026-01-01T00:00:00Z"),
        )

    from aquila_web import local_db as db
    db.init_local_db()   # migrate in place
    db.init_local_db()   # idempotent: running again must not error

    # The pre-existing event survived the migration and is still pending...
    pending = db.get_pending_events()
    assert [e["event_type"] for e in pending] == ["run_complete"]
    # ...and the new quarantine seam now works on the upgraded table.
    db.mark_event_quarantined(pending[0]["id"], reason="legacy poison")
    assert db.get_pending_events() == []
    assert [e["quarantine_reason"] for e in db.get_quarantined_events()] == ["legacy poison"]

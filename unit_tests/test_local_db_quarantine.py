"""
Unit tests for the event-quarantine seam in aquila_web/local_db.py (#289).

Covers the additive migration (existing devices gain the quarantine columns
without losing rows) and the quarantine helpers that keep an oversized event
in the DB while removing it from the flushable set.
"""
import sqlite3

import pytest

from aquila_web import local_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "events.db"))
    local_db.init_local_db()
    return local_db


class TestQuarantineMigration:
    def test_init_adds_columns_to_a_legacy_events_table_without_dropping_rows(self, tmp_path, monkeypatch):
        db_path = tmp_path / "legacy.db"
        monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(db_path))
        # Simulate a pre-#289 device: events table with no quarantine columns.
        with sqlite3.connect(db_path) as conn:
            conn.execute(
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
            conn.execute(
                "INSERT INTO events (event_type, payload, created_at) VALUES ('run_complete', '{}', 'yesterday')"
            )

        local_db.init_local_db()  # migration runs here

        with sqlite3.connect(db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
            assert {"quarantined_at", "quarantine_reason"} <= columns
            # legacy row survived and is still pending
            (count,) = conn.execute("SELECT COUNT(*) FROM events").fetchone()
            assert count == 1
        assert len(local_db.get_pending_events()) == 1

    def test_init_is_idempotent(self, db):
        db.init_local_db()  # second run must not raise on already-present columns
        assert db.get_pending_events() == []


class TestQuarantineHelpers:
    def test_quarantined_event_leaves_pending_set_but_row_is_retained(self, db):
        keep = db.enqueue_event("run_complete", {"ok": True})
        poison = db.enqueue_event("optics_readings", {"blob": "big"})

        db.mark_event_quarantined([poison], reason="too big")

        pending_ids = [e["id"] for e in db.get_pending_events()]
        assert pending_ids == [keep]                       # poison excluded
        quarantined = db.get_quarantined_events()
        assert [q["id"] for q in quarantined] == [poison]  # retained, discoverable
        assert quarantined[0]["quarantine_reason"] == "too big"

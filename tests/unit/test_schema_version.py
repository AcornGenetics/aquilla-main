"""
Schema version stamp on the local outbox DB (#305).

`init_local_db` stamps `PRAGMA user_version` so every Sentri's outbox carries an
explicit schema version to gate future non-additive migrations on, instead of
inferring state from column introspection. The stamp only ever moves forward.
"""
import sqlite3

import pytest

pytestmark = pytest.mark.unit

SCHEMA_VERSION = 2


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "schema.db"))
    from aquila_web import local_db
    return local_db


def _user_version(db) -> int:
    with sqlite3.connect(db.get_db_path()) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def test_fresh_db_reports_schema_version(db):
    db.init_local_db()

    assert _user_version(db) == SCHEMA_VERSION


def test_init_does_not_regress_a_higher_version(db):
    # A DB already stamped at a future version must not be lowered by init.
    db.init_local_db()
    with sqlite3.connect(db.get_db_path()) as conn:
        conn.execute("PRAGMA user_version = 3")

    db.init_local_db()

    assert _user_version(db) == 3


def test_init_is_idempotent(db):
    db.init_local_db()
    db.init_local_db()  # running again must not error or change the version

    assert _user_version(db) == SCHEMA_VERSION


def test_existing_pre_stamp_db_is_upgraded_in_place(db):
    # A DB created before the stamp existed: an events table, no user_version, and
    # missing the later quarantine columns. init must migrate it and stamp it.
    with sqlite3.connect(db.get_db_path()) as conn:
        conn.execute(
            "CREATE TABLE events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, "
            "payload TEXT NOT NULL, device_id TEXT, created_at TEXT NOT NULL, "
            "synced_at TEXT)"
        )
    assert _user_version(db) == 0  # precondition: unstamped legacy DB

    db.init_local_db()

    assert _user_version(db) == SCHEMA_VERSION

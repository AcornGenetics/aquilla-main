"""
Seam-2 unit tests: parsing Homing Samples from the on-device homing log into the
SQLite outbox (issue #326, ADR-021).

The parser reads the dedicated homing log written by motor_class (#325) and
enqueues each Sample as a ``homing_sample`` Event so it rides the same outbox ->
Sync path as run_complete. Exactly-once is a property of the data (the Sample id
backs a UNIQUE dedup_key + INSERT OR IGNORE).

Follows the temp-SQLite pattern of test_local_db_quarantine.py: point local_db
at a tmp DB and assert outbox state through the public interface.
"""
import json

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "homing.db"))
    from aquila_web import local_db as db
    db.init_local_db()
    return db


def _sample(sid, motor="drawer", steps=5, residual=-5, reached=True):
    return {
        "id": sid,
        "ts": "2026-07-16T00:00:00Z",
        "motor": motor,
        "steps_to_flag": steps,
        "residual": residual,
        "reached_home": reached,
    }


def _write_log(log_dir, *samples, name="homing.log"):
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / name
    path.write_text("".join(json.dumps(s) + "\n" for s in samples))
    return path


# ---------------------------------------------------------------------------
# Cycle 1: parse one Sample into one homing_sample Event, payload preserved
# ---------------------------------------------------------------------------

def test_parses_one_sample_into_one_homing_event(db, tmp_path):
    from aquila_web.homing_parser import import_homing_samples
    log_dir = tmp_path / "logs" / "homing"
    sample = _sample("s1")
    _write_log(log_dir, sample)

    count = import_homing_samples(log_dir=str(log_dir))

    assert count == 1
    pending = db.get_pending_events()
    assert len(pending) == 1
    assert pending[0]["event_type"] == "homing_sample"
    assert pending[0]["payload"] == sample


# ---------------------------------------------------------------------------
# Cycle 2: re-parsing the same log is idempotent (no duplicate Events)
# ---------------------------------------------------------------------------

def test_reparsing_same_lines_is_idempotent(db, tmp_path):
    from aquila_web.homing_parser import import_homing_samples
    log_dir = tmp_path / "logs" / "homing"
    _write_log(log_dir, _sample("s1"), _sample("s2"))

    first = import_homing_samples(log_dir=str(log_dir))
    second = import_homing_samples(log_dir=str(log_dir))

    assert first == 2      # both Samples enqueued the first time
    assert second == 0     # nothing new the second time
    assert len(db.get_pending_events()) == 2


# ---------------------------------------------------------------------------
# Cycle 3: Samples in the rotated log (.1) are loaded, not just the active file
# ---------------------------------------------------------------------------

def test_reads_rotated_log_in_addition_to_active(db, tmp_path):
    from aquila_web.homing_parser import import_homing_samples
    log_dir = tmp_path / "logs" / "homing"
    _write_log(log_dir, _sample("active1"), name="homing.log")
    _write_log(log_dir, _sample("rotated1"), name="homing.log.1")

    count = import_homing_samples(log_dir=str(log_dir))

    assert count == 2
    ids = {e["payload"]["id"] for e in db.get_pending_events()}
    assert ids == {"active1", "rotated1"}


# ---------------------------------------------------------------------------
# Cycle 4: a malformed line is skipped; the remaining Samples still load
# ---------------------------------------------------------------------------

def test_malformed_line_is_skipped_and_rest_load(db, tmp_path):
    from aquila_web.homing_parser import import_homing_samples
    log_dir = tmp_path / "logs" / "homing"
    log_dir.mkdir(parents=True)
    (log_dir / "homing.log").write_text(
        json.dumps(_sample("good1")) + "\n"
        + "this is not json\n"
        + json.dumps(_sample("good2")) + "\n"
    )

    count = import_homing_samples(log_dir=str(log_dir))

    assert count == 2
    ids = {e["payload"]["id"] for e in db.get_pending_events()}
    assert ids == {"good1", "good2"}


# ---------------------------------------------------------------------------
# Cycle 5a: existing Event types (no dedup_key) are unaffected by the change
# ---------------------------------------------------------------------------

def test_events_without_dedup_key_coexist(db):
    """Enqueuing without a dedup_key still works: multiple NULL dedup_keys must
    not collide under the UNIQUE index."""
    a = db.enqueue_event("run_complete", {"n": 1})
    b = db.enqueue_event("run_complete", {"n": 2})

    assert a is not None and b is not None and a != b
    assert len(db.get_pending_events()) == 2


# ---------------------------------------------------------------------------
# Cycle 5b: a pre-dedup device DB migrates in place without data loss
# ---------------------------------------------------------------------------

def test_migration_adds_dedup_without_data_loss(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(db_path))
    # A device DB created before #326: events table without a dedup_key column.
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

    # The pre-existing event survived the migration...
    pending = db.get_pending_events()
    assert [e["event_type"] for e in pending] == ["run_complete"]
    # ...and dedup now works on the upgraded table.
    first = db.enqueue_event("homing_sample", {"id": "x"}, dedup_key="x")
    dup = db.enqueue_event("homing_sample", {"id": "x"}, dedup_key="x")
    assert first is not None and dup is None

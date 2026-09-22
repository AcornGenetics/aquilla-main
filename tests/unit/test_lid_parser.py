"""
Unit tests: parsing Lid Heater Samples from the on-device Sample log into the
SQLite outbox (issue #452, ADR-022).

The lid-heater worker runs in the assay container; the outbox is owned by the
backend. The shared log directory is the seam between them, exactly as it is for
Homing Samples (ADR-021). Exactly-once is a property of the data: each Sample's
id backs a UNIQUE dedup_key + INSERT OR IGNORE, so re-parsing a log or a
rotation can never double-enqueue.

Follows the temp-SQLite pattern of test_homing_parser.py.
"""
import json

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "lid.db"))
    from aquila_web import local_db as db
    db.init_local_db()
    return db


def _sample(sid, kind="settled"):
    return {
        "sample_id": sid,
        "device_ts": "2026-08-20T09:00:00Z",
        "run_timestamp": "2026-08-20T08:59:00Z",
        "window_kind": kind,
        "window_seconds": 300.0,
        "mean_voltage": 0.32,
        "min_voltage": 0.31,
        "max_voltage": 0.33,
    }


def _write_log(log_dir, *samples, name="lid_samples.log"):
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / name
    path.write_text("".join(json.dumps(s) + "\n" for s in samples))
    return path


def test_parses_one_sample_into_one_lid_heater_event(db, tmp_path):
    from aquila_web.lid_parser import import_lid_samples
    log_dir = tmp_path / "logs" / "lid_heater"
    sample = _sample("s1")
    _write_log(log_dir, sample)

    count = import_lid_samples(log_dir=str(log_dir))

    assert count == 1
    pending = db.get_pending_events()
    assert len(pending) == 1
    assert pending[0]["event_type"] == "lid_heater_sample"
    assert pending[0]["payload"] == sample


def test_re_parsing_the_same_log_enqueues_nothing_twice(db, tmp_path):
    """The parser re-scans the whole log every sync cycle, so idempotency is
    not an optimisation -- without it every Sample would be sent repeatedly."""
    from aquila_web.lid_parser import import_lid_samples
    log_dir = tmp_path / "logs" / "lid_heater"
    _write_log(log_dir, _sample("s1"), _sample("s2"))

    first = import_lid_samples(log_dir=str(log_dir))
    second = import_lid_samples(log_dir=str(log_dir))

    assert (first, second) == (2, 0)
    assert len(db.get_pending_events()) == 2


def test_reads_the_rotated_file_before_the_active_one(db, tmp_path):
    """A rotation must not lose the Samples written before it, nor reorder
    them: the .1 holds the older stretch."""
    from aquila_web.lid_parser import import_lid_samples
    log_dir = tmp_path / "logs" / "lid_heater"
    _write_log(log_dir, _sample("older"), name="lid_samples.log.1")
    _write_log(log_dir, _sample("newer"))

    import_lid_samples(log_dir=str(log_dir))

    ids = [e["payload"]["sample_id"] for e in db.get_pending_events()]
    assert ids == ["older", "newer"]


def test_a_malformed_line_does_not_stop_the_rest(db, tmp_path):
    """A half-written line from a power cut must not wedge the whole import."""
    from aquila_web.lid_parser import import_lid_samples
    log_dir = tmp_path / "logs" / "lid_heater"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "lid_samples.log").write_text(
        json.dumps(_sample("good1")) + "\n"
        + '{"sample_id": "truncated", "mean_vo\n'
        + json.dumps({"device_ts": "no id here"}) + "\n"
        + json.dumps(_sample("good2")) + "\n"
    )

    count = import_lid_samples(log_dir=str(log_dir))

    assert count == 2
    ids = [e["payload"]["sample_id"] for e in db.get_pending_events()]
    assert ids == ["good1", "good2"]

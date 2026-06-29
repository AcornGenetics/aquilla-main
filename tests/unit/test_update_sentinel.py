"""Unit tests for the OTA update completion sentinel state machine (issue #183).

The sentinel is a small on-disk record that survives the container swap and the
reboot, so a freshly-started container knows an update just finished. These tests
exercise the pure logic only — no FastAPI, no hardware.

Run: pytest tests/unit/test_update_sentinel.py -v
"""
from datetime import datetime, timedelta, timezone

from aquila_web import update_sentinel as us

_TS = "2026-06-19T14:00:00Z"
_BASE = datetime(2026, 6, 19, 14, 0, 0, tzinfo=timezone.utc)


def test_write_then_read_round_trips_state(tmp_path):
    path = tmp_path / "last_update.json"
    us.write_sentinel(str(path), "reboot_pending", "2026-06-19T14:00:00Z")
    record = us.read_sentinel(str(path))
    assert record["state"] == "reboot_pending"
    assert record["ts"] == "2026-06-19T14:00:00Z"


def test_read_returns_none_when_absent_or_corrupt(tmp_path):
    assert us.read_sentinel(str(tmp_path / "nope.json")) is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("not json {{{")
    assert us.read_sentinel(str(corrupt)) is None


def test_fresh_reboot_pending_resolves_to_reboot():
    rec = {"state": "reboot_pending", "ts": _TS}
    now = _BASE + timedelta(seconds=30)
    assert us.next_startup_action(rec, now, ttl_seconds=600) == "reboot"


def test_fresh_show_complete_resolves_to_show_complete():
    rec = {"state": "show_complete", "ts": _TS}
    now = _BASE + timedelta(seconds=30)
    assert us.next_startup_action(rec, now, ttl_seconds=600) == "show_complete"


def test_sentinel_past_ttl_is_ignored():
    rec = {"state": "show_complete", "ts": _TS}
    now = _BASE + timedelta(seconds=601)
    assert us.next_startup_action(rec, now, ttl_seconds=600) == "none"


def test_no_record_resolves_to_none():
    now = _BASE + timedelta(seconds=30)
    assert us.next_startup_action(None, now, ttl_seconds=600) == "none"


def test_clear_removes_the_sentinel(tmp_path):
    path = tmp_path / "last_update.json"
    us.write_sentinel(str(path), "show_complete", _TS)
    us.clear_sentinel(str(path))
    assert us.read_sentinel(str(path)) is None
    us.clear_sentinel(str(path))  # idempotent — no error when already gone


# --- failed-update detection (spec_ota_update_failed_detection.md) -------------

def test_classify_update_complete_when_running_matches_target():
    assert us.classify_update("sha256:aaa", "sha256:aaa") == "complete"


def test_classify_update_failed_when_running_differs_from_target():
    assert us.classify_update("sha256:new", "sha256:old") == "failed"


def test_classify_update_unknown_when_a_digest_is_missing():
    # Host unreachable / no digest recorded -> can't tell -> caller stays optimistic.
    assert us.classify_update("sha256:new", None) == "unknown"
    assert us.classify_update(None, "sha256:old") == "unknown"
    assert us.classify_update("sha256:x", "") == "unknown"


def test_write_sentinel_round_trips_target_digest(tmp_path):
    path = tmp_path / "last_update.json"
    us.write_sentinel(str(path), "reboot_pending", _TS, target_digest="sha256:new")
    assert us.read_sentinel(str(path))["target_digest"] == "sha256:new"


def test_fresh_show_failed_resolves_to_show_failed():
    rec = {"state": "show_failed", "ts": _TS}
    now = _BASE + timedelta(seconds=30)
    assert us.next_startup_action(rec, now, ttl_seconds=600) == "show_failed"

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

def test_classify_update_complete_when_target_is_among_running_digests():
    # Host reports every digest the running image is known by; a match on any means
    # the target image is what booted.
    assert us.classify_update("sha256:new", "sha256:old", ["sha256:new"]) == "complete"


def test_classify_update_failed_only_when_old_image_is_positively_running():
    # Crash mid-update: the device is provably still on the exact pre-update image.
    assert us.classify_update("sha256:new", "sha256:old", ["sha256:old"]) == "failed"


def test_classify_update_unknown_when_running_matches_neither():
    # Digest formats don't line up (e.g. index vs platform manifest). We must NOT
    # call this a failure — stay optimistic so a good update never shows "Failed".
    assert us.classify_update("sha256:new", "sha256:old", ["sha256:something-else"]) == "unknown"


def test_classify_update_unknown_when_no_running_digests():
    assert us.classify_update("sha256:new", "sha256:old", []) == "unknown"
    assert us.classify_update("sha256:new", "sha256:old", None) == "unknown"


def test_write_sentinel_round_trips_target_digest(tmp_path):
    path = tmp_path / "last_update.json"
    us.write_sentinel(str(path), "reboot_pending", _TS, target_digest="sha256:new")
    assert us.read_sentinel(str(path))["target_digest"] == "sha256:new"


def test_write_sentinel_round_trips_prev_digest(tmp_path):
    path = tmp_path / "last_update.json"
    us.write_sentinel(str(path), "reboot_pending", _TS,
                      target_digest="sha256:new", prev_digest="sha256:old")
    assert us.read_sentinel(str(path))["prev_digest"] == "sha256:old"


def test_fresh_show_failed_resolves_to_show_failed():
    rec = {"state": "show_failed", "ts": _TS}
    now = _BASE + timedelta(seconds=30)
    assert us.next_startup_action(rec, now, ttl_seconds=600) == "show_failed"


def test_reboot_pending_does_not_expire():
    # The headline scenario is power loss mid-update: the device may be off for far
    # longer than the TTL before someone re-powers it. The pending update must still
    # be verified on that next boot, not silently dropped.
    rec = {"state": "reboot_pending", "ts": _TS}
    now = _BASE + timedelta(days=7)
    assert us.next_startup_action(rec, now, ttl_seconds=600) == "reboot"


def test_show_failed_does_not_expire():
    # A failure must wait on disk until the operator actually sees and acks it.
    rec = {"state": "show_failed", "ts": _TS}
    now = _BASE + timedelta(days=7)
    assert us.next_startup_action(rec, now, ttl_seconds=600) == "show_failed"

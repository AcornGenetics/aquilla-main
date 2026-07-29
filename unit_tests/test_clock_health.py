"""Clock trustworthiness (#353).

These Pis have no battery-backed RTC, and local_db stamps every outbox Event with
`datetime.utcnow()`. A device that boots with a wrong clock writes wrong
timestamps into the analytics warehouse — permanently, and in the worst window:
immediately after boot, while startup and first-run Events are queued.

The distinction under test is `unknown` vs `synced`. A clock that cannot be
verified must not report as trusted.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# unit_tests/ has no conftest, so the repo root is added the same way the other
# tests in this directory do it.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from aquila_web import clock_health as ch  # noqa: E402

BUILD = "2026-07-01T00:00:00Z"


def _at(dt_str):
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


# ── The one-sided lower-bound test ────────────────────────────────────────────

def test_clock_before_build_is_detected():
    """A device cannot be running software that has not been built yet."""
    assert ch.clock_is_before_build(BUILD, now=_at("2026-06-30T23:59:00Z")) is True


def test_clock_at_epoch_is_detected():
    """The dominant failure: an RTC-less Pi booting to 1970."""
    assert ch.clock_is_before_build(BUILD, now=_at("1970-01-01T00:00:00Z")) is True


def test_clock_after_build_passes_the_lower_bound():
    assert ch.clock_is_before_build(BUILD, now=_at("2026-07-28T00:00:00Z")) is False


def test_no_baked_build_time_cannot_be_evaluated():
    """Images from before #351 have no build_time. None is not False."""
    assert ch.clock_is_before_build(None) is None
    assert ch.clock_is_before_build("unknown") is None
    assert ch.clock_is_before_build("not-a-date") is None


# ── The systemd flag ──────────────────────────────────────────────────────────

def test_sync_flag_absent_directory_is_unknown_not_unsynced(tmp_path, monkeypatch):
    """In a container the flag is invisible unless bind-mounted. Absence of the
    mount is not evidence of a bad clock."""
    monkeypatch.setattr(ch, "SYNC_FLAG_PATH", str(tmp_path / "nope" / "synchronized"))
    assert ch.ntp_sync_flag() is None


def test_sync_flag_present_means_synced(tmp_path, monkeypatch):
    d = tmp_path / "timesync"
    d.mkdir()
    (d / "synchronized").write_text("")
    monkeypatch.setattr(ch, "SYNC_FLAG_PATH", str(d / "synchronized"))
    assert ch.ntp_sync_flag() is True


def test_mounted_but_missing_flag_means_unsynced(tmp_path, monkeypatch):
    """The directory exists (so it IS mounted) but NTP has not synced."""
    d = tmp_path / "timesync"
    d.mkdir()
    monkeypatch.setattr(ch, "SYNC_FLAG_PATH", str(d / "synchronized"))
    assert ch.ntp_sync_flag() is False


# ── Combined verdict ──────────────────────────────────────────────────────────

def _no_mount(monkeypatch, tmp_path):
    monkeypatch.setattr(ch, "SYNC_FLAG_PATH", str(tmp_path / "absent" / "synchronized"))


def _mounted(monkeypatch, tmp_path, synced):
    d = tmp_path / "timesync"
    d.mkdir(exist_ok=True)
    if synced:
        (d / "synchronized").write_text("")
    monkeypatch.setattr(ch, "SYNC_FLAG_PATH", str(d / "synchronized"))


def test_synced_flag_gives_a_trusted_clock(tmp_path, monkeypatch):
    _mounted(monkeypatch, tmp_path, synced=True)
    s = ch.clock_status(BUILD, now=_at("2026-07-28T00:00:00Z"))
    assert s["clock_status"] == ch.SYNCED
    assert s["clock_trusted"] is True


def test_clock_before_build_overrides_a_synced_flag(tmp_path, monkeypatch):
    """A clock earlier than the running build is wrong whatever systemd says."""
    _mounted(monkeypatch, tmp_path, synced=True)
    s = ch.clock_status(BUILD, now=_at("2026-06-01T00:00:00Z"))
    assert s["clock_status"] == ch.UNSYNCED
    assert s["clock_trusted"] is False
    assert "build" in s["clock_reason"]


def test_unsynced_flag_is_reported(tmp_path, monkeypatch):
    _mounted(monkeypatch, tmp_path, synced=False)
    s = ch.clock_status(BUILD, now=_at("2026-07-28T00:00:00Z"))
    assert s["clock_status"] == ch.UNSYNCED
    assert s["clock_trusted"] is False


def test_no_mount_and_plausible_clock_is_unknown_not_trusted(tmp_path, monkeypatch):
    """The lower-bound test passing does not prove the clock is right — a clock
    set far into the future passes it too."""
    _no_mount(monkeypatch, tmp_path)
    s = ch.clock_status(BUILD, now=_at("2026-07-28T00:00:00Z"))
    assert s["clock_status"] == ch.UNKNOWN
    assert s["clock_trusted"] is False


def test_no_mount_and_no_build_time_is_unknown(tmp_path, monkeypatch):
    _no_mount(monkeypatch, tmp_path)
    s = ch.clock_status(None)
    assert s["clock_status"] == ch.UNKNOWN
    assert s["clock_trusted"] is False


def test_a_clock_in_the_far_future_is_not_caught():
    """Documenting the known limit: the lower bound is one-sided by design.

    This is why the systemd flag is preferred when present and why `unknown` is a
    distinct answer rather than being folded into `synced`.
    """
    assert ch.clock_is_before_build(BUILD, now=_at("2099-01-01T00:00:00Z")) is False

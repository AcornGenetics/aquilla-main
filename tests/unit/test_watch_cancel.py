"""
Unit tests for watch_cancel.py — the live self-cancel monitor (issue #159).

Pure logic (color decisions + header state); the tail-follow render loop is
manual/on-device. Imported via sys.path like tests/unit/test_wifi_helpers.py.
"""
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))

import watch_cancel as wc  # noqa: E402


class TestClassifyColor:
    def test_forced_stop_is_red(self):
        line = "2026-06-16 14:02:20,100 - ERROR - Backend unreachable for 10 consecutive polls — forcing stop"
        assert wc.classify_color(line) == "red"

    def test_poll_ladder_is_yellow(self):
        line = "2026-06-16 14:02:18,000 - WARNING - Error polling stop request (7/10): timeout"
        assert wc.classify_color(line) == "yellow"

    def test_cancel_markers_are_magenta(self):
        assert wc.classify_color("... - INFO - Stop request detected") == "magenta"
        assert wc.classify_color("... - INFO - Run stopped by user") == "magenta"
        assert wc.classify_color("... - INFO - Stop button pressed") == "magenta"

    def test_lid_lifecycle_is_cyan(self):
        assert wc.classify_color("... - INFO - LID WORKER START tid=1 live=1") == "cyan"

    def test_plain_line_is_none(self):
        assert wc.classify_color("... - INFO - Hold 95 for 30s") is None


class TestMonitor:
    def test_lid_line_updates_live_workers(self):
        m = wc.Monitor()
        m.feed("lid", "2026-06-16 14:00:00,000 - INFO - LID WORKER START tid=1 live=1")
        m.feed("lid", "2026-06-16 14:01:00,000 - INFO - LID WORKER START tid=2 live=3")
        assert m.live_workers == 3

    def test_poll_ladder_updates_and_run_start_resets(self):
        m = wc.Monitor()
        m.feed("logger", "... - WARNING - Error polling stop request (4/10): timeout")
        assert m.poll_failures == 4
        m.feed("logger", "... - WARNING - Error polling stop request (7/10): timeout")
        assert m.poll_failures == 7
        m.feed("logger", "2026-06-16 14:05:00,000 - INFO - RUN START index=5")
        assert m.poll_failures == 0

    def test_seconds_since_app_from_last_app_line(self):
        m = wc.Monitor()
        assert m.seconds_since_app(datetime(2026, 6, 16, 14, 2, 20)) is None
        m.feed("app", "2026-06-16 14:02:15,000 - INFO - GET /button_status/")
        assert m.seconds_since_app(datetime(2026, 6, 16, 14, 2, 20)) == 5.0

    def test_cancel_marker_latches_cancel_fired(self):
        m = wc.Monitor()
        assert m.cancel_fired is False
        m.feed("logger", "2026-06-16 14:02:25,000 - INFO - Stop request detected")
        assert m.cancel_fired is True

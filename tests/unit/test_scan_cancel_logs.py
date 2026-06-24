"""
Unit tests for scan_cancel_logs.py — the self-cancel log classifier (issue #158).

Pure logic over in-memory log lines; no hardware, no files. Imported via sys.path
the same way tests/unit/test_wifi_helpers.py imports a script module.
"""
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))

import scan_cancel_logs as scl  # noqa: E402


class TestParseTimestamp:
    def test_parses_a_standard_log_line(self):
        line = "2026-06-16 14:02:11,304 - INFO - LID WORKER START tid=1 live=1"
        assert scl.parse_timestamp(line) == datetime(2026, 6, 16, 14, 2, 11, 304000)

    def test_returns_none_for_non_timestamped_line(self):
        assert scl.parse_timestamp("Traceback (most recent call last):") is None
        assert scl.parse_timestamp("") is None


class TestFindCancels:
    def test_locates_a_self_cancel_event(self):
        lines = [
            "2026-06-16 14:02:00,000 - INFO - RUN START index=1",
            "2026-06-16 14:02:25,500 - INFO - Stop request detected",
            "2026-06-16 14:02:25,600 - INFO - Run stopped by user",
        ]
        assert scl.find_cancels(lines) == [1]


class TestClassifyWindow:
    def test_forced_stop_without_press_is_trigger2(self):
        logger_lines = [
            "2026-06-16 14:02:20,000 - WARNING - Error polling stop request (10/10): timeout",
            "2026-06-16 14:02:20,100 - ERROR - Backend unreachable for 10 consecutive polls — forcing stop",
            "2026-06-16 14:02:20,200 - INFO - Stop request detected",
        ]
        app_lines = [
            "2026-06-16 14:02:14,000 - INFO - Run button pressed",
        ]
        verdict = scl.classify_window(logger_lines, app_lines)
        assert verdict.code == "TRIGGER2"

    def test_stop_button_pressed_is_h3(self):
        logger_lines = [
            "2026-06-16 14:02:25,200 - INFO - Stop request detected",
        ]
        app_lines = [
            "2026-06-16 14:02:25,000 - INFO - Stop button pressed",
        ]
        verdict = scl.classify_window(logger_lines, app_lines)
        assert verdict.code == "H3"

    def test_lid_worker_accumulation_is_h1(self):
        logger_lines = [
            "2026-06-16 14:02:20,100 - ERROR - Backend unreachable for 10 consecutive polls — forcing stop",
            "2026-06-16 14:02:20,200 - INFO - Stop request detected",
        ]
        lid_lines = [
            "2026-06-16 14:00:00,000 - INFO - LID WORKER START tid=1 live=1",
            "2026-06-16 14:01:00,000 - INFO - LID WORKER START tid=2 live=2",
            "2026-06-16 14:02:00,000 - INFO - LID WORKER START tid=3 live=3",
        ]
        verdict = scl.classify_window(logger_lines, [], lid_lines=lid_lines)
        assert verdict.code == "H1"

    def test_cancel_with_no_explanation_is_h8(self):
        logger_lines = [
            "2026-06-16 14:02:25,000 - INFO - Stop request detected",
            "2026-06-16 14:02:25,100 - INFO - Run stopped by user",
        ]
        verdict = scl.classify_window(logger_lines, [])
        assert verdict.code == "H8"

    def test_no_signal_is_h0(self):
        logger_lines = [
            "2026-06-16 14:02:00,000 - INFO - RUN START index=1",
            "2026-06-16 14:02:30,000 - INFO - Hold 95 for 30s",
        ]
        verdict = scl.classify_window(logger_lines, [])
        assert verdict.code == "H0"


class TestCoincidenceDelta:
    def test_seconds_between_last_app_line_and_cancel(self):
        app_lines = [
            "2026-06-16 14:02:10,000 - INFO - GET /button_status/",
            "2026-06-16 14:02:15,000 - INFO - GET /button_status/",  # last before cancel
            "2026-06-16 14:02:40,000 - INFO - GET /button_status/",  # after cancel
        ]
        cancel_ts = datetime(2026, 6, 16, 14, 2, 20, 0)
        # app went silent 5s before the controller gave up at :20
        assert scl.coincidence_delta(app_lines, cancel_ts) == 5.0

    def test_none_when_no_app_line_precedes_cancel(self):
        app_lines = ["2026-06-16 14:02:40,000 - INFO - GET /button_status/"]
        cancel_ts = datetime(2026, 6, 16, 14, 2, 20, 0)
        assert scl.coincidence_delta(app_lines, cancel_ts) is None

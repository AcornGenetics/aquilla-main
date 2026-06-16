"""
Unit tests for snapshot_resources.py — per-run resource snapshot tool (issue #160).

Pure logic (trend analysis + CSV model); host metric collection is on-device.
Imported via sys.path like tests/unit/test_wifi_helpers.py.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))

import snapshot_resources as sr  # noqa: E402


class TestMonotonicTrend:
    def test_strictly_increasing_up_is_true(self):
        assert sr.monotonic_trend([56.0, 61.0, 68.0, 74.0], direction="up") is True

    def test_strictly_decreasing_down_is_true(self):
        # disk_free_mb falling every run = disk filling up
        assert sr.monotonic_trend([900.0, 700.0, 400.0, 120.0], direction="down") is True

    def test_non_monotonic_or_too_few_points_is_false(self):
        assert sr.monotonic_trend([56.0, 61.0, 60.0, 74.0], direction="up") is False
        assert sr.monotonic_trend([56.0, 56.0], direction="up") is False  # plateau
        assert sr.monotonic_trend([56.0], direction="up") is False        # one point
        assert sr.monotonic_trend([], direction="up") is False


class TestCsvModel:
    def test_write_then_read_round_trip(self, tmp_path):
        csv_path = tmp_path / "snapshots.csv"
        sr.write_snapshot(csv_path, {"label": "before-run-1", "soc_temp": "56.0"})
        sr.write_snapshot(csv_path, {"label": "after-run-1", "soc_temp": "61.0"})
        rows = sr.read_snapshots(csv_path)
        assert [r["label"] for r in rows] == ["before-run-1", "after-run-1"]
        assert rows[1]["soc_temp"] == "61.0"


class TestAnalyze:
    def test_climbing_soc_temp_flags_h4(self):
        rows = [
            {"label": "r1", "soc_temp": "56.0"},
            {"label": "r2", "soc_temp": "63.0"},
            {"label": "r3", "soc_temp": "71.0"},
        ]
        flags = sr.analyze(rows)
        flagged = {f.metric: f.hypothesis for f in flags}
        assert flagged.get("soc_temp") == "H4"

    def test_falling_disk_free_flags_disk(self):
        rows = [
            {"label": "r1", "disk_free_mb": "900"},
            {"label": "r2", "disk_free_mb": "500"},
            {"label": "r3", "disk_free_mb": "120"},
        ]
        flagged = {f.metric: f.hypothesis for f in sr.analyze(rows)}
        assert flagged.get("disk_free_mb") == "DISK"

    def test_flat_or_noisy_metric_is_not_flagged(self):
        rows = [
            {"label": "r1", "ctrl_rss": "100000"},
            {"label": "r2", "ctrl_rss": "100000"},  # flat
            {"label": "r3", "ctrl_rss": "99000"},   # dips
        ]
        assert "ctrl_rss" not in {f.metric for f in sr.analyze(rows)}

    def test_blank_and_non_numeric_values_are_skipped(self):
        # Missing sources leave blank cells; analysis must not crash, and a
        # series reduced below 2 numeric points must not be flagged.
        rows = [
            {"label": "r1", "app_fds": "", "soc_temp": "not-a-number"},
            {"label": "r2", "app_fds": "50", "soc_temp": ""},
            {"label": "r3", "app_fds": "", "soc_temp": "60.0"},
        ]
        flags = sr.analyze(rows)  # must not raise
        assert "app_fds" not in {f.metric for f in flags}
        assert "soc_temp" not in {f.metric for f in flags}


class TestHistoryBytes:
    def test_finds_logs_history_json(self, tmp_path):
        # The real device path is logs/history.json (BASE_DIR/logs/history.json).
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "history.json").write_text("x" * 123)
        size = sr.first_existing_size([
            str(tmp_path / "data" / "history.json"),   # absent
            str(logs / "history.json"),                # present
        ])
        assert size == "123"

    def test_returns_blank_when_none_exist(self, tmp_path):
        assert sr.first_existing_size([str(tmp_path / "nope.json")]) == ""

    def test_default_candidates_include_logs_path_first(self):
        # Regression guard for the reported bug: logs/ must be checked.
        assert "logs/history.json" in sr.HISTORY_CANDIDATES

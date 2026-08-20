"""
Unit tests for Lid Heater Sample emission (issue #452, ADR-022).

Samples go to a dedicated, non-propagating JSON-lines log, exactly as Homing
Samples do (ADR-021): a local file append only, so emitting never stalls the
lid-heater control loop with network or database work.
"""
import json
import logging

import pytest

from aq_lib import lid_heater_log

pytestmark = pytest.mark.unit


SAMPLE = {
    "sample_id": "abc123",
    "device_ts": "2026-08-20T09:00:00Z",
    "run_timestamp": "2026-08-20T08:59:00Z",
    "window_kind": "settled",
    "window_seconds": 300.0,
    "mean_voltage": 0.32,
}


class TestEmission:
    def test_writes_the_sample_as_one_json_line(self, tmp_path):
        path = lid_heater_log.configure_lid_sample_logger(log_dir=str(tmp_path))

        lid_heater_log.emit_lid_sample(SAMPLE)

        lines = [l for l in open(path).read().splitlines() if l.strip()]
        assert len(lines) == 1
        assert json.loads(lines[0]) == SAMPLE

    def test_reconfiguring_does_not_double_write(self, tmp_path):
        """configure runs at process start and must be safe to call again --
        a duplicated handler would enqueue every Sample twice downstream."""
        lid_heater_log.configure_lid_sample_logger(log_dir=str(tmp_path))
        path = lid_heater_log.configure_lid_sample_logger(log_dir=str(tmp_path))

        lid_heater_log.emit_lid_sample(SAMPLE)

        lines = [l for l in open(path).read().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_samples_stay_out_of_the_main_log(self, tmp_path):
        """A Sample every 300 s would drown logger.log, and the lid heater's
        own per-read debug lines must stay out of the Sample log."""
        lid_heater_log.configure_lid_sample_logger(log_dir=str(tmp_path))
        caught = []

        class _Spy(logging.Handler):
            def emit(self, record):
                caught.append(record)

        parent = logging.getLogger("aquila")
        spy = _Spy()
        parent.addHandler(spy)
        try:
            lid_heater_log.emit_lid_sample(SAMPLE)
        finally:
            parent.removeHandler(spy)

        assert caught == []

"""Hardware integration test for Lid Heater Sample emission (issue #452, ADR-022).

Requires a real Pi: importing aq_lib.regulate pulls in RPi.GPIO and the I2C ADC.
Skipped in CI. The Sample Window logic itself is hardware-free and covered by
tests/unit/test_lid_heater_window.py -- what can only be checked on device is the
wiring: that a running worker actually feeds readings in, and that stopping it
flushes the open window as a Sample on disk.

Run on device: pytest tests/unit/hardware/test_lid_heater_telemetry.py -m hardware
"""
import json
import time
from threading import Event, Thread

import pytest

from aq_lib import lid_heater_log

RUN_TS = "2026-08-20T09:00:00Z"


def _samples_written(path):
    with open(path) as fp:
        return [json.loads(line) for line in fp if line.strip()]


@pytest.mark.hardware
def test_a_run_flushes_its_open_window_as_a_sample(tmp_path):
    from aq_lib.regulate import lid_heater_worker

    path = lid_heater_log.configure_lid_sample_logger(log_dir=str(tmp_path))
    stop_event, quiet_event = Event(), Event()

    t = Thread(target=lid_heater_worker, args=(stop_event, quiet_event),
               kwargs={"run_timestamp": RUN_TS}, daemon=True)
    t.start()
    time.sleep(5)          # several real ADC reads
    stop_event.set()
    t.join(timeout=10)

    samples = _samples_written(path)
    assert len(samples) == 1, "the partial window must be flushed on stop"

    sample = samples[0]
    assert sample["run_timestamp"] == RUN_TS
    assert sample["reading_count"] >= 3, "readings should have reached the window"
    assert sample["live_worker_count"] == 1
    assert 0.0 < sample["mean_voltage"] < 4.096
    assert sample["min_voltage"] <= sample["mean_voltage"] <= sample["max_voltage"]


@pytest.mark.hardware
def test_a_worker_with_no_run_emits_nothing(tmp_path):
    """Samples are Run-scoped by definition, so the standalone diagnostic path
    must stay silent rather than emit Samples referencing no Run."""
    from aq_lib.regulate import lid_heater_worker

    path = lid_heater_log.configure_lid_sample_logger(log_dir=str(tmp_path))
    stop_event, quiet_event = Event(), Event()

    t = Thread(target=lid_heater_worker, args=(stop_event, quiet_event), daemon=True)
    t.start()
    time.sleep(3)
    stop_event.set()
    t.join(timeout=10)

    assert _samples_written(path) == []

"""Hardware integration test for issue #157 lid-worker instrumentation.

Requires a real Pi: importing sentri_lib.regulate pulls in RPi.GPIO and the I2C ADC.
Skipped in CI. Verifies that a lid-heater worker registers on entry and, after a
clean stop, the live count returns to zero (no leak on the happy path).

Run on device: pytest tests/unit/hardware/test_lid_worker_instrumentation.py -m hardware
"""
from threading import Event, Thread

import pytest

from sentri_lib import lid_worker_metrics as lwm


@pytest.mark.hardware
def test_clean_run_leaves_no_live_workers():
    from sentri_lib.regulate import lid_heater_worker

    lwm.reset()
    stop_event = Event()
    quiet_event = Event()

    t = Thread(target=lid_heater_worker, args=(stop_event, quiet_event), daemon=True)
    t.start()

    # Let the worker register and take at least one reading.
    import time
    time.sleep(2)
    assert lwm.live_count() == 1, "worker should be registered while running"

    stop_event.set()
    t.join(timeout=5)

    assert not t.is_alive(), "worker should exit after stop_event is set"
    assert lwm.live_count() == 0, "clean exit must deregister the worker"

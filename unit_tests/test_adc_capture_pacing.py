"""
Unit test for ADC capture pacing clock-source (issue #512).

OpticalRead.capture_blink paces its 60 Hz sampling with sleep(max(0, j/60 - dt)).
If dt is measured with the wall clock, a mid-capture BACKWARD clock step (NTP can
step either way) makes dt hugely negative, so the sleep balloons to ~the step
size — the observed multi-thousand-second capture stall. Measuring dt
monotonically keeps every pacing sleep bounded.

Hardware is stubbed so adc_class imports off-Pi; OpticalRead is built via
__new__ to skip the hardware __init__. Marked ``unit``.
"""
import io
import sys
import types
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

# Stub hardware deps so `import aq_lib.adc_class` works off-device.
_gpio = types.ModuleType("RPi.GPIO")
for _name, _val in (("HIGH", 1), ("LOW", 0), ("IN", 0), ("OUT", 1), ("BCM", 11)):
    setattr(_gpio, _name, _val)
_gpio.setwarnings = lambda *a, **k: None
_gpio.setmode = lambda *a, **k: None
_gpio.setup = lambda *a, **k: None
_gpio.output = lambda *a, **k: None
_rpi = types.ModuleType("RPi")
_rpi.GPIO = _gpio
sys.modules.setdefault("RPi", _rpi)
sys.modules.setdefault("RPi.GPIO", _gpio)
sys.modules.setdefault("spidev", types.ModuleType("spidev"))

import aq_lib.adc_class as adc_mod  # noqa: E402
from aq_lib.run_clock import MonotonicStopwatch  # noqa: E402


class FakeTime:
    """Patches the whole `time` module seen by adc_class.

    - monotonic() never jumps and advances only when sleep() is called.
    - time() (wall clock) steps BACKWARD ~95 min after the first read.
    - sleep() is recorded, not actually slept.
    """

    def __init__(self):
        self.mono = 1000.0
        self.sleeps = []
        self._wall_reads = 0

    def monotonic(self):
        return self.mono

    def time(self):
        self._wall_reads += 1
        if self._wall_reads == 1:
            return 1000.0
        return 1000.0 - 5700.0  # NTP steps the clock backward ~95 min

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.mono += 1.0 / 60.0  # real time advances monotonically


def _make_adc(fake):
    adc = adc_mod.OpticalRead.__new__(adc_mod.OpticalRead)
    adc.gpio = MagicMock()
    adc.spi = MagicMock()
    adc.spi.xfer2.return_value = [0, 0, 0, 0]
    adc.LED_ON = 1
    adc.LED_OFF = 0
    adc.data_file = io.StringIO()
    adc.t0 = 1000.0  # wall-clock baseline (retained for log correlation)
    adc._clock = fake.monotonic
    adc._run_stopwatch = MonotonicStopwatch(clock=fake.monotonic)
    adc._run_stopwatch.start()
    return adc


def test_capture_pacing_bounded_despite_backward_wall_step(monkeypatch):
    fake = FakeTime()
    monkeypatch.setattr(adc_mod, "time", fake)
    adc = _make_adc(fake)

    adc.capture_blink("rox")

    # Pacing is 60 Hz, so no single sleep should exceed ~1 s. A wall-clock-based
    # dt would have produced a ~5700 s sleep.
    assert max(fake.sleeps) <= 2.0

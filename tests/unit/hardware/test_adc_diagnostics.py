"""Pure-logic tests for the Tier 1 ADC diagnostics (#517 Slice 3).

adc_class imports RPi.GPIO and spidev at module load, so those are stubbed into
sys.modules before import. The diagnostics under test (`_check_frame`, the health
counters, the RDY constants) touch no hardware; the SPI read loops that drive the
n_retries/n_failed_reads increments are hardware paths exercised on-device only.
"""
import sys
import types

import pytest
from unittest.mock import patch


@pytest.fixture
def adc_module():
    fake_rpi = types.ModuleType("RPi")
    fake_gpio = types.ModuleType("RPi.GPIO")
    for name in ("LOW", "HIGH", "IN", "OUT", "BCM"):
        setattr(fake_gpio, name, 0)
    for fn in ("setwarnings", "setmode", "setup", "output"):
        setattr(fake_gpio, fn, lambda *a, **k: None)
    fake_rpi.GPIO = fake_gpio

    fake_spidev = types.ModuleType("spidev")
    fake_spidev.SpiDev = object

    with patch.dict(sys.modules, {
        "RPi": fake_rpi,
        "RPi.GPIO": fake_gpio,
        "spidev": fake_spidev,
    }):
        sys.modules.pop("aq_lib.adc_class", None)
        import aq_lib.adc_class as m
        yield m
    sys.modules.pop("aq_lib.adc_class", None)


def _stub_reader(module):
    """An OpticalRead with only the state _check_frame needs, bypassing the
    hardware __init__."""
    obj = object.__new__(module.OpticalRead)
    obj.n_stale_frames = 0
    return obj


# --- RDY constants ---------------------------------------------------------

@pytest.mark.unit
def test_rdy_constants(adc_module):
    assert adc_module.ADC_RDY_ATTEMPTS_CAPTURE == 7
    assert adc_module.ADC_RDY_ATTEMPTS_AMBIENT == 20
    assert adc_module.ADC_RDY_SLEEP == 0.001


# --- _check_frame ----------------------------------------------------------

@pytest.mark.unit
def test_fresh_frame_byte0_zero_is_not_counted(adc_module):
    r = _stub_reader(adc_module)
    out = r._check_frame([0x00, 0x12, 0x34, 0x56], "rox")
    assert r.n_stale_frames == 0
    assert out == [0x00, 0x12, 0x34, 0x56]  # returned unchanged


@pytest.mark.unit
def test_stale_frame_full_byte0_is_counted(adc_module):
    r = _stub_reader(adc_module)
    r._check_frame([0xff, 0x00, 0x00, 0x00], "fam")
    assert r.n_stale_frames == 1


@pytest.mark.unit
def test_partial_byte0_is_counted(adc_module):
    """Partial ready-line values (byte0 != 0x00 and != 0xff) are stale too."""
    r = _stub_reader(adc_module)
    for b in (0x80, 0xc0, 0xf0, 0xfc):
        r._check_frame([b, 0x00, 0x00, 0x00], "rox")
    assert r.n_stale_frames == 4


@pytest.mark.unit
def test_empty_reply_is_not_counted(adc_module):
    r = _stub_reader(adc_module)
    assert r._check_frame([], "ambient") == []
    assert r.n_stale_frames == 0


@pytest.mark.unit
def test_counter_keeps_counting_past_the_log_cap(adc_module):
    """The warning is capped at 10 lines, but the counter itself keeps going."""
    r = _stub_reader(adc_module)
    for _ in range(12):
        r._check_frame([0xff, 0, 0, 0], "rox")
    assert r.n_stale_frames == 12

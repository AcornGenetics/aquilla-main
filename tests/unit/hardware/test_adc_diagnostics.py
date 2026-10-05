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


# --- half-period-aware -123 repair in mask_data (Slice 4, Tier 2) ----------
#
# data_both rows are 11-element [reply_rox, reply_fam, adc_rox, adc_fam, led,
# channel, tag1, tag2, pcr_t0, t0, t]. mask_data repairs the -123 sentinel in
# adc_rox (idx 2) / adc_fam (idx 3) in place. With blink_num=7 the LED
# half-periods are index groups [0..6], [7..13], ... so index 7 is the first
# sample of a new half-period and must NOT borrow index 6 (the other phase).
# 28 rows (4 groups of 7) reshape cleanly through mask_data's padding/fake-blink.

def _row(rox, fam=20.0, led=1):
    return [0, 0, rox, fam, led, "both", 1, 1, 0.0, 0.0, 0.0]


def _mask_reader(adc_module, rows, blink_num=7, scan_num=6):
    r = object.__new__(adc_module.OpticalRead)
    r.blink_num = blink_num
    r.scan_num = scan_num
    r.n_unrepairable = 0
    r.data_both = rows
    return r


@pytest.mark.unit
def test_repair_does_not_cross_half_period_boundary(adc_module):
    """A -123 at the start of a half-period (index 7) must take its in-period
    successor (index 8), never the previous half-period's value (index 6)."""
    rows = [_row(10.0) for _ in range(28)]
    rows[6][2] = 999.0      # previous half-period — must NOT be used
    rows[7][2] = -123       # first sample of this half-period
    rows[8][2] = 50.0       # in-period successor — must be used
    target = rows[7]
    _mask_reader(adc_module, rows).mask_data()
    assert target[2] == 50.0


@pytest.mark.unit
def test_interior_sentinel_averages_both_in_period_neighbours(adc_module):
    """A -123 mid-half-period with good neighbours both sides = their mean."""
    rows = [_row(10.0) for _ in range(28)]
    rows[2][2] = 10.0
    rows[3][2] = -123
    rows[4][2] = 20.0
    target = rows[3]
    _mask_reader(adc_module, rows).mask_data()
    assert target[2] == 15.0


@pytest.mark.unit
def test_no_sentinels_leaves_values_unchanged(adc_module):
    rows = [_row(10.0, 20.0) for _ in range(28)]
    targets = rows[:]  # keep references
    r = _mask_reader(adc_module, rows)
    r.mask_data()
    assert all(t[2] == 10.0 for t in targets)
    assert r.n_unrepairable == 0


@pytest.mark.unit
def test_unrepairable_sentinel_is_counted_and_defaults(adc_module):
    """index 0 has no in-period predecessor and a -123 successor → no usable
    neighbour → counted and defaulted to 2.0 (rox)."""
    rows = [_row(10.0) for _ in range(28)]
    rows[0][2] = -123
    rows[1][2] = -123
    target = rows[0]
    r = _mask_reader(adc_module, rows)
    r.mask_data()
    assert r.n_unrepairable >= 1
    assert target[2] == 2.0

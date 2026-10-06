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
    r.n_retries = r.n_failed_reads = r.n_stale_frames = 0
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
def test_slice7_no_pad_and_rows_per_capture_is_six_w(adc_module):
    """One tube = 2 real blinks = 4*w samples. mask_data writes the honest
    w-wide half-flashes (no pad to 10) and synthesizes a 3rd blink → 6*w rows
    per capture: 60 at w=10 (byte-identical), 42 at w=7 (#517 Slice 7)."""
    for w in (7, 10):
        rows = [_row(10.0, 20.0) for _ in range(4 * w)]
        r = _mask_reader(adc_module, rows, blink_num=w)
        r.mask_data()
        assert len(r.data_both2) == 4 * w   # no padding rows added
        assert len(r.data_both3) == 6 * w   # 3 blinks x 2*w


@pytest.mark.unit
def test_variantc_streaming_mask_is_byte_identical_to_batch(adc_module):
    """ADR-024: mask_data_streaming (bounded 2-pass window) must produce the
    exact same reshaped output as the whole-buffer mask_data, including the
    cross-pass -123 repair look-back and the n_unrepairable count."""
    scan_num = 6
    for w in (7, 10):
        pass_len = scan_num * 4 * w
        for n_passes in (1, 2, 3):
            base = []
            for i in range(n_passes * pass_len):
                r = _row(float(i % 13) - 3.0, float(i % 9) - 2.0)
                if i % 5 == 0:    # sentinels to exercise in-pass + cross-pass repair
                    r[2] = -123
                if i % 11 == 0:
                    r[3] = -123
                base.append(r)

            rb = _mask_reader(adc_module, [list(r) for r in base], blink_num=w, scan_num=scan_num)
            rb.mask_data()

            rs = _mask_reader(adc_module, [], blink_num=w, scan_num=scan_num)
            passes = [[list(base[p * pass_len + k]) for k in range(pass_len)] for p in range(n_passes)]
            stream = rs.mask_data_streaming(passes)

            assert stream == rb.data_both3, f"w={w} n_passes={n_passes}"
            assert rs.n_unrepairable == rb.n_unrepairable, f"w={w} n_passes={n_passes}"


@pytest.mark.unit
def test_variantc_recovery_from_raw_log_matches_live(adc_module, tmp_path):
    """ADR-024: reconstructing the optics file from the raw safety log yields the
    same output as the live out_data for the same capture (the write-time
    timestamp column is pinned via a fixed clock)."""
    import io
    from unittest.mock import patch
    scan_num, w, n_passes = 6, 7, 2
    pass_len = scan_num * 4 * w
    base = [_row(float(i % 13) - 3.0, float(i % 9) - 2.0) for i in range(n_passes * pass_len)]
    for i in range(0, len(base), 5):
        base[i][2] = -123

    with patch("time.time", lambda: 1000.0):
        live = _mask_reader(adc_module, [list(r) for r in base], blink_num=w, scan_num=scan_num)
        live.well_15 = False
        live.two_adcs = True
        live.both_channel_was_used = True
        live.t0 = 0.0
        live.data_file = io.StringIO()
        live.out_data()
        live_out = live.data_file.getvalue()

        raw_path = tmp_path / "raw.log"
        raw_path.write_text("".join(repr(r) + "\n" for r in base))

        rec = _mask_reader(adc_module, [], blink_num=w, scan_num=scan_num)
        rec.well_15 = False
        rec.two_adcs = True
        rec.t0 = 0.0
        rec.data_file = io.StringIO()
        rec.optics_from_raw_log(str(raw_path))
        rec_out = rec.data_file.getvalue()

    assert len(rec_out) > 0
    assert rec_out == live_out


@pytest.mark.unit
def test_variantc_recovery_drops_torn_trailing_line(adc_module, tmp_path):
    """A crash mid-write leaves a torn final line; recovery stops at the last
    intact pass rather than failing."""
    import io
    from unittest.mock import patch
    scan_num, w = 6, 7
    pass_len = scan_num * 4 * w
    base = [_row(1.0, 2.0) for _ in range(pass_len)]
    raw_path = tmp_path / "raw.log"
    raw_path.write_text("".join(repr(r) + "\n" for r in base) + "[0, 0, 1.0, 2.")  # torn line
    with patch("time.time", lambda: 1000.0):
        rec = _mask_reader(adc_module, [], blink_num=w, scan_num=scan_num)
        rec.well_15 = False
        rec.two_adcs = True
        rec.t0 = 0.0
        rec.data_file = io.StringIO()
        rec.optics_from_raw_log(str(raw_path))   # must not raise
    assert len(rec.data_file.getvalue()) > 0


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

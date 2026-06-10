"""
Integration tests: rapid terminal rise detection against real optics log files.

Each test verifies one of four labeled testing sets:

  Set 1  — Normal run. All tubes detected except rox2 which is a slow late-Cq
            rise that SHOULD still be detected.
  Set 2  — Tube 4 (fam + rox) has a rapid terminal rise and must be undetected.
  Set 3  — All tubes undetected (noise or rapid artifacts).
  Set 4  — Tube 1 (fam + rox) undetected due to rapid terminal rise.

Tests skip when the log files are not present (CI / machines without optics data).
"""
import os
import pytest
from aq_curve.curve import Curve
from aq_curve.evaluator import evaluate_curve, check_no_rapid_terminal_rise
from aq_curve.pcr_curve_helpers import get_curve_data

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "optics")

SET1 = "Testing1_set_1_2026-05-20_18-03-07.log"
SET2 = "Testing1_set_2_2026-05-20_19-15-38.log"
SET3 = "Testing1_set_3_2026-05-20_20-25-37.log"
SET4 = "Testing1_set_4_2026-05-20_21-36-36_.log"


def _skip_if_missing(fname):
    path = os.path.join(LOGS_DIR, fname)
    if not os.path.exists(path):
        pytest.skip(f"Log file not present: {fname}")
    return path


@pytest.fixture(scope="module")
def curve():
    return Curve(src_basedir=LOGS_DIR)


def _status(curve_obj, fname, dye, well):
    return evaluate_curve(curve_obj, fname, dye, well)["status"]


def _rapid(curve_obj, fname, dye, well):
    cd = get_curve_data(curve_obj, fname, dye, well)
    return not check_no_rapid_terminal_rise(cd, curve_obj)


# ---------------------------------------------------------------------------
# Set 1: slow late-Cq rise — rox2 MUST be detected
# ---------------------------------------------------------------------------

class TestSet1:
    def setup_method(self):
        _skip_if_missing(SET1)

    def test_rox2_slow_rise_detected(self, curve):
        """Rox 2 in set 1 is a genuine slow late-Cq signal and must be detected."""
        assert _status(curve, SET1, "rox", 2) == "detected"

    def test_rox2_not_flagged_as_rapid(self, curve):
        """Rox 2 rises slowly — the rapid-rise check must pass (return False)."""
        assert _rapid(curve, SET1, "rox", 2) is False

    def test_normal_channels_still_detected(self, curve):
        """All other Set 1 channels with clear amplification remain detected."""
        for dye in ("fam", "rox"):
            for well in (1, 3, 4):
                assert _status(curve, SET1, dye, well) == "detected", \
                    f"Set1 {dye} well {well} should be detected"


# ---------------------------------------------------------------------------
# Set 2: tube 4 rapid rise — both dye channels must be undetected
# ---------------------------------------------------------------------------

class TestSet2:
    def setup_method(self):
        _skip_if_missing(SET2)

    def test_fam4_undetected(self, curve):
        assert _status(curve, SET2, "fam", 4) == "undetected"

    def test_rox4_rapid_rise_detected(self, curve):
        """Rox 4 in set 2 must be flagged by the rapid-rise check."""
        assert _rapid(curve, SET2, "rox", 4) is True

    def test_rox4_undetected(self, curve):
        assert _status(curve, SET2, "rox", 4) == "undetected"

    def test_other_set2_wells_detected(self, curve):
        for dye in ("fam", "rox"):
            for well in (1, 2, 3):
                assert _status(curve, SET2, dye, well) == "detected", \
                    f"Set2 {dye} well {well} should be detected"


# ---------------------------------------------------------------------------
# Set 3: all tubes undetected
# ---------------------------------------------------------------------------

class TestSet3:
    def setup_method(self):
        _skip_if_missing(SET3)

    @pytest.mark.parametrize("dye,well", [
        ("fam", 1), ("fam", 2), ("fam", 3), ("fam", 4),
        ("rox", 1), ("rox", 2), ("rox", 3), ("rox", 4),
    ])
    def test_all_undetected(self, curve, dye, well):
        assert _status(curve, SET3, dye, well) == "undetected", \
            f"Set3 {dye} well {well} should be undetected"

    @pytest.mark.parametrize("dye,well", [("rox", 1), ("rox", 3)])
    def test_rapid_rise_flagged(self, curve, dye, well):
        """The rox channels with late steep rise must trigger the rapid-rise check."""
        assert _rapid(curve, SET3, dye, well) is True


# ---------------------------------------------------------------------------
# Set 4: tube 1 undetected, tubes 3 detected
# ---------------------------------------------------------------------------

class TestSet4:
    def setup_method(self):
        _skip_if_missing(SET4)

    def test_fam1_undetected(self, curve):
        assert _status(curve, SET4, "fam", 1) == "undetected"

    def test_fam1_flagged_as_rapid(self, curve):
        assert _rapid(curve, SET4, "fam", 1) is True

    def test_rox1_undetected(self, curve):
        assert _status(curve, SET4, "rox", 1) == "undetected"

    def test_fam3_detected(self, curve):
        assert _status(curve, SET4, "fam", 3) == "detected"

    def test_rox3_detected(self, curve):
        assert _status(curve, SET4, "rox", 3) == "detected"

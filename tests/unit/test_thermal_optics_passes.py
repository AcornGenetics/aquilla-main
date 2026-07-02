"""
Unit tests for count_optics_passes (#288, review follow-up).

read_passes must come from the profile's *planned* optics passes so an aborted
run's expected_lines is the intended total (complete=false, honest coverage),
not just what happened to fire before the abort.
"""
from aq_lib.thermal_parser import count_optics_passes


def test_counts_baseline_plus_one_per_cycle():
    steps = [
        {"setpoint": 95, "duration": 30},
        {"optics": True},                       # baseline pass
        {"repeat": [
            {"setpoint": 60, "duration": 30},
            {"optics": True},                   # one pass per cycle
        ], "cycles": 40},
    ]
    assert count_optics_passes(steps) == 41      # 1 baseline + 40 cycles


def test_profile_without_optics_counts_zero():
    steps = [{"setpoint": 95, "duration": 30}, {"setpoint": 60, "duration": 30}]
    assert count_optics_passes(steps) == 0


def test_malformed_profile_does_not_raise():
    assert count_optics_passes("not-a-profile") == 0

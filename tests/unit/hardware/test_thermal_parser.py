"""
Unit tests for aq_lib/thermal_parser.py

thermal_parser() is a pure generator — no hardware, no GPIO, no RPi.
"""
import pytest

from aq_lib.thermal_parser import thermal_parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect(steps, **kwargs):
    """Materialise the generator into a list for easy inspection."""
    return list(thermal_parser(steps, **kwargs))


# ---------------------------------------------------------------------------
# Single setpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_single_setpoint_produces_ramp_and_hold():
    """One setpoint step must emit exactly one ramp and one hold action."""
    steps = [{"setpoint": 95.0, "duration": 30.0}]
    actions = _collect(steps, last_temp=25.0)
    names = [a[0] for a in actions]
    assert names == ["ramp", "hold"]


@pytest.mark.unit
def test_single_setpoint_ramp_has_correct_temp():
    """The ramp action must target the setpoint temperature."""
    steps = [{"setpoint": 95.0, "duration": 30.0}]
    actions = _collect(steps, last_temp=25.0)
    ramp = actions[0]
    # tuple layout: (name, n, last_temp, setpoint, duration, last_time)
    assert ramp[3] == 95.0


@pytest.mark.unit
def test_single_setpoint_hold_duration_matches_profile():
    """The hold action duration must equal the value given in the step."""
    steps = [{"setpoint": 95.0, "duration": 45.0}]
    actions = _collect(steps, last_temp=25.0)
    hold = actions[1]
    # duration is index 4
    assert hold[4] == 45.0


@pytest.mark.unit
def test_single_setpoint_hold_setpoint_matches():
    """The hold action's setpoint must equal the step setpoint."""
    steps = [{"setpoint": 72.0, "duration": 10.0}]
    actions = _collect(steps, last_temp=25.0)
    hold = actions[1]
    assert hold[3] == 72.0


@pytest.mark.unit
def test_single_setpoint_ramp_duration_uses_ramp_rate():
    """Ramp duration = |setpoint - last_temp| / ramp_rate."""
    steps = [{"setpoint": 95.0, "duration": 30.0}]
    actions = _collect(steps, last_temp=25.0, ramp_rate=10.0)
    ramp = actions[0]
    expected_ramp_duration = abs(95.0 - 25.0) / 10.0  # 7.0
    assert abs(ramp[4] - expected_ramp_duration) < 1e-9


@pytest.mark.unit
def test_single_setpoint_last_time_accumulates():
    """last_time after hold = ramp_duration + hold_duration."""
    steps = [{"setpoint": 95.0, "duration": 30.0}]
    actions = _collect(steps, last_temp=25.0, ramp_rate=10.0, last_time=0.0)
    hold = actions[1]
    expected_end = (abs(95.0 - 25.0) / 10.0) + 30.0  # 7.0 + 30.0 = 37.0
    assert abs(hold[5] - expected_end) < 1e-9


# ---------------------------------------------------------------------------
# Repeat block
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_repeat_block_cycles_correct_number_of_times():
    """A repeat block with cycles=3 must emit 3 × (ramp + hold) = 6 actions."""
    steps = [
        {
            "repeat": [{"setpoint": 95.0, "duration": 10.0}],
            "cycles": 3,
        }
    ]
    actions = _collect(steps, last_temp=25.0)
    assert len(actions) == 6  # 3 cycles × (ramp + hold)


@pytest.mark.unit
def test_repeat_block_names_are_ramp_hold_alternating():
    """Each cycle in a repeat block must produce ramp then hold."""
    steps = [
        {
            "repeat": [{"setpoint": 95.0, "duration": 10.0}],
            "cycles": 2,
        }
    ]
    actions = _collect(steps, last_temp=25.0)
    names = [a[0] for a in actions]
    assert names == ["ramp", "hold", "ramp", "hold"]


@pytest.mark.unit
def test_repeat_single_cycle_same_as_direct_step():
    """cycles=1 must produce the same result as the step without repeat."""
    direct_steps = [{"setpoint": 72.0, "duration": 20.0}]
    repeat_steps = [{"repeat": [{"setpoint": 72.0, "duration": 20.0}], "cycles": 1}]

    direct = _collect(direct_steps, last_temp=25.0, ramp_rate=10.0)
    repeated = _collect(repeat_steps, last_temp=25.0, ramp_rate=10.0)

    # Compare names, last_temps, setpoints, durations (ignore cycle index n)
    for d, r in zip(direct, repeated):
        assert d[0] == r[0]   # name
        assert d[2] == r[2]   # last_temp
        assert d[3] == r[3]   # setpoint
        assert d[4] == r[4]   # duration


# ---------------------------------------------------------------------------
# Nested repeat
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_nested_repeat_expands_correctly():
    """Outer 2 cycles × inner 3 cycles × 1 setpoint = 2×3×2 = 12 actions."""
    inner = [{"setpoint": 60.0, "duration": 5.0}]
    steps = [
        {
            "repeat": [
                {"repeat": inner, "cycles": 3}
            ],
            "cycles": 2,
        }
    ]
    actions = _collect(steps, last_temp=25.0)
    assert len(actions) == 12  # 2 outer × 3 inner × (ramp+hold)


# ---------------------------------------------------------------------------
# ramp_rate step
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_ramp_rate_step_emits_call_action():
    """A ramp_rate step must emit a 'call' action to change_ramprate."""
    steps = [{"ramp_rate": 5.0}]
    actions = _collect(steps)
    assert len(actions) == 1
    assert actions[0][0] == "call"
    assert actions[0][1] == "change_ramprate"
    assert actions[0][2] == [5.0]


@pytest.mark.unit
def test_ramp_rate_stored_and_used_in_subsequent_steps():
    """After a ramp_rate step, subsequent setpoints use the new rate."""
    steps = [
        {"ramp_rate": 5.0},
        {"setpoint": 75.0, "duration": 10.0},
    ]
    actions = _collect(steps, last_temp=25.0)
    # First action = call, second = ramp
    ramp = actions[1]
    assert ramp[0] == "ramp"
    expected_duration = abs(75.0 - 25.0) / 5.0  # 10.0
    assert abs(ramp[4] - expected_duration) < 1e-9


# ---------------------------------------------------------------------------
# enable / disable passthrough
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_enable_step_passed_through():
    """enable step emits an 'enable' action with the correct duration."""
    steps = [{"enable": True, "duration": 3.0}]
    actions = _collect(steps)
    assert len(actions) == 1
    assert actions[0][0] == "enable"
    assert actions[0][4] == 3.0


@pytest.mark.unit
def test_disable_step_passed_through():
    """disable step emits a 'disable' action with the correct duration."""
    steps = [{"disable": True, "duration": 7.5}]
    actions = _collect(steps)
    assert len(actions) == 1
    assert actions[0][0] == "disable"
    assert actions[0][4] == 7.5


# ---------------------------------------------------------------------------
# Callback passthrough steps: optics, fanon, fanoff
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_optics_step_yields_optics_action():
    """optics step must yield a tuple whose first element is 'optics'."""
    steps = [
        {"setpoint": 60.0, "duration": 5.0},  # needed so duration is defined
        {"optics": True},
    ]
    actions = _collect(steps, last_temp=25.0)
    optics_actions = [a for a in actions if a[0] == "optics"]
    assert len(optics_actions) == 1


@pytest.mark.unit
def test_pcr_fanon_step_yields_pcr_fanon_action():
    """pcr_fanon step must yield a tuple whose first element is 'pcr_fanon'."""
    steps = [{"pcr_fanon": True}]
    actions = _collect(steps)
    assert len(actions) == 1
    assert actions[0][0] == "pcr_fanon"


@pytest.mark.unit
def test_pcr_fanoff_step_yields_pcr_fanoff_action():
    """pcr_fanoff step must yield a tuple whose first element is 'pcr_fanoff'."""
    steps = [{"pcr_fanoff": True}]
    actions = _collect(steps)
    assert len(actions) == 1
    assert actions[0][0] == "pcr_fanoff"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_empty_steps_produces_no_actions():
    """An empty steps list must produce zero actions."""
    actions = _collect([])
    assert actions == []


@pytest.mark.unit
def test_two_sequential_setpoints_accumulate_time():
    """Time accumulates correctly across two sequential setpoints."""
    steps = [
        {"setpoint": 95.0, "duration": 30.0},
        {"setpoint": 60.0, "duration": 20.0},
    ]
    actions = _collect(steps, last_temp=25.0, ramp_rate=10.0)
    assert len(actions) == 4  # ramp, hold, ramp, hold
    # The final hold's end time should be the total cumulative time
    ramp1_dur = abs(95.0 - 25.0) / 10.0   # 7.0
    hold1_dur = 30.0
    ramp2_dur = abs(60.0 - 95.0) / 10.0   # 3.5
    hold2_dur = 20.0
    expected_final = ramp1_dur + hold1_dur + ramp2_dur + hold2_dur
    assert abs(actions[3][5] - expected_final) < 1e-9

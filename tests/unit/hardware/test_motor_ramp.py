"""Pure-logic tests for the motor acceleration ramp (#517 Slice 5).

motor_class imports pigpio at load, stubbed here. The ramp math
(_ramp_profile, move_time_estimate, _resolve_pulse_delay) is pure; _ramp_pulses
builds pigpio.pulse objects so pigpio.pulse is stubbed to record its period.
The actual wave transmission stays hardware-only.
"""
import sys
import types

import pytest
from unittest.mock import patch


class _FakePulse:
    def __init__(self, on, off, us):
        self.on, self.off, self.us = on, off, us


@pytest.fixture
def motor_module():
    fake_pigpio = types.ModuleType("pigpio")
    fake_pigpio.pulse = _FakePulse
    fake_pigpio.pi = lambda *a, **k: None
    fake_pigpio.OUTPUT = 1
    fake_pigpio.INPUT = 0
    with patch.dict(sys.modules, {"pigpio": fake_pigpio}):
        sys.modules.pop("aq_lib.motor_class", None)
        import aq_lib.motor_class as m
        yield m
    sys.modules.pop("aq_lib.motor_class", None)


def _motor(module, *, ramp_steps=40, ramp_start_delay=0.0002,
           move_pulse_delay=0.0001, step_multiplier=8, step_pin=19):
    mtr = object.__new__(module.Motor)
    mtr.ramp_steps = ramp_steps
    mtr.ramp_start_delay = ramp_start_delay
    mtr.move_pulse_delay = move_pulse_delay
    mtr.step_multiplier = step_multiplier
    mtr.STEP_PIN = step_pin
    return mtr


# --- _resolve_pulse_delay --------------------------------------------------

@pytest.mark.unit
def test_resolve_pulse_delay_uses_default_on_none(motor_module):
    assert _motor(motor_module, move_pulse_delay=0.0003)._resolve_pulse_delay(None) == 0.0003


@pytest.mark.unit
def test_resolve_pulse_delay_passthrough(motor_module):
    assert _motor(motor_module)._resolve_pulse_delay(0.00007) == 0.00007


# --- _ramp_profile : step-count invariant ----------------------------------

@pytest.mark.unit
def test_profile_conserves_total_steps(motor_module):
    m = _motor(motor_module, ramp_steps=40, ramp_start_delay=0.0002)
    for total in (16, 80, 320, 2420):
        n_ramp, cruise = m._ramp_profile(total, 0.0001)
        assert 2 * n_ramp + cruise == total
        assert cruise >= 0


@pytest.mark.unit
def test_profile_triangular_for_short_move(motor_module):
    """A move shorter than 2*ramp_steps has no cruise (all ramp)."""
    m = _motor(motor_module, ramp_steps=40)
    n_ramp, cruise = m._ramp_profile(50, 0.0001)  # 50 < 80
    assert n_ramp == 25
    assert cruise == 0


@pytest.mark.unit
def test_profile_disabled_when_ramp_steps_zero(motor_module):
    m = _motor(motor_module, ramp_steps=0)
    assert m._ramp_profile(320, 0.0001) == (0, 320)


@pytest.mark.unit
def test_profile_disabled_when_cruise_not_faster_than_start(motor_module):
    """No ramp possible if cruise period >= ramp_start_delay."""
    m = _motor(motor_module, ramp_start_delay=0.0002)
    assert m._ramp_profile(320, 0.0002) == (0, 320)   # equal
    assert m._ramp_profile(320, 0.0003) == (0, 320)   # slower cruise


# --- _ramp_pulses : count + monotonic period -------------------------------

@pytest.mark.unit
def test_ramp_pulses_count(motor_module):
    m = _motor(motor_module, step_multiplier=8)
    pulses = m._ramp_pulses(4, 0.0001, accelerating=True)
    assert len(pulses) == 2 * 4 * 8   # 2 pulses per motor-step, step_multiplier each


@pytest.mark.unit
def test_ramp_pulses_accelerate_period_decreases(motor_module):
    m = _motor(motor_module, step_multiplier=1, ramp_start_delay=0.0002)
    periods = [p.us for p in m._ramp_pulses(5, 0.0001, accelerating=True)][::2]
    assert periods == sorted(periods, reverse=True)   # slow -> fast
    assert periods[0] > periods[-1]


@pytest.mark.unit
def test_ramp_pulses_decelerate_is_mirror(motor_module):
    m = _motor(motor_module, step_multiplier=1, ramp_start_delay=0.0002)
    periods = [p.us for p in m._ramp_pulses(5, 0.0001, accelerating=False)][::2]
    assert periods == sorted(periods)   # fast -> slow


# --- move_time_estimate ----------------------------------------------------

@pytest.mark.unit
def test_time_estimate_flat_when_ramp_disabled(motor_module):
    m = _motor(motor_module, ramp_steps=0, step_multiplier=8)
    assert m.move_time_estimate(100, 0.0001) == pytest.approx(100 * 8 * 0.0001)


@pytest.mark.unit
def test_time_estimate_ramped_is_slower_than_flat(motor_module):
    m = _motor(motor_module, ramp_steps=40, ramp_start_delay=0.0002, step_multiplier=8)
    ramped = m.move_time_estimate(320, 0.0001)
    flat = 320 * 8 * 0.0001
    assert ramped > flat   # ramp steps run slower than cruise


@pytest.mark.unit
def test_time_estimate_monotonic_in_distance(motor_module):
    m = _motor(motor_module, ramp_steps=40, step_multiplier=8)
    assert m.move_time_estimate(320, 0.0001) < m.move_time_estimate(640, 0.0001)

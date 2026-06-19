"""
Unit tests for sentri_lib/thermal_engine.py

All tests use DummyMeer from tests/unit/conftest.py — no real hardware required.
"""
import io
from threading import Event, Thread
import time

import pytest

from sentri_lib.thermal_engine import RunStopped, thermal_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_callback(args):
    """Callback that records invocations."""
    pass


def _make_callback():
    """Return a callback that records every invocation."""
    calls = []

    def cb(args):
        calls.append(args)

    cb.calls = calls
    return cb


# ---------------------------------------------------------------------------
# stop_event behaviour
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_stop_event_pre_set_raises_run_stopped(dummy_meer, stop_event, logfile):
    """stop_event already set raises RunStopped before any action executes."""
    stop_event.set()
    actions = [("hold", 1, 25.0, 95.0, 10.0, 10.0)]

    with pytest.raises(RunStopped):
        thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)

    # log() must never have been called
    assert dummy_meer.log_calls == []


@pytest.mark.unit
def test_stop_event_pre_set_no_change_setpoint(dummy_meer, stop_event, logfile):
    """stop_event pre-set: change_setpoint is never called."""
    stop_event.set()
    actions = [("ramp", 1, 25.0, 95.0, 7.0, 7.0)]

    with pytest.raises(RunStopped):
        thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)

    assert dummy_meer.setpoints == []


@pytest.mark.unit
def test_stop_event_mid_run_halts_at_next_iteration(dummy_meer, logfile):
    """stop_event set by DummyMeer.log() halts at the next loop iteration."""
    stop_event = Event()

    # Override log() to set the stop_event on first call, then raise RunStopped
    first_call_done = []

    def log_and_stop(endtime=None, logfile=None, stop_event=None):
        dummy_meer.log_calls.append({"endtime": endtime})
        if not first_call_done:
            first_call_done.append(True)
            stop_event.set()
            raise RunStopped("stopped mid-run")

    dummy_meer.log = log_and_stop

    actions = [
        ("hold", 1, 25.0, 95.0, 10.0, 10.0),
        ("hold", 2, 95.0, 95.0, 30.0, 40.0),
    ]

    with pytest.raises(RunStopped):
        thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)

    # Only the first hold should have triggered log()
    assert len(dummy_meer.log_calls) == 1


# ---------------------------------------------------------------------------
# ramp action
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_ramp_calls_change_setpoint(dummy_meer, stop_event, logfile):
    """ramp action calls change_setpoint with the correct temperature."""
    actions = [("ramp", 1, 25.0, 95.0, 7.0, 7.0)]
    thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)
    assert dummy_meer.setpoints == [95.0]


@pytest.mark.unit
def test_ramp_also_calls_log(dummy_meer, stop_event, logfile):
    """ramp action calls meer.log with the correct endtime."""
    actions = [("ramp", 1, 25.0, 95.0, 7.0, 7.0)]
    thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)
    assert len(dummy_meer.log_calls) == 1
    assert dummy_meer.log_calls[0]["endtime"] == 7.0


# ---------------------------------------------------------------------------
# hold action
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_hold_calls_log_with_correct_endtime(dummy_meer, stop_event, logfile):
    """hold action calls meer.log with the correct endtime."""
    actions = [("hold", 1, 95.0, 95.0, 30.0, 37.0)]
    thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)
    assert dummy_meer.log_calls[0]["endtime"] == 37.0


@pytest.mark.unit
def test_hold_does_not_call_change_setpoint(dummy_meer, stop_event, logfile):
    """hold action must NOT call change_setpoint."""
    actions = [("hold", 1, 95.0, 95.0, 30.0, 37.0)]
    thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)
    assert dummy_meer.setpoints == []


# ---------------------------------------------------------------------------
# enable / disable actions
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_enable_calls_output_stage_enable_1(dummy_meer, stop_event, logfile):
    """enable action calls output_stage_enable(1)."""
    actions = [("enable", 1, 25.0, 25.0, 5.0, 5.0)]
    thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)
    assert dummy_meer.output_stages == [1]


@pytest.mark.unit
def test_disable_calls_output_stage_enable_0(dummy_meer, stop_event, logfile):
    """disable action calls output_stage_enable(0)."""
    actions = [("disable", 1, 25.0, 25.0, 5.0, 5.0)]
    thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)
    assert dummy_meer.output_stages == [0]


# ---------------------------------------------------------------------------
# callback-dispatched actions: pcr_fanon, pcr_fanoff, optics
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pcr_fanon_invokes_callback(dummy_meer, stop_event, logfile):
    """pcr_fanon tuple is forwarded to the callback."""
    cb = _make_callback()
    fan_action = ("pcr_fanon", {"pcr_fanon": True})
    thermal_engine([fan_action], dummy_meer, cb, logfile, stop_event)
    assert len(cb.calls) == 1
    assert cb.calls[0][0] == "pcr_fanon"


@pytest.mark.unit
def test_pcr_fanon_does_not_touch_meer(dummy_meer, stop_event, logfile):
    """pcr_fanon must not call log, change_setpoint, or output_stage_enable."""
    fan_action = ("pcr_fanon", {"pcr_fanon": True})
    thermal_engine([fan_action], dummy_meer, _noop_callback, logfile, stop_event)
    assert dummy_meer.log_calls == []
    assert dummy_meer.setpoints == []
    assert dummy_meer.output_stages == []


@pytest.mark.unit
def test_pcr_fanoff_invokes_callback(dummy_meer, stop_event, logfile):
    """pcr_fanoff tuple is forwarded to the callback."""
    cb = _make_callback()
    fan_action = ("pcr_fanoff", {"pcr_fanoff": True})
    thermal_engine([fan_action], dummy_meer, cb, logfile, stop_event)
    assert len(cb.calls) == 1
    assert cb.calls[0][0] == "pcr_fanoff"


@pytest.mark.unit
def test_pcr_fanoff_does_not_touch_meer(dummy_meer, stop_event, logfile):
    """pcr_fanoff must not call log, change_setpoint, or output_stage_enable."""
    fan_action = ("pcr_fanoff", {"pcr_fanoff": True})
    thermal_engine([fan_action], dummy_meer, _noop_callback, logfile, stop_event)
    assert dummy_meer.log_calls == []
    assert dummy_meer.setpoints == []
    assert dummy_meer.output_stages == []


@pytest.mark.unit
def test_optics_callback_invoked(dummy_meer, stop_event, logfile):
    """optics tuple is forwarded to the callback at the correct step."""
    cb = _make_callback()
    optics_action = ("optics", 3, 60.0, 60.0, 0.0, 15.0)
    thermal_engine([optics_action], dummy_meer, cb, logfile, stop_event)
    assert len(cb.calls) == 1
    assert cb.calls[0][0] == "optics"


@pytest.mark.unit
def test_optics_callback_receives_full_tuple(dummy_meer, stop_event, logfile):
    """The full optics action tuple is passed through to the callback."""
    cb = _make_callback()
    optics_action = ("optics", 3, 60.0, 60.0, 0.0, 15.0)
    thermal_engine([optics_action], dummy_meer, cb, logfile, stop_event)
    assert cb.calls[0] == optics_action


# ---------------------------------------------------------------------------
# multi-action sequence
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_multiple_actions_execute_in_sequence(dummy_meer, stop_event, logfile):
    """ramp + hold sequence: change_setpoint then log twice."""
    actions = [
        ("ramp", 1, 25.0, 95.0, 7.0, 7.0),
        ("hold", 1, 95.0, 95.0, 30.0, 37.0),
    ]
    thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)
    assert dummy_meer.setpoints == [95.0]
    assert len(dummy_meer.log_calls) == 2
    assert dummy_meer.log_calls[0]["endtime"] == 7.0
    assert dummy_meer.log_calls[1]["endtime"] == 37.0


@pytest.mark.unit
def test_mixed_sequence_enable_ramp_hold(dummy_meer, stop_event, logfile):
    """enable → ramp → hold executes all three in order."""
    actions = [
        ("enable", 1, 25.0, 25.0, 1.0, 1.0),
        ("ramp",   1, 25.0, 72.0, 4.7, 5.7),
        ("hold",   1, 72.0, 72.0, 60.0, 65.7),
    ]
    thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)
    assert dummy_meer.output_stages == [1]
    assert dummy_meer.setpoints == [72.0]
    assert len(dummy_meer.log_calls) == 3


# ---------------------------------------------------------------------------
# no stop_event — runs to completion
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_no_stop_event_runs_to_completion(dummy_meer, logfile):
    """With stop_event=None the engine completes without raising."""
    actions = [
        ("ramp", 1, 25.0, 95.0, 7.0, 7.0),
        ("hold", 1, 95.0, 95.0, 30.0, 37.0),
        ("ramp", 1, 95.0, 72.0, 2.3, 39.3),
        ("hold", 1, 72.0, 72.0, 30.0, 69.3),
    ]
    thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event=None)
    assert len(dummy_meer.log_calls) == 4
    assert len(dummy_meer.setpoints) == 2


@pytest.mark.unit
def test_no_stop_event_unset_runs_to_completion(dummy_meer, stop_event, logfile):
    """With a clear (not set) stop_event the engine runs all actions."""
    # stop_event fixture is clear by default
    actions = [
        ("hold", 1, 25.0, 25.0, 5.0, 5.0),
        ("hold", 2, 25.0, 25.0, 5.0, 10.0),
    ]
    thermal_engine(actions, dummy_meer, _noop_callback, logfile, stop_event)
    assert len(dummy_meer.log_calls) == 2

"""
Tests for meer.log() stop_event interruptibility and backward compatibility.
"""
import io
import time
from threading import Event, Thread
from unittest.mock import MagicMock, patch

import pytest

import aq_lib.meerstetter as meer_module
from aq_lib.meerstetter import MeerStetter
from aq_lib.thermal_engine import RunStopped, thermal_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_logfile():
    return io.StringIO()


class _MeerSelf:
    """
    Minimal self-like object for calling MeerStetter.log() as an unbound method.
    Avoids inheriting from Serial so no __del__ / is_open issues in tests.
    """
    def __init__(self):
        self.write = MagicMock()
        self.read = MagicMock(return_value=b"\x00" * 20)
        self.reply_to_float = MagicMock(return_value=1.23)
        self.compile = MagicMock(return_value=b"")

    def log(self, endtime=None, logfile=None, stop_event=None):
        """Delegate to the real MeerStetter.log() with self as the instance."""
        return MeerStetter.log(self, endtime=endtime, logfile=logfile, stop_event=stop_event)


def _make_meer_instance():
    return _MeerSelf()


def _set_t0_now():
    meer_module.t0 = time.time()


# ---------------------------------------------------------------------------
# Stub for thermal_engine tests (duck-typed, not a Serial subclass)
# ---------------------------------------------------------------------------

class RecordingMeer:
    """Records arguments passed to log() — used to verify thermal_engine wiring."""

    def __init__(self):
        self.log_calls = []

    def log(self, endtime=None, logfile=None, stop_event=None):
        self.log_calls.append({"endtime": endtime, "stop_event": stop_event})

    def change_setpoint(self, setpoint):
        pass

    def output_stage_enable(self, value):
        pass


# ---------------------------------------------------------------------------
# meer.log() — behavioral tests
# ---------------------------------------------------------------------------

def test_log_runs_to_completion_no_stop_event():
    """log() with no stop_event runs until endtime and writes output."""
    _set_t0_now()
    meer = _make_meer_instance()
    logfile = _make_logfile()
    endtime = meer_module.get_time() + 0.15
    meer.log(endtime=endtime, logfile=logfile)
    assert logfile.tell() > 0


def test_log_runs_to_completion_stop_event_not_set():
    """log() with an unset stop_event completes normally."""
    _set_t0_now()
    meer = _make_meer_instance()
    logfile = _make_logfile()
    stop_event = Event()
    endtime = meer_module.get_time() + 0.15
    meer.log(endtime=endtime, logfile=logfile, stop_event=stop_event)
    assert logfile.tell() > 0


def test_log_exits_immediately_when_stop_event_pre_set():
    """log() exits before writing anything if stop_event is already set."""
    _set_t0_now()
    meer = _make_meer_instance()
    logfile = _make_logfile()
    stop_event = Event()
    stop_event.set()
    endtime = meer_module.get_time() + 60.0

    start = time.time()
    meer.log(endtime=endtime, logfile=logfile, stop_event=stop_event)
    elapsed = time.time() - start

    assert elapsed < 1.0
    assert logfile.tell() == 0


def test_log_exits_early_when_stop_event_set_from_thread():
    """log() aborts mid-run when stop_event is set by another thread."""
    _set_t0_now()
    meer = _make_meer_instance()
    logfile = _make_logfile()
    stop_event = Event()
    endtime = meer_module.get_time() + 60.0

    def _trigger():
        time.sleep(0.2)
        stop_event.set()

    Thread(target=_trigger, daemon=True).start()

    start = time.time()
    meer.log(endtime=endtime, logfile=logfile, stop_event=stop_event)
    elapsed = time.time() - start

    assert elapsed < 2.0


def test_log_backward_compat_none_stop_event():
    """log() called without stop_event kwarg (legacy callers) still works."""
    _set_t0_now()
    meer = _make_meer_instance()
    logfile = _make_logfile()
    endtime = meer_module.get_time() + 0.15
    meer.log(endtime, logfile)
    assert logfile.tell() > 0


# ---------------------------------------------------------------------------
# thermal_engine — stop_event pass-through tests
# ---------------------------------------------------------------------------

def test_thermal_engine_passes_stop_event_to_log_hold():
    stop_event = Event()
    meer = RecordingMeer()
    thermal_engine(
        [("hold", 1, 25.0, 30.0, 1.0, 1.0)],
        meer, lambda *_: None, None, stop_event,
    )
    assert meer.log_calls[0]["stop_event"] is stop_event


def test_thermal_engine_passes_stop_event_to_log_ramp():
    stop_event = Event()
    meer = RecordingMeer()
    thermal_engine(
        [("ramp", 1, 25.0, 95.0, 10.0, 10.0)],
        meer, lambda *_: None, None, stop_event,
    )
    assert meer.log_calls[0]["stop_event"] is stop_event


def test_thermal_engine_passes_stop_event_to_log_disable():
    stop_event = Event()
    meer = RecordingMeer()
    thermal_engine(
        [("disable", 1, 25.0, 0.0, 5.0, 5.0)],
        meer, lambda *_: None, None, stop_event,
    )
    assert meer.log_calls[0]["stop_event"] is stop_event


def test_thermal_engine_passes_stop_event_to_log_enable():
    stop_event = Event()
    meer = RecordingMeer()
    thermal_engine(
        [("enable", 1, 25.0, 25.0, 5.0, 5.0)],
        meer, lambda *_: None, None, stop_event,
    )
    assert meer.log_calls[0]["stop_event"] is stop_event


def test_thermal_engine_raises_before_log_when_stop_pre_set():
    """
    If stop_event is already set, thermal_engine raises RunStopped at the top
    of the for loop before log() is called.
    """
    stop_event = Event()
    stop_event.set()
    meer = RecordingMeer()
    with pytest.raises(RunStopped):
        thermal_engine(
            [("hold", 1, 25.0, 30.0, 60.0, 60.0)],
            meer, lambda *_: None, None, stop_event,
        )
    assert len(meer.log_calls) == 0

"""
Tests for Meerstetter TEC error-latch recovery and mid-run detection (#519).

Background: the TEC latches an over-current error (dev_Status = 3) and stays
latched until a power cycle. The run software never reset or detected it, so a
second run reused a dead controller and produced a flat, no-heat trace. These
tests exercise the recovery/detection behaviour through the public interface
with a duck-typed fake (mirrors _MeerSelf in test_meer_log_stop.py — no Serial
subclassing, so no __del__/is_open side effects).
"""
import io
from unittest.mock import MagicMock

import pytest

import aq_lib.meerstetter as meer_module
from aq_lib.meerstetter import MeerStetter, TecError


class FakeMeer:
    """Duck-typed MeerStetter: real status/recovery methods, stubbed serial I/O.

    The methods under test are invoked as unbound MeerStetter methods with this
    instance as ``self``; the serial-level primitives they call
    (``get_parid_long``, ``reset``) are MagicMocks the test drives.
    """

    def __init__(self):
        self.get_parid_long = MagicMock()
        self.reset = MagicMock()

    def get_status(self, inst=1):
        return MeerStetter.get_status(self, inst)

    def get_error_number(self, inst=1):
        return MeerStetter.get_error_number(self, inst)

    def is_latched(self, inst=1, reads=2):
        return MeerStetter.is_latched(self, inst, reads)

    def recover(self, **kwargs):
        return MeerStetter.recover(self, **kwargs)


def test_is_latched_true_when_controller_in_error():
    """Two consecutive ERROR status reads => latched."""
    meer = FakeMeer()
    meer.get_parid_long.return_value = MeerStetter.STATUS_ERROR
    assert meer.is_latched() is True


def test_is_latched_false_when_ready():
    meer = FakeMeer()
    meer.get_parid_long.return_value = MeerStetter.STATUS_READY
    assert meer.is_latched() is False


def test_is_latched_debounces_single_transient_error_read():
    """One ERROR read followed by a clean read must NOT register as latched.

    Guards against the controller's serial framing noise producing a false
    abort on a healthy run (#519).
    """
    meer = FakeMeer()
    meer.get_parid_long.side_effect = [MeerStetter.STATUS_ERROR, MeerStetter.STATUS_READY]
    assert meer.is_latched() is False


# ---------------------------------------------------------------------------
# recover(): reset the controller and wait until it returns to Ready
# ---------------------------------------------------------------------------

def test_recover_resets_and_returns_when_ready():
    meer = FakeMeer()
    meer.get_parid_long.return_value = MeerStetter.STATUS_READY
    meer.recover(timeout=1.0, poll=0.01)
    meer.reset.assert_called_once()


def test_recover_raises_tecerror_if_never_ready():
    """Controller stuck in Error after reset => TecError within the timeout."""
    meer = FakeMeer()
    meer.get_parid_long.return_value = MeerStetter.STATUS_ERROR
    with pytest.raises(TecError):
        meer.recover(timeout=0.05, poll=0.01)


# ---------------------------------------------------------------------------
# log(): detect a mid-run latch (opt-in via check_latch) and raise TecError
# ---------------------------------------------------------------------------

class LoggingMeer:
    """Duck-typed stub for exercising MeerStetter.log() (cf. _MeerSelf)."""

    def __init__(self, latched=False):
        self.write = MagicMock()
        self.read = MagicMock(return_value=b"\x00" * 20)
        self.reply_to_float = MagicMock(return_value=1.0)
        self.compile = MagicMock(return_value=b"")
        self.is_latched = MagicMock(return_value=latched)
        self.get_error_number = MagicMock(return_value=30)
        self.get_error_param = MagicMock(return_value=9941)

    def log(self, **kwargs):
        return MeerStetter.log(self, **kwargs)


def test_log_raises_tecerror_when_latched_midrun():
    meer_module.set_time()
    meer = LoggingMeer(latched=True)
    endtime = meer_module.get_time() + 60.0
    with pytest.raises(TecError):
        meer.log(endtime=endtime, logfile=io.StringIO(), check_latch=True)


def test_log_does_not_check_latch_by_default():
    """Legacy callers (no check_latch) must never consult is_latched (#519)."""
    meer_module.set_time()
    meer = LoggingMeer(latched=True)
    endtime = meer_module.get_time() + 0.15
    meer.log(endtime=endtime, logfile=io.StringIO())
    meer.is_latched.assert_not_called()


# ---------------------------------------------------------------------------
# thermal_engine wires mid-run latch detection into every log() call
# ---------------------------------------------------------------------------

class _CheckLatchRecorder:
    def __init__(self):
        self.check_latch_flags = []

    def log(self, endtime=None, logfile=None, stop_event=None, check_latch=False):
        self.check_latch_flags.append(check_latch)

    def change_setpoint(self, setpoint):
        pass

    def output_stage_enable(self, value):
        pass


def test_thermal_engine_enables_latch_check_on_log():
    from threading import Event

    from aq_lib.thermal_engine import thermal_engine

    meer = _CheckLatchRecorder()
    thermal_engine(
        [("ramp", 1, 25.0, 95.0, 10.0, 10.0)],
        meer, lambda *_: None, None, Event(),
    )
    assert meer.check_latch_flags == [True]

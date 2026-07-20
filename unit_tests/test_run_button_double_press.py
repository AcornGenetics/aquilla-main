"""
Regression test for issue #333: the Run button had to be pressed twice to start
a new run after a completed run.

The bug lived in ``application.main()``'s ``ready -> run -> end`` loop. When the
operator pressed Run on the results screen, ``end()`` captured the selected
profile but the caller discarded it and unconditionally looped back to
``ready()`` -- which then waited for a *second* press. The fix makes ``end()``
return ``True`` when it arms a run from the results screen, and the loop skips
``ready()`` in that case so the single press actually starts the run.

These tests drive the REAL ``application.main()`` loop with a fake
``AssayInterface``, so no Pi hardware is required. The full on-device behaviour
(results screen "3" -> running screen "2" on a single tap, reusing the last
profile) is a hardware-path check -- see the ``@pytest.mark.hardware`` note at
the bottom of this module.

``end()``'s own arm-decision (``profile is not None`` -> set run_name /
thermal_profile -> return True) cannot be unit-imported on a dev machine because
``state_run_assay`` runs GPIO/I2C calls at import time; it is exercised on
hardware and asserted here at the loop contract level (True -> skip ready).
"""
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# application.py imports AssayInterface (state_run_assay) and sr
# (aq_lib.state_requests) at module load, both of which pull in the Pi hardware
# stack, and it calls logging.config.dictConfig(APP_LOGGING_CONFIG) at import.
# Replace those collaborators with lightweight stubs BEFORE importing
# application so the pure loop logic can run on a dev machine / CI. This mirrors
# the RPi/serial stubbing used by the other unit-test modules.
_aq_pkg = types.ModuleType("aq_lib")
_aq_pkg.__path__ = []
sys.modules.setdefault("aq_lib", _aq_pkg)

_sra = types.ModuleType("state_run_assay")
_sra.AssayInterface = object  # replaced per-test via monkeypatch
sys.modules["state_run_assay"] = _sra

_cfg = types.ModuleType("aq_lib.config_module")
_cfg.Config = object
sys.modules["aq_lib.config_module"] = _cfg

_utils = types.ModuleType("aq_lib.utils")
_utils.APP_LOGGING_CONFIG = {"version": 1}
sys.modules["aq_lib.utils"] = _utils

_srq = types.ModuleType("aq_lib.state_requests")
_srq.change_screen = lambda *a, **k: None
sys.modules["aq_lib.state_requests"] = _srq

import application  # noqa: E402  (import after stubs are installed)


class _StopLoop(Exception):
    """Sentinel to break application.main()'s ``while True`` loop.

    main() wraps the loop in ``except Exception``, so raising this from a fake
    call unwinds the loop and returns cleanly -- the test then asserts on the
    recorded call order.
    """


class FakeAssayInterface:
    """Records ready/run/end call order and replays scripted end() returns.

    ``end_script`` is the sequence of values ``end()`` returns (mimicking "Run
    pressed on results screen with a profile" -> True, anything else -> False).
    The loop is stopped the ``stop_on_ready_call``-th time ``ready()`` is
    invoked, giving each test a deterministic, finite call trace.
    """

    def __init__(self, end_script, stop_on_ready_call):
        self.calls = []
        self._end_script = list(end_script)
        self._ready_calls = 0
        self._stop_on_ready_call = stop_on_ready_call

    def ready(self):
        self._ready_calls += 1
        self.calls.append("ready")
        if self._ready_calls >= self._stop_on_ready_call:
            raise _StopLoop

    def run(self):
        self.calls.append("run")

    def end(self):
        self.calls.append("end")
        return self._end_script.pop(0) if self._end_script else False


def _drive_main(monkeypatch, fake):
    monkeypatch.setattr(application, "AssayInterface", lambda: fake)
    application.main()  # loop unwinds when the fake raises _StopLoop
    return fake.calls


def test_run_armed_from_results_screen_skips_ready(monkeypatch):
    """A run armed by end() (Run pressed on results screen) starts on ONE press.

    end() returns True after the first completed run, so the loop must go
    straight to run() without a ready() in between. This is the regression the
    fix targets: before the fix the loop always re-entered ready() here, which
    is what forced the second press.
    """
    fake = FakeAssayInterface(end_script=[True, False], stop_on_ready_call=2)
    calls = _drive_main(monkeypatch, fake)

    # ready, run, end(->True), [NO ready], run, end(->False), ready(stop)
    assert calls == ["ready", "run", "end", "run", "end", "ready"]
    # The load-bearing assertion: no ready() was inserted after the armed end().
    assert calls[2:4] == ["end", "run"]


def test_end_not_arming_falls_back_to_ready(monkeypatch):
    """When end() returns False (abort / no profile), the loop re-enters ready().

    This is the correct behaviour for a completed run the operator did NOT
    immediately re-launch, and for the aborted-run path where end() returns
    False early.
    """
    fake = FakeAssayInterface(end_script=[False], stop_on_ready_call=2)
    calls = _drive_main(monkeypatch, fake)

    # ready, run, end(->False), ready(stop) -- a fresh press is awaited in ready.
    assert calls == ["ready", "run", "end", "ready"]


# NOTE (@pytest.mark.hardware): the end-to-end single-press behaviour on the
# device -- pressing Run on results screen "3" transitions directly to running
# screen "2" and reuses the last-selected profile -- exercises state_run_assay's
# real GPIO/motor/state-request stack and cannot run in CI. Validate on the Pi:
# complete a run, press Run once, confirm it starts without a second press.

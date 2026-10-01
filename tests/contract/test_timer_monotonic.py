"""
Anti-regression contract tests for issue #512.

The run countdown timer must be measured against a monotonic clock, so a mid-run
wall-clock step (NTP correcting the no-RTC Pi after boot) cannot drive the
countdown to 0:00. These drive the /timer + /ws elapsed value through a simulated
~95-minute wall-clock jump and assert elapsed reflects real (monotonic) time.

FastAPI TestClient only, no hardware. Marked ``contract``.
"""
import datetime as _dt

import pytest

from aq_lib.run_clock import MonotonicStopwatch

pytestmark = pytest.mark.contract


class _FakeMono:
    """Controllable stand-in for time.monotonic()."""

    def __init__(self, t=1000.0):
        self.t = float(t)

    def __call__(self):
        return self.t


class _FakeDateTime:
    """Stand-in for datetime whose now() is controllable (the wall clock)."""

    _val = _dt.datetime(2020, 1, 1, 0, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls._val


def test_ws_elapsed_ignores_forward_wall_clock_jump(client, monkeypatch):
    import aquila_web.main as main

    mono = _FakeMono(1000.0)
    monkeypatch.setattr(main, "run_stopwatch", MonotonicStopwatch(clock=mono), raising=False)
    _FakeDateTime._val = _dt.datetime(2020, 1, 1, 0, 0, 0)
    monkeypatch.setattr(main, "datetime", _FakeDateTime)

    client.post("/timer", json={"action": "start"})  # stopwatch starts at mono=1000

    # Only 5 real seconds pass, but NTP steps the wall clock forward ~95 min.
    mono.t += 5
    _FakeDateTime._val = _dt.datetime(2020, 1, 1, 1, 35, 0)  # +5700 s

    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()

    assert data["elapsed"] == 5  # monotonic truth, not the 5700 s wall jump


def test_ws_elapsed_ignores_backward_wall_clock_jump(client, monkeypatch):
    import aquila_web.main as main

    mono = _FakeMono(1000.0)
    monkeypatch.setattr(main, "run_stopwatch", MonotonicStopwatch(clock=mono), raising=False)
    _FakeDateTime._val = _dt.datetime(2020, 1, 1, 2, 0, 0)
    monkeypatch.setattr(main, "datetime", _FakeDateTime)

    client.post("/timer", json={"action": "start"})  # stopwatch starts at mono=1000

    # 5 real seconds pass, but the wall clock is stepped BACKWARD ~95 min.
    mono.t += 5
    _FakeDateTime._val = _dt.datetime(2020, 1, 1, 0, 25, 0)  # -5700 s

    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()

    # Must stay +5 (monotonic), never a negative/garbage elapsed from the step.
    assert data["elapsed"] == 5

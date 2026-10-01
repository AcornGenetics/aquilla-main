"""
Unit tests for aq_lib.run_clock.MonotonicStopwatch.

Pure logic, no hardware or network. Marked ``unit``.

These tests pin the behavior that fixes issue #512: run-critical timing must be
measured against a monotonic clock, so a mid-run wall-clock step (e.g. NTP
correcting a no-RTC Pi after boot) cannot distort run durations.

The stopwatch takes an injectable ``clock`` so a fake monotonic clock can be
driven deterministically; the "wall clock" is irrelevant to it by design.
"""
import pytest

from aq_lib.run_clock import MonotonicStopwatch

pytestmark = pytest.mark.unit


class FakeClock:
    """A controllable stand-in for time.monotonic()."""

    def __init__(self, now=0.0):
        self._now = float(now)

    def __call__(self):
        return self._now

    def advance(self, seconds):
        self._now += seconds


def test_elapsed_tracks_injected_clock():
    clock = FakeClock(now=100.0)
    sw = MonotonicStopwatch(clock=clock)

    sw.start()
    clock.advance(30.0)

    assert sw.elapsed() == pytest.approx(30.0)


def test_reset_stops_running_and_zeroes_elapsed():
    clock = FakeClock(now=100.0)
    sw = MonotonicStopwatch(clock=clock)

    sw.start()
    clock.advance(30.0)
    assert sw.running is True

    sw.reset()
    assert sw.running is False

    # Elapsed stays 0 even as the clock keeps advancing after a reset.
    clock.advance(42.0)
    assert sw.elapsed() == pytest.approx(0.0)

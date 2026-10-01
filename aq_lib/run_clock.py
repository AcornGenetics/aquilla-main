"""Monotonic run timing (issue #512).

Run-critical timing on the Sentri must never depend on the wall clock. The Pi
has no RTC, so after boot ``systemd-timesyncd`` steps the system clock to the
correct time (often a large forward jump) once DNS/NTP is reachable. If a run's
elapsed/pacing is measured with ``datetime.now()`` / ``time.time()``, that step
corrupts the run: the countdown jumps to 0:00, the amplification-curve time axis
gets a discontinuity, and capture pacing can stall.

``MonotonicStopwatch`` measures elapsed time against ``time.monotonic()`` (a
clock that never jumps). The ``clock`` is injectable so tests can drive it
deterministically. This mirrors the existing precedent in ``meerstetter.py``
(wall clock kept only for log correlation; monotonic drives step timing).
"""
import time


class MonotonicStopwatch:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._start = None

    def start(self):
        self._start = self._clock()

    def elapsed(self):
        if self._start is None:
            return 0.0
        return self._clock() - self._start

    def reset(self):
        self._start = None

    @property
    def running(self):
        return self._start is not None

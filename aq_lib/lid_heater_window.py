"""Lid Heater Sample Windows (issue #452, ADR-022).

The lid-heater worker reads its sensor about once a second for the whole of a
Run. Shipping every reading would be unqueryable, so the device summarises a
**Sample Window** into one **Lid Heater Sample**.

A Run's windows are deliberately not all the same length. The first is the
**Climb Window**, covering the rise from cold and ending the moment the lid
first reaches its cutoff; **Settled Windows** follow at a fixed length. A
uniform window would make the first Sample of every Run half climb and half
settled, and its mean voltage a number that means nothing.

Pure logic, no hardware imports: elapsed time is supplied by the caller, so this
is importable and exactly testable on any machine.
"""
import uuid
from datetime import datetime, timezone

SETTLED_WINDOW_SECONDS = 300.0

#: A read past this is what lets the teardown join time out, leaving a worker
#: abandoned for the next Run to revive -- the known lid-thread leak (#157).
#: It lives here rather than centrally because it *is* the join timeout, which
#: is device code regardless.
SLOW_READ_SECONDS = 5.0

#: The worker loop reads once per pass of a ~1 s duty cycle (0.9 s on + 0.1 s
#: off, plus the read itself), so one reading per whole second of window.
READ_PERIOD_SECONDS = 1.0

#: Checkpoints are offsets *below* this machine's cutoff, not fixed voltages.
#: The end of the climb is the comparable part: where a climb starts is an
#: accident of ambient temperature or leftover warmth from a previous Run,
#: whereas the last stretch up to cutoff is the same journey every time, and is
#: where a weakening element shows first (ADR-022).
CHECKPOINT_OFFSETS = (0.06, 0.04, 0.02, 0.0)


def derive_checkpoints(cutoff_voltage: float, floor_voltage: float) -> list:
    """The checkpoint ladder for a machine as (threshold_voltage, key) pairs, low
    to high.

    The key is the checkpoint's offset below cutoff in whole millivolts ("60",
    "40", "20", "0"), NOT the formatted voltage. A voltage key would have the
    device and the Warehouse each format a float to a 2-decimal string, and
    Python's ``%.2f`` and Postgres' ``to_char(..., 'FM0.00')`` round half-cent
    cutoffs (0.345, 0.305, ...) in opposite directions -- silently dropping the
    crossing and reporting a healthy climb as "never reached cutoff". An integer
    millivolt offset is exact on both sides, and "0" is always the at-cutoff
    crossing regardless of the machine's cutoff.

    Any checkpoint at or below the floor is dropped rather than clamped -- below
    the floor the reading means "broken sensor", not "cold lid".
    """
    ladder = [(round(cutoff_voltage - offset, 4), _key(offset))
              for offset in CHECKPOINT_OFFSETS]
    return [(threshold, key) for (threshold, key) in ladder if threshold > floor_voltage]


class LidSampler:
    """Accumulates readings and yields a Sample whenever a window closes."""

    def __init__(self, cutoff_voltage: float, floor_voltage: float,
                 target_voltage: float, run_timestamp: str, now_utc=None):
        self._cutoff = float(cutoff_voltage)
        self._floor = float(floor_voltage)
        # Where a healthy lid on *this* machine parks. The heater cycles around
        # the cutoff rather than resting on it, so the honest health question is
        # how far the window's mean sits from this target -- and the target is
        # configured per machine, so it travels with every Sample.
        self._target = float(target_voltage)
        self._run_timestamp = run_timestamp
        self._now_utc = now_utc or _utc_now
        self._window_ts = self._now_utc()
        self._window_start = 0.0
        self._climbing = True
        self._warm_start = None
        self._readings_in_window = 0
        self._voltage_sum = 0.0
        self._min_voltage = None
        self._max_voltage = None
        self._at_cutoff = 0
        self._active = 0
        self._quiet = 0
        self._slowest_read = 0.0
        self._slow_reads = 0
        self._retries = 0
        self._live_workers = 0
        self._last_voltage = None
        self._last_elapsed = None
        self._last_quiet = False
        self._checkpoints = derive_checkpoints(self._cutoff, self._floor)
        self._crossings = {}

    def record(self, voltage: float, *, elapsed: float, quiet: bool = False,
               read_seconds: float = 0.0, retries: int = 0,
               live_workers: int = 1):
        """Accept one reading; return a Sample if it closed a window."""
        if self._climbing:
            for threshold, key in self._checkpoints:
                if voltage >= threshold and key not in self._crossings:
                    self._crossings[key] = elapsed

        self._readings_in_window += 1
        if self._min_voltage is None or voltage < self._min_voltage:
            self._min_voltage = voltage
        if self._max_voltage is None or voltage > self._max_voltage:
            self._max_voltage = voltage
        if quiet:
            self._quiet += 1
        else:
            # Health is only a question about the stretches the heater was meant
            # to be working: while Quiet it is off on purpose and the lid is
            # allowed to cool, so counting those readings would mark a busy
            # machine unhealthy for behaving correctly. min/max above are the
            # exception -- they see every reading, because a frozen or
            # below-floor sensor is broken whether the heater was on or not.
            self._active += 1
            self._voltage_sum += voltage
            if voltage >= self._cutoff:
                self._at_cutoff += 1
        if read_seconds > self._slowest_read:
            self._slowest_read = read_seconds
        if read_seconds > SLOW_READ_SECONDS:
            self._slow_reads += 1
        self._retries += retries
        # The worst seen, not the last: a leak climbs and never heals, so a
        # last-value reading could miss one that appeared mid-window.
        if live_workers > self._live_workers:
            self._live_workers = live_workers
        self._last_voltage = voltage
        self._last_elapsed = elapsed
        self._last_quiet = quiet

        # A Run that opens already at temperature never climbed, so there is
        # nothing to time: it has no Climb Window at all.
        if self._warm_start is None:
            self._warm_start = voltage >= self._cutoff
            if self._warm_start:
                self._climbing = False
                # A warm start never climbed: discard the crossings the loop above
                # recorded from this first reading before we knew the lid opened at
                # temperature, so its (Settled) window never carries a fabricated
                # instant climb. The climb view reads only Climb Windows today, but
                # the invariant "crossings describe the climb" must hold at source.
                self._crossings = {}

        reached_cutoff = self._climbing and voltage >= self._cutoff
        capped = elapsed - self._window_start >= SETTLED_WINDOW_SECONDS
        if reached_cutoff or capped:
            kind = "climb" if self._climbing else "settled"
            self._climbing = False
            return self._close(elapsed, kind)
        return None

    def close(self, elapsed: float):
        """Flush the open window at the end of a Run.

        Called from the worker's ``finally`` block, so it runs even when the
        worker dies mid-Run -- that Sample is the only record that the lid
        stopped being heated at all.
        """
        if self._readings_in_window == 0:
            return None
        return self._close(elapsed, "climb" if self._climbing else "settled")

    def _close(self, elapsed: float, kind: str) -> dict:
        window_seconds = elapsed - self._window_start
        readings = self._readings_in_window
        sample = {
            "sample_id": uuid.uuid4().hex,
            "device_ts": self._window_ts,
            "run_timestamp": self._run_timestamp,
            "window_kind": kind,
            "window_seconds": window_seconds,
            "mean_voltage": (self._voltage_sum / self._active) if self._active else None,
            "min_voltage": self._min_voltage,
            "max_voltage": self._max_voltage,
            # Shares of readings, not of clock time: the worker reads at roughly
            # 1 Hz, so the two agree, and a share of readings degrades honestly
            # when reads are missed rather than silently assuming they happened.
            # None when every reading was Quiet: that window cannot answer the
            # hold question. It is still emitted -- dropping it would forge the
            # "missing Samples mean a stalled controller" signal, and its leak
            # and read-health counters still matter.
            "at_cutoff_fraction": (self._at_cutoff / self._active) if self._active else None,
            "quiet_fraction": self._quiet / readings,
            "checkpoint_crossings": dict(self._crossings),
            "live_worker_count": self._live_workers,
            "slowest_read_seconds": self._slowest_read,
            "slow_read_count": self._slow_reads,
            "read_retry_count": self._retries,
            "reading_count": readings,
            # Whole loop periods, not a rounded duration: a window closes ON a
            # reading, so its length overshoots the last read by part of a
            # period. Rounding up made a healthy sn03 report 300 readings
            # against 301 expected on every single window. A shortfall of one
            # is still normal at a window boundary -- anything reading this
            # should allow a reading or two of slack before calling it a stall.
            "expected_reading_count": int(window_seconds // READ_PERIOD_SECONDS),
            "last_voltage": self._last_voltage,
            "last_reading_age_seconds": elapsed - self._last_elapsed,
            "heater_state": self._heater_state(),
            "cutoff_voltage": self._cutoff,
            "floor_voltage": self._floor,
            "target_voltage": self._target,
        }
        self._window_start = elapsed
        self._window_ts = self._now_utc()
        self._reset_window()
        return sample

    def _heater_state(self) -> str:
        """Why the heater is doing what it is doing, which the voltage alone
        cannot say. Quiet wins: the heater is held off regardless of voltage
        while the machine moves or images. Below the floor the worker
        deliberately refuses to drive -- a broken sensor, not a cold lid."""
        if self._last_quiet:
            return "quiet"
        if self._last_voltage <= self._floor:
            return "not_heating"
        if self._last_voltage >= self._cutoff:
            return "holding"
        return "heating"

    def _reset_window(self) -> None:
        # Crossings describe the climb, once per Run: a Settled Window must not
        # carry a stale copy of them (seen on sn03, 2026-08-21).
        self._crossings = {}
        self._readings_in_window = 0
        self._voltage_sum = 0.0
        self._min_voltage = None
        self._max_voltage = None
        self._at_cutoff = 0
        self._active = 0
        self._quiet = 0
        self._slowest_read = 0.0
        self._slow_reads = 0
        self._retries = 0
        self._live_workers = 0
        self._last_voltage = None
        self._last_elapsed = None
        self._last_quiet = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _key(offset: float) -> str:
    """A crossing's key is its offset below cutoff in whole millivolts ("0" is at
    cutoff). An integer is exact on both the device and in the Warehouse's JSONB
    lookup, unlike a formatted voltage whose half-cent rounding can differ
    between Python's %.2f and Postgres' to_char."""
    return str(int(round(offset * 1000)))

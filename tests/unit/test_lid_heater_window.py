"""
Unit tests for lid-heater Sample Windows (issue #452, ADR-022).

A Lid Heater Sample summarises one Sample Window of the lid-heater worker's
behaviour. A Run produces one Climb Window -- the rise from cold, ending when
the lid first reaches its cutoff -- followed by fixed-length Settled Windows.
Pure logic: elapsed time is passed in, so nothing here sleeps or touches
hardware.
"""
import pytest

from aq_lib.lid_heater_window import LidSampler

pytestmark = pytest.mark.unit

RUN_TS = "2026-08-20T09:00:00Z"


def sampler(cutoff=0.34, floor=0.20):
    return LidSampler(cutoff_voltage=cutoff, floor_voltage=floor, run_timestamp=RUN_TS)


class TestClimbWindow:
    def test_closes_when_the_lid_first_reaches_cutoff(self):
        """The Climb Window ends on arrival at temperature, not on the clock."""
        s = sampler()

        assert s.record(0.30, elapsed=100.0) is None

        sample = s.record(0.34, elapsed=172.0)
        assert sample is not None
        assert sample["window_seconds"] == pytest.approx(172.0)

    def test_carries_the_time_each_checkpoint_was_first_reached(self):
        """The ladder is derived from this machine's cutoff: the last 0.06 V,
        sampled every 0.02 V. Crossings are firsts -- a lid that wobbles back
        down and up again does not overwrite an earlier crossing."""
        s = sampler(cutoff=0.34)

        s.record(0.26, elapsed=20.0)
        s.record(0.28, elapsed=41.2)
        s.record(0.27, elapsed=50.0)   # dips back
        s.record(0.28, elapsed=55.0)   # re-crosses; must not overwrite 41.2
        s.record(0.30, elapsed=58.9)
        s.record(0.32, elapsed=96.4)
        sample = s.record(0.34, elapsed=172.0)

        assert sample["checkpoint_crossings"] == {
            "0.28": pytest.approx(41.2),
            "0.30": pytest.approx(58.9),
            "0.32": pytest.approx(96.4),
            "0.34": pytest.approx(172.0),
        }

    def test_closes_at_the_window_cap_when_cutoff_is_never_reached(self):
        """A lid that never gets there still reports -- otherwise the sickest
        machines would be the quietest."""
        s = sampler(cutoff=0.34)

        s.record(0.29, elapsed=100.0)
        assert s.record(0.29, elapsed=299.0) is None

        sample = s.record(0.29, elapsed=300.4)
        assert sample is not None
        assert sample["window_seconds"] == pytest.approx(300.4)
        assert sample["checkpoint_crossings"] == {"0.28": pytest.approx(100.0)}

    def test_a_lid_already_at_temperature_produces_no_climb_window(self):
        """A back-to-back Run on a warm machine never climbs, so there is
        nothing to time; its first window is Settled, not a zero-length Climb."""
        s = sampler(cutoff=0.34)

        assert s.record(0.35, elapsed=1.0) is None

        sample = s.record(0.35, elapsed=301.0)
        assert sample["window_kind"] == "settled"

    def test_a_climb_that_crosses_nothing_is_still_marked_a_climb(self):
        """Lid Hold is drawn from Settled Windows only, so the kinds must be
        distinguishable even when a lid is too cold to cross any checkpoint."""
        s = sampler(cutoff=0.34)

        sample = s.record(0.21, elapsed=300.0)
        assert sample["window_kind"] == "climb"
        assert sample["checkpoint_crossings"] == {}


class TestClosing:
    def test_close_flushes_the_partial_window_with_its_true_length(self):
        """A Run ends when it ends, not on a window boundary -- and the last
        window is the one that says whether the lid held to the finish."""
        s = sampler(cutoff=0.34)
        s.record(0.22, elapsed=1.0)            # cold: this Run really climbs
        s.record(0.34, elapsed=170.0)          # closes the Climb Window
        s.record(0.33, elapsed=400.0)

        sample = s.close(elapsed=410.0)
        assert sample["window_kind"] == "settled"
        assert sample["window_seconds"] == pytest.approx(240.0)

    def test_close_emits_nothing_when_the_window_saw_no_readings(self):
        """A stalled controller must show up as missing Samples, never as a
        fabricated healthy-looking one."""
        s = sampler(cutoff=0.34)
        assert s.close(elapsed=12.0) is None


class TestDerivedLadder:
    def test_checkpoints_below_the_floor_are_dropped_not_clamped(self):
        """Below the floor a reading means "broken sensor", not "cold lid", so
        a checkpoint down there would time a meaningless journey."""
        s = sampler(cutoff=0.24, floor=0.20)

        s.record(0.19, elapsed=5.0)
        s.record(0.21, elapsed=10.0)
        s.record(0.22, elapsed=20.0)
        sample = s.record(0.24, elapsed=30.0)

        assert sample["checkpoint_crossings"] == {
            "0.22": pytest.approx(20.0),
            "0.24": pytest.approx(30.0),
        }


class TestWindowFigures:
    def test_reports_level_spread_and_the_shares(self):
        """min/max are shipped rather than a spread or below-floor/frozen
        booleans, so the Warehouse derives those and their cutoffs stay in SQL
        (ADR-022). Shares are shares of readings -- the loop reads at ~1 Hz."""
        s = sampler(cutoff=0.34)
        s.record(0.35, elapsed=1.0)                     # warm start: Settled from the off
        s.record(0.30, elapsed=2.0)
        s.record(0.36, elapsed=3.0, quiet=True)
        s.record(0.31, elapsed=4.0, quiet=True)

        sample = s.close(elapsed=5.0)
        assert sample["min_voltage"] == pytest.approx(0.30)
        assert sample["max_voltage"] == pytest.approx(0.36)
        assert sample["mean_voltage"] == pytest.approx(0.33)
        assert sample["at_cutoff_fraction"] == pytest.approx(0.5)
        assert sample["quiet_fraction"] == pytest.approx(0.5)

    def test_reports_the_counters_that_say_whether_to_believe_the_rest(self):
        """A read past 5 s is what lets the teardown join time out and leak a
        worker, so it is counted separately from merely slow reads."""
        s = sampler(cutoff=0.34)
        s.record(0.35, elapsed=1.0, read_seconds=0.2, live_workers=1)
        s.record(0.35, elapsed=2.0, read_seconds=6.1, retries=3, live_workers=2)
        s.record(0.35, elapsed=3.0, read_seconds=0.3, live_workers=1)

        sample = s.close(elapsed=11.0)
        assert sample["slowest_read_seconds"] == pytest.approx(6.1)
        assert sample["slow_read_count"] == 1
        assert sample["read_retry_count"] == 3
        assert sample["reading_count"] == 3
        assert sample["expected_reading_count"] == 11

    def test_a_leak_seen_at_any_point_in_the_window_is_the_one_reported(self):
        """The count climbs and does not heal, so the worst seen is the truth;
        a last-value reading could miss it entirely."""
        s = sampler(cutoff=0.34)
        s.record(0.35, elapsed=1.0, live_workers=1)
        s.record(0.35, elapsed=2.0, live_workers=3)
        s.record(0.35, elapsed=3.0, live_workers=1)

        assert s.close(elapsed=4.0)["live_worker_count"] == 3


class TestHeaterState:
    @pytest.mark.parametrize("voltage, quiet, expected", [
        (0.30, False, "heating"),      # in band, driven
        (0.35, False, "holding"),      # at temperature, heater off
        (0.30, True, "quiet"),         # held off for motion or imaging
        (0.19, False, "not_heating"),  # below the floor: refused, not cold
    ])
    def test_says_why_the_heater_is_off_which_voltage_alone_cannot(
            self, voltage, quiet, expected):
        s = sampler(cutoff=0.34, floor=0.20)
        s.record(0.35, elapsed=1.0)                     # warm start
        s.record(voltage, elapsed=2.0, quiet=quiet)

        sample = s.close(elapsed=6.0)
        assert sample["heater_state"] == expected
        assert sample["last_voltage"] == pytest.approx(voltage)
        assert sample["last_reading_age_seconds"] == pytest.approx(4.0)


class TestIdentity:
    def test_each_sample_is_identifiable_and_tied_to_its_run(self):
        """sample_id is the dedup key the whole path depends on, and device_ts
        is when the window *opened* -- the Sample describes a stretch that
        started then, not an instant when it was written."""
        # A third stamp because a fresh window opens after every close; the
        # one opened by the final close is never emitted.
        stamps = iter(["2026-08-20T09:00:00Z", "2026-08-20T09:05:00Z",
                       "2026-08-20T09:06:40Z"])
        s = LidSampler(cutoff_voltage=0.34, floor_voltage=0.20,
                       run_timestamp=RUN_TS, now_utc=lambda: next(stamps))

        s.record(0.35, elapsed=1.0)
        first = s.record(0.35, elapsed=301.0)
        s.record(0.35, elapsed=302.0)
        second = s.close(elapsed=400.0)

        assert first["run_timestamp"] == RUN_TS
        assert first["device_ts"] == "2026-08-20T09:00:00Z"
        assert second["device_ts"] == "2026-08-20T09:05:00Z"
        assert first["sample_id"] != second["sample_id"]
        assert len(first["sample_id"]) == 32

"""
Unit tests for lid-heater worker live-count tracking (issue #157).

The live counter is the core diagnostic for the SENTRI self-cancel study: it
makes lid-heater thread accumulation visible (a leak shows live_count climbing
across runs without coming back to zero). No hardware — pure logic.
"""
import pytest

from sentri_lib import lid_worker_metrics as lwm


@pytest.fixture(autouse=True)
def _clean_registry():
    lwm.reset()
    yield
    lwm.reset()


class TestLiveCount:
    def test_enter_registers_one_worker(self):
        live = lwm.enter(1001)
        assert live == 1
        assert lwm.live_count() == 1

    def test_exit_deregisters_worker(self):
        lwm.enter(1001)
        live = lwm.exit(1001)
        assert live == 0
        assert lwm.live_count() == 0

    def test_workers_accumulate_without_exit(self):
        """A lid-thread leak: each run enters a new worker that never exits."""
        for tid in (1001, 1002, 1003, 1004):
            lwm.enter(tid)
        assert lwm.live_count() == 4

    def test_concurrent_enters_are_counted_correctly(self):
        """Many real worker threads entering at once must not lose updates."""
        import threading

        barrier = threading.Barrier(50)

        def worker():
            barrier.wait()
            lwm.enter(threading.get_ident())

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert lwm.live_count() == 50

    def test_exit_of_unknown_tid_never_goes_negative(self):
        """A double-exit or stray exit must not corrupt the count."""
        live = lwm.exit(9999)
        assert live == 0
        assert lwm.live_count() == 0
        lwm.enter(1001)
        lwm.exit(1001)
        assert lwm.exit(1001) == 0  # second exit is a no-op

    def test_live_tids_reflects_registered_workers(self):
        """live_tids lets a leaked START log be matched to a missing EXIT."""
        lwm.enter(1001)
        lwm.enter(1002)
        lwm.exit(1001)
        assert lwm.live_tids() == {1002}

    def test_live_tids_is_a_copy(self):
        """Caller mutating the returned set must not corrupt internal state."""
        lwm.enter(1001)
        tids = lwm.live_tids()
        tids.add(2002)
        assert lwm.live_count() == 1

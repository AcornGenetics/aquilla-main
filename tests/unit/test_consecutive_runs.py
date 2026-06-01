"""
Unit tests for consecutive run behaviour in state_run_assay.

Tests the queue-drain fix: a stale "quit" left in the message queue after an
aborted run must not kill the executor of the next run.

No hardware required — executor logic is exercised through a minimal stub that
shares the same Queue-drain code path as AssayInterface.run().
"""
import time
from queue import Empty, Queue
from threading import Event, Thread

import pytest


# ---------------------------------------------------------------------------
# Minimal executor stub (mirrors AssayInterface.executor exactly)
# ---------------------------------------------------------------------------

class _StubExecutor:
    """Runs the same executor loop as AssayInterface without any hardware."""

    def __init__(self, queue: Queue):
        self.message_queue = queue
        self.lid_heater_quiet_event = Event()
        self.tasks_processed: list = []

    def executor(self):
        while True:
            try:
                item = self.message_queue.get(timeout=0.1)
                if type(item) is str and item == "quit":
                    break
                self.tasks_processed.append(item)
                self.message_queue.task_done()
            except Empty:
                pass


def _drain_queue(q: Queue):
    """Exact copy of the drain logic added to AssayInterface.run()."""
    while not q.empty():
        try:
            q.get_nowait()
        except Empty:
            break


def _run_executor(queue: Queue, stop_after: float = 1.0):
    """Start an executor thread, return it and the stub."""
    stub = _StubExecutor(queue)
    t = Thread(target=stub.executor, daemon=True)
    t.start()
    return t, stub


# ===========================================================================
# queue drain tests
# ===========================================================================

class TestQueueDrain:
    def test_drain_removes_stale_tasks(self):
        q = Queue()
        for item in [{"capture": "rox"}, {"goto_position": 0}, "quit"]:
            q.put(item)
        _drain_queue(q)
        assert q.empty()

    def test_drain_on_empty_queue_is_safe(self):
        q = Queue()
        _drain_queue(q)  # must not raise
        assert q.empty()

    def test_drain_removes_quit_only(self):
        q = Queue()
        q.put("quit")
        _drain_queue(q)
        assert q.empty()

    def test_fresh_tasks_added_after_drain_are_kept(self):
        q = Queue()
        q.put("quit")
        _drain_queue(q)
        q.put({"capture": "fam"})
        assert q.get_nowait() == {"capture": "fam"}


# ===========================================================================
# executor behaviour tests
# ===========================================================================

class TestExecutorConsecutiveRuns:
    def test_stale_quit_stops_executor_without_drain(self):
        """Demonstrate the bug: stale quit kills the next executor immediately."""
        q = Queue()
        # Simulate stale quit left by previous run's inner finally
        q.put("quit")
        # Add tasks the new run wants processed
        for i in range(3):
            q.put({"capture": "rox", "position": i})

        t, stub = _run_executor(q)
        t.join(timeout=1.0)

        # Executor quit before processing any real tasks
        assert stub.tasks_processed == [], (
            "Without drain, stale quit stops executor before any tasks run"
        )

    def test_drain_allows_executor_to_process_new_tasks(self):
        """After draining, the new executor processes all new-run tasks."""
        q = Queue()
        # Stale state from previous run
        q.put({"goto_position": 5})
        q.put("quit")

        # Drain before starting the new run's executor
        _drain_queue(q)

        # Queue new-run tasks
        new_tasks = [
            {"capture": "rox", "position": 0},
            {"capture": "rox", "position": 1},
            {"capture": "fam", "position": 2},
        ]
        for task in new_tasks:
            q.put(task)
        q.put("quit")  # clean quit for this run

        t, stub = _run_executor(q)
        t.join(timeout=2.0)

        assert stub.tasks_processed == new_tasks

    def test_two_consecutive_aborted_runs_both_drain_correctly(self):
        """Each run drains before starting; no stale state accumulates."""
        q = Queue()

        results = []
        for run_index in range(3):
            # Simulate previous run leaving stale tasks + quit
            if run_index > 0:
                q.put({"goto_position": 99})
                q.put("quit")

            _drain_queue(q)

            tasks = [{"capture": "rox", "position": run_index}]
            for task in tasks:
                q.put(task)
            q.put("quit")

            t, stub = _run_executor(q)
            t.join(timeout=2.0)
            results.append(stub.tasks_processed)

        assert results[0] == [{"capture": "rox", "position": 0}]
        assert results[1] == [{"capture": "rox", "position": 1}]
        assert results[2] == [{"capture": "rox", "position": 2}]

    def test_executor_processes_all_tasks_before_quit(self):
        """Normal single run: executor processes all tasks in order."""
        q = Queue()
        tasks = [
            {"goto_position": 0},
            {"capture": "rox", "position": 0},
            {"goto_position": 1},
            {"capture": "rox", "position": 1},
            {"capture": "fam", "position": 1},
        ]
        for task in tasks:
            q.put(task)
        q.put("quit")

        t, stub = _run_executor(q)
        t.join(timeout=2.0)

        assert stub.tasks_processed == tasks

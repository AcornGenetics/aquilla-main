"""Unit tests for the Profile Sync Agent's run-loop coordinator (am#488, ADR-022).

The native component funnels three triggers — startup, `profiles`-shadow delta, and
a periodic interval — into a single reconcile. `SyncCoordinator` is that funnel: it
runs `agent.sync_once()`, serializes overlapping triggers, and never lets a failed
sync kill the loop. The agent is injected so this is testable without IPC/S3/threads.
Marked ``unit``.
"""
import pytest

pytestmark = pytest.mark.unit

from aquila_web.profile_sync_agent import SyncCoordinator


class FakeAgent:
    def __init__(self):
        self.calls = 0

    def sync_once(self):
        self.calls += 1


def test_reconcile_runs_a_sync():
    agent = FakeAgent()

    SyncCoordinator(agent).reconcile()

    assert agent.calls == 1


class ExplodingAgent:
    def __init__(self):
        self.calls = 0

    def sync_once(self):
        self.calls += 1
        raise RuntimeError("s3 unreachable")


def test_a_failed_sync_is_swallowed_so_the_loop_survives():
    """One bad tick (S3 blip, transient error) must not propagate and kill the run
    loop — it's logged and the next trigger still runs."""
    agent = ExplodingAgent()

    SyncCoordinator(agent).reconcile()  # must NOT raise

    assert agent.calls == 1


class ReentrantAgent:
    """Simulates a second trigger (delta/interval) arriving while a sync is running."""

    def __init__(self):
        self.calls = 0
        self.coordinator = None

    def sync_once(self):
        self.calls += 1
        if self.calls == 1:
            self.coordinator.reconcile()  # another trigger fires mid-sync


def test_overlapping_triggers_serialize_not_concurrent():
    """A reconcile that arrives while one is in progress is skipped, not run on top
    of it — no two syncs mutate managed/ at once."""
    agent = ReentrantAgent()
    coord = SyncCoordinator(agent)
    agent.coordinator = coord

    coord.reconcile()

    assert agent.calls == 1  # the re-entrant trigger was skipped

"""On-device Managed Profile sync agent — the orchestration (issue #465).

Wires the tested decisions (``parse_desired`` + ``reconcile``) to Greengrass Core
IPC and S3:

    read the ``profiles`` shadow desired  →  reconcile managed/  →  write reported

The IPC client and the S3 ``fetch``/``remote_version`` are injected — the real
greengrasscoreipc/boto3 adapters are thin glue used only on-device (wired in
``profile_sync_main`` for the native com.acorn.profile-sync component, ADR-022), so
this module holds no IPC/boto3 specifics and is unit-testable with fakes. This file
also holds ``SyncCoordinator``, which funnels the component's startup/delta/interval
triggers into a single serialized ``sync_once``. Mirrors ``update_agent.UpdateAgent``.
"""
import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from aquila_web.profile_sync import parse_desired, reconcile, reported_state


class SyncCoordinator:
    """Funnels every reconcile trigger (startup / shadow-delta / interval) into a
    single, serialized `agent.sync_once()`. Non-reentrant (overlapping triggers are
    skipped, not queued or run concurrently) and failure-tolerant (a failed sync is
    logged, never propagated) so the run loop can't be killed by one bad tick."""

    def __init__(self, agent, log: Optional[logging.Logger] = None):
        self._agent = agent
        self._log = log or logging.getLogger(__name__)
        self._lock = threading.Lock()

    def reconcile(self) -> None:
        # Non-reentrant: if a sync is already running, drop this trigger rather than
        # run a second concurrently — the next interval/delta will pick up any change.
        if not self._lock.acquire(blocking=False):
            self._log.debug("reconcile already in progress; skipping this trigger")
            return
        try:
            self._agent.sync_once()
        except Exception as e:  # noqa: BLE001 - one bad tick must not kill the loop
            self._log.warning("Managed Profile sync failed: %s", e)
        finally:
            self._lock.release()


class ProfileSyncAgent:
    def __init__(
        self,
        ipc,
        managed_dir,
        fetch: Callable[[str], bytes],
        remote_version: Optional[Callable[[str], str]] = None,
    ):
        self._ipc = ipc
        self._managed_dir = Path(managed_dir)
        self._fetch = fetch
        self._remote_version = remote_version

    def sync_once(self):
        """Read the assignment, reconcile the managed/ dir, report what's on disk.

        An unreadable/absent shadow parses to ``None`` (UNAVAILABLE) → reconcile
        keeps the cached set; the agent still reports what it actually has.
        """
        desired = parse_desired(self._ipc.get_thing_shadow("profiles"))
        result = reconcile(
            desired, self._managed_dir, self._fetch, self._remote_version
        )
        self._ipc.update_thing_shadow(reported_state(result), shadow_name="profiles")
        return result

"""On-device Managed Profile sync agent — the orchestration (issue #465).

Wires the tested decisions (``parse_desired`` + ``reconcile``) to Greengrass Core
IPC and S3:

    read the ``profiles`` shadow desired  →  reconcile managed/  →  write reported

The IPC client and the S3 ``fetch``/``remote_version`` are injected — the real
greengrasscoreipc/boto3 adapters are thin glue used only on-device (see
``greengrass_ipc.start_profile_sync_agent``), so this module holds no IPC/boto3
specifics and is unit-testable with fakes. Mirrors ``update_agent.UpdateAgent``.
"""
from pathlib import Path
from typing import Callable, Optional

from aquila_web.profile_sync import parse_desired, reconcile, reported_state


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

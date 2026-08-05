"""On-device operator update-gate (am#382).

Holds the operator-approval state for the pre-download-then-deferred-switch
model: Greengrass offers an update, the device holds the switch until the
operator approves, and the switch only applies when idle. Pure in-process state
built on the tested version_health decisions — the Phase-2 Greengrass IPC agent
reads it to decide whether to DeferComponentUpdate.
"""
from aquila_web.version_health import should_defer_update, update_banner, update_outcome


class UpdateGate:
    def __init__(self):
        self._pending_version = None
        self._approved = False
        self._last_update_failed = False

    def mark_pending(self, version):
        """Greengrass has offered `version`. A *new* version needs fresh approval;
        a re-offer of the same version (each defer recheck) keeps the approval."""
        if version != self._pending_version:
            self._approved = False
        self._pending_version = version

    def mark_update_failed(self):
        """Record that the last update did not take (running the previous version)."""
        self._last_update_failed = True

    def approve(self):
        """The operator tapped Update — release the deferred switch."""
        self._approved = True

    def should_apply(self, assay_running):
        """Apply the pre-staged switch only when idle AND operator-approved."""
        if self._pending_version is None:
            return False
        return not should_defer_update(assay_running, self._approved)

    def status(self):
        """Operator-facing gate state (served to the UI)."""
        return {
            "pending": self._pending_version is not None,
            "target_version": self._pending_version,
            "approved": self._approved,
            "banner": update_banner(self._last_update_failed),
        }


def resolve_update_result(recorded_sha, running_sha, gate, clear_record):
    """Turn the pre-apply sha + the running sha into a banner decision (am#394).

    ``recorded_sha`` is the build recorded just before a switch was allowed;
    ``running_sha`` is what's running now. On success the switch took, so forget
    the record. On rollback we're back on the old build — raise the banner and
    KEEP the record so the banner survives reboots until a later update succeeds.
    """
    outcome = update_outcome(recorded_sha, running_sha)
    if outcome == "succeeded":
        clear_record()
    elif outcome == "rolled_back":
        gate.mark_update_failed()
    return outcome


# Process-wide gate shared by the FastAPI endpoints and the Phase-2 Greengrass IPC
# agent (which runs in the same process). Reference as `update_gate.GATE` so it
# stays swappable in tests.
GATE = UpdateGate()

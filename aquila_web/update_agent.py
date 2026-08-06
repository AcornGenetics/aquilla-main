"""Greengrass update agent (am#382, Phase 2).

Wires the tested decisions (UpdateGate + version_health) to Greengrass Core IPC:
- defers an offered component update until the operator approves AND no assay runs
- publishes the Device Shadow (running SHAs + matched-pair Container Health)

The IPC client is injected — the real greengrasscoreipc adapter is used on-device;
tests pass a fake. This module holds no IPC specifics, only the orchestration.
"""
from aquila_web.version_health import build_shadow_report


class UpdateAgent:
    def __init__(self, ipc, gate, running_shas, record_pre_update=None):
        self._ipc = ipc
        self._gate = gate
        self._running_shas = running_shas
        # Records the build running just before a switch is allowed, so a later
        # boot/post-update event can tell whether Greengrass applied or rolled back
        # (am#394). No-op by default (off-device / tests that don't care).
        self._record_pre_update = record_pre_update or (lambda sha: None)

    def handle_update_offer(self, deployment_id, version):
        """Greengrass offers `version` — hold it until the operator approves."""
        self._gate.mark_pending(version)
        if not self._gate.should_apply():
            self._ipc.defer_component_update(deployment_id)
            return "deferred"
        # About to let the switch take — record the build we're leaving behind.
        api_sha, _ = self._running_shas()
        self._record_pre_update(api_sha)
        return "applied"

    def publish_health(self):
        """Report the running build SHAs + Container Health to the Device Shadow."""
        api_sha, ui_sha = self._running_shas()
        self._ipc.update_thing_shadow(build_shadow_report(api_sha, ui_sha))

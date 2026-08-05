"""On-device Greengrass Core IPC adapter for the update agent (am#382, Phase 2).

Thin wrapper over ``awsiot.greengrasscoreipc`` — imported lazily so this module
loads fine off-device (CI, local dev, tests). The testable orchestration lives in
update_agent.py / update_gate.py; this is the adapter that only means anything on
a real Sentri under Greengrass, and is verified there (not in unit tests).

Wiring on the device:
    start_update_agent(gate, running_shas, assay_running)
brings up the IPC client, subscribes to component updates (deferring per the gate),
and publishes the Device Shadow on an interval.
"""
import json
import os
import threading
import time


class GreengrassIpc:
    """Real Greengrass Core IPC — defer component updates + publish the shadow."""

    def __init__(self, thing_name=None):
        import awsiot.greengrasscoreipc.clientv2 as clientv2

        self._client = clientv2.GreengrassCoreIPCClientV2()
        self._thing_name = thing_name or os.environ["AWS_IOT_THING_NAME"]

    def defer_component_update(self, deployment_id, recheck_after_ms=30000):
        # Hold the switch; Greengrass re-offers after recheck_after_ms so the gate
        # is polled again (operator may approve / the assay may finish by then).
        self._client.defer_component_update(
            deployment_id=deployment_id, recheck_after_ms=recheck_after_ms
        )

    def update_thing_shadow(self, payload):
        # Classic (unnamed) shadow, so Fleet Indexing (REGISTRY_AND_SHADOW) indexes
        # it without a named-shadow filter change.
        self._client.update_thing_shadow(
            thing_name=self._thing_name,
            shadow_name="",
            payload=json.dumps({"state": {"reported": payload}}).encode(),
        )

    def subscribe_to_component_updates(self, on_pre_update, on_post_update=None):
        # PreComponentUpdateEvent carries the deploymentId; the handler decides
        # whether to defer. PostComponentUpdateEvent fires once a deployment
        # completes — used to re-resolve the "last update failed" banner (am#394)
        # without waiting for a reboot. Returns after establishing the stream.
        def _handle(ev):
            if getattr(ev, "pre_update_event", None):
                on_pre_update(ev.pre_update_event.deployment_id)
            elif on_post_update and getattr(ev, "post_update_event", None):
                on_post_update(ev.post_update_event.deployment_id)

        self._client.subscribe_to_component_updates(on_stream_event=_handle)


def start_update_agent(gate, running_shas, assay_running, record_pre_update=None,
                       on_post_update=None, publish_interval_s=60):
    """Bring up the on-device agent: defer-gate on updates + periodic shadow publish.

    ``record_pre_update`` persists the build running just before a switch; the agent
    calls it when it lets an update apply. ``on_post_update`` fires when a Greengrass
    deployment completes, so the banner is re-resolved immediately (am#394).

    Best-effort — if Greengrass IPC isn't available (off-device), it logs and
    returns without starting, so it never breaks a non-Greengrass boot.
    """
    from aquila_web.update_agent import UpdateAgent

    try:
        ipc = GreengrassIpc()
    except Exception as e:  # noqa: BLE001 - off-device / IPC unavailable is fine
        import logging

        # WARNING, not INFO: off-device this is expected, but on a real Sentri it
        # means the agent silently did nothing (no shadow, no operator Update gate)
        # — e.g. a missing awsiotsdk import. Make that visible in the logs.
        logging.getLogger(__name__).warning(
            "Greengrass IPC unavailable, update agent not started: %s", e
        )
        return None

    agent = UpdateAgent(ipc, gate, running_shas, assay_running,
                        record_pre_update=record_pre_update)
    # Defer/apply each offered update via the gate; re-resolve the banner on the
    # post-update event.
    ipc.subscribe_to_component_updates(
        lambda deployment_id: agent.handle_update_offer(deployment_id, deployment_id),
        on_post_update=on_post_update,
    )

    # Report health (running SHAs + Container Health) on an interval.
    def _publish_loop():
        import logging

        log = logging.getLogger(__name__)
        warned = False
        while True:
            try:
                agent.publish_health()
                warned = False
            except Exception as e:  # noqa: BLE001 - must not kill the loop
                # Log the FIRST failure of a run at WARNING (a persistently failing
                # shadow — e.g. missing ShadowManager/accessControl, #395 — must be
                # visible, not silently swallowed), then stay quiet to avoid spam.
                if not warned:
                    log.warning("Device Shadow publish failed: %s", e)
                    warned = True
            time.sleep(publish_interval_s)

    threading.Thread(target=_publish_loop, daemon=True).start()
    return agent

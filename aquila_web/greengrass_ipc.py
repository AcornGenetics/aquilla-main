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

    def subscribe_to_component_updates(self, on_pre_update):
        # PreComponentUpdateEvent carries the deploymentId; the handler decides
        # whether to defer. Returns after establishing the stream.
        self._client.subscribe_to_component_updates(
            on_stream_event=lambda ev: (
                on_pre_update(ev.pre_update_event.deployment_id)
                if getattr(ev, "pre_update_event", None)
                else None
            )
        )


def start_update_agent(gate, running_shas, assay_running, publish_interval_s=60):
    """Bring up the on-device agent: defer-gate on updates + periodic shadow publish.

    Best-effort — if Greengrass IPC isn't available (off-device), it logs and
    returns without starting, so it never breaks a non-Greengrass boot.
    """
    from aquila_web.update_agent import UpdateAgent

    try:
        ipc = GreengrassIpc()
    except Exception as e:  # noqa: BLE001 - off-device / IPC unavailable is fine
        import logging

        logging.getLogger(__name__).info("Greengrass IPC unavailable, agent not started: %s", e)
        return None

    agent = UpdateAgent(ipc, gate, running_shas, assay_running)
    # Defer/apply each offered update via the gate.
    ipc.subscribe_to_component_updates(
        lambda deployment_id: agent.handle_update_offer(deployment_id, deployment_id)
    )

    # Report health (running SHAs + Container Health) on an interval.
    def _publish_loop():
        while True:
            try:
                agent.publish_health()
            except Exception:  # noqa: BLE001 - a transient IPC error must not kill the loop
                pass
            time.sleep(publish_interval_s)

    threading.Thread(target=_publish_loop, daemon=True).start()
    return agent

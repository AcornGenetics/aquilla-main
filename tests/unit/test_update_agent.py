"""
Unit tests for the Greengrass update agent (am#382, Phase 2).

The agent wires the tested decisions (UpdateGate + version_health) to Greengrass
Core IPC. The IPC client is injected so the agent's behaviour is testable with a
fake — the real greengrasscoreipc client is a thin adapter used only on-device.

Run with:
    pytest tests/unit/test_update_agent.py -v
"""
import pytest

pytestmark = pytest.mark.unit

from aquila_web.update_agent import UpdateAgent
from aquila_web.update_gate import UpdateGate


class FakeIpc:
    def __init__(self):
        self.deferred = []
        self.shadows = []

    def defer_component_update(self, deployment_id, recheck_after_ms=None):
        self.deferred.append(deployment_id)

    def update_thing_shadow(self, payload):
        self.shadows.append(payload)


def test_defers_an_update_the_operator_has_not_approved():
    ipc = FakeIpc()
    agent = UpdateAgent(
        ipc,
        gate=UpdateGate(),
        running_shas=lambda: ("abc", "abc"),
        assay_running=lambda: False,
    )

    action = agent.handle_update_offer("deploy-1", "0.1.20")

    assert action == "deferred"
    assert ipc.deferred == ["deploy-1"]


def test_applies_on_re_offer_once_the_operator_approves():
    ipc = FakeIpc()
    gate = UpdateGate()
    agent = UpdateAgent(
        ipc, gate, running_shas=lambda: ("a", "a"), assay_running=lambda: False
    )

    agent.handle_update_offer("deploy-1", "0.1.20")  # 1st offer → deferred (unapproved)
    gate.approve()  # operator taps "Update"
    action = agent.handle_update_offer("deploy-1", "0.1.20")  # Greengrass re-offers

    assert action == "applied"
    assert ipc.deferred == ["deploy-1"]  # only the first was deferred


def test_defers_during_an_assay_even_when_approved():
    ipc = FakeIpc()
    gate = UpdateGate()
    agent = UpdateAgent(
        ipc, gate, running_shas=lambda: ("a", "a"), assay_running=lambda: True
    )
    gate.mark_pending("0.1.20")
    gate.approve()

    action = agent.handle_update_offer("deploy-1", "0.1.20")

    assert action == "deferred"  # never interrupt a run


def test_publish_health_reports_matched_pair_to_the_shadow():
    ipc = FakeIpc()
    agent = UpdateAgent(
        ipc, UpdateGate(), running_shas=lambda: ("sha1", "sha1"), assay_running=lambda: False
    )

    agent.publish_health()

    assert len(ipc.shadows) == 1
    report = ipc.shadows[0]
    assert report["images"] == {"api": "sha1", "ui": "sha1"}
    assert report["container_health"] == "matched"

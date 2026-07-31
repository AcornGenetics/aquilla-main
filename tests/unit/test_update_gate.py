"""
Unit tests for the operator update-gate (am#382).

The gate holds the on-device operator-approval state for the pre-download-then-
deferred-switch model: Greengrass offers an update (mark_pending), the device
holds the switch until the operator approves (approve), and only then — and only
when no assay is running — does the switch apply. Pure in-process state built on
the tested version_health decisions.

Run with:
    pytest tests/unit/test_update_gate.py -v
"""
import pytest

pytestmark = pytest.mark.unit

from aquila_web.update_gate import UpdateGate


def test_approved_pending_update_applies_when_idle():
    gate = UpdateGate()
    gate.mark_pending("0.1.20")
    gate.approve()

    # Idle + approved + a pending update → apply the pre-staged switch.
    assert gate.should_apply(assay_running=False) is True


def test_never_applies_during_an_assay_even_if_approved():
    gate = UpdateGate()
    gate.mark_pending("0.1.20")
    gate.approve()

    assert gate.should_apply(assay_running=True) is False


def test_does_not_apply_until_the_operator_approves():
    gate = UpdateGate()
    gate.mark_pending("0.1.20")

    assert gate.should_apply(assay_running=False) is False


def test_a_newer_pending_update_requires_fresh_approval():
    gate = UpdateGate()
    gate.mark_pending("0.1.20")
    gate.approve()

    gate.mark_pending("0.1.21")  # a newer version supersedes — re-approve required
    assert gate.should_apply(assay_running=False) is False


def test_re_offering_the_same_version_keeps_approval():
    gate = UpdateGate()
    gate.mark_pending("0.1.20")
    gate.approve()

    # Greengrass re-offers the same version after each defer — must not reset approval.
    gate.mark_pending("0.1.20")
    assert gate.should_apply(assay_running=False) is True


def test_nothing_to_apply_when_no_update_pending():
    assert UpdateGate().should_apply(assay_running=False) is False


def test_status_reports_pending_and_approval():
    gate = UpdateGate()
    assert gate.status()["pending"] is False

    gate.mark_pending("0.1.20")
    s = gate.status()
    assert s["pending"] is True
    assert s["target_version"] == "0.1.20"
    assert s["approved"] is False

    gate.approve()
    assert gate.status()["approved"] is True


def test_status_carries_a_non_blocking_banner_after_a_failed_update():
    gate = UpdateGate()
    assert gate.status()["banner"] is None

    gate.mark_update_failed()
    banner = gate.status()["banner"]
    assert banner is not None
    assert banner["blocking"] is False  # informational — the operator can still run

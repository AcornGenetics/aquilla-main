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

from aquila_web.update_gate import UpdateGate, resolve_update_result


def test_resolve_marks_failed_and_keeps_record_on_rollback():
    # Recorded "old" before applying, still "old" now ⇒ Greengrass rolled back.
    # The banner shows, and the record is KEPT so the banner persists across
    # reboots until a later successful update clears it (am#394).
    gate = UpdateGate()
    cleared = []
    resolve_update_result("old", "old", gate, clear_record=lambda: cleared.append(True))
    assert gate.status()["banner"] is not None
    assert cleared == []


def test_resolve_clears_and_no_banner_on_success():
    # Now on a different build ⇒ the switch took. Forget the record, no banner.
    gate = UpdateGate()
    cleared = []
    resolve_update_result("old", "new", gate, clear_record=lambda: cleared.append(True))
    assert gate.status()["banner"] is None
    assert cleared == [True]


def test_resolve_is_a_noop_when_no_update_was_in_flight():
    gate = UpdateGate()
    cleared = []
    resolve_update_result(None, "new", gate, clear_record=lambda: cleared.append(True))
    assert gate.status()["banner"] is None
    assert cleared == []


def test_approved_pending_update_applies():
    gate = UpdateGate()
    gate.mark_pending("0.1.20")
    gate.approve()

    # Approved + a pending update → apply the pre-staged switch.
    assert gate.should_apply() is True


def test_applies_once_approved_regardless_of_device_state():
    # Pressing "Update" IS the operator's go-ahead — the gate must not second-guess
    # it against device state (a stale 'running' screen could otherwise wedge an
    # already-approved update forever). Approval is the only condition to apply.
    gate = UpdateGate()
    gate.mark_pending("0.1.20")
    gate.approve()

    assert gate.should_apply() is True


def test_does_not_apply_until_the_operator_approves():
    gate = UpdateGate()
    gate.mark_pending("0.1.20")

    assert gate.should_apply() is False


def test_a_newer_pending_update_requires_fresh_approval():
    gate = UpdateGate()
    gate.mark_pending("0.1.20")
    gate.approve()

    gate.mark_pending("0.1.21")  # a newer version supersedes — re-approve required
    assert gate.should_apply() is False


def test_re_offering_the_same_version_keeps_approval():
    gate = UpdateGate()
    gate.mark_pending("0.1.20")
    gate.approve()

    # Greengrass re-offers the same version after each defer — must not reset approval.
    gate.mark_pending("0.1.20")
    assert gate.should_apply() is True


def test_nothing_to_apply_when_no_update_pending():
    assert UpdateGate().should_apply() is False


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


def test_mark_update_succeeded_clears_the_failure_banner():
    # A post-update event means the approved deployment applied — even one that only
    # added ShadowManager and left the app git_sha unchanged. That must clear the
    # banner, not read as a rollback (the sn01 false positive).
    gate = UpdateGate()
    gate.mark_update_failed()
    assert gate.status()["banner"] is not None

    gate.mark_update_succeeded()
    assert gate.status()["banner"] is None

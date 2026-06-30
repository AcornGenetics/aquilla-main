"""
E2E tests for the Profiles page delete confirmation (issue #261).
Verifies the themed confirm modal replaces native confirm() on Profile deletes.
Requires a running backend at base_url (default http://localhost:8090).
Run with: pytest -m e2e tests/e2e/test_profiles.py
"""
import httpx
import pytest

pytestmark = pytest.mark.e2e


def _create_profile(base_url: str, name: str) -> str:
    payload = {
        "name": name,
        "fam_label": "FAM Target",
        "rox_label": "ROX Target",
        "steps": [
            {"setpoint": 95, "duration": 30},
            {"setpoint": 55, "duration": 60},
            {"setpoint": 72, "duration": 60},
        ],
    }
    try:
        resp = httpx.post(f"{base_url}/profiles", json=payload, timeout=5)
        resp.raise_for_status()
    except Exception as exc:
        pytest.skip(f"Could not create profile: {exc}")
    return resp.json()["id"]


def _delete_profile(base_url: str, profile_id: str) -> None:
    try:
        httpx.post(f"{base_url}/profiles/delete", json={"profiles": [profile_id]}, timeout=5)
    except Exception:
        pass


def _goto_profiles(page, base_url, name):
    try:
        page.goto(f"{base_url}/profiles-page", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    page.wait_for_load_state("domcontentloaded")
    row = page.locator("#profiles-table-body tr", has_text=name)
    row.wait_for(state="visible", timeout=5_000)
    return row


def test_profile_delete_confirm_removes(page, base_url):
    """Delete → themed modal naming the profile → Delete removes it."""
    name = "E2E Delete Profile"
    profile_id = _create_profile(base_url, name)
    try:
        row = _goto_profiles(page, base_url, name)
        row.locator(".profile-checkbox").check()
        page.locator("#profiles-delete-button").click()
        modal = page.locator(".confirm-modal")
        modal.wait_for(state="visible", timeout=3_000)
        assert name in modal.inner_text(), "Modal detail should list the profile name"
        page.locator(".confirm-modal__btn--confirm").click()
        page.wait_for_function(
            "(n) => !Array.from(document.querySelectorAll('#profiles-table-body tr'))"
            "      .some(tr => tr.textContent.includes(n))",
            arg=name,
            timeout=5_000,
        )
    finally:
        _delete_profile(base_url, profile_id)


def test_profile_delete_cancel_keeps(page, base_url):
    """Cancel dismisses the modal and deletes nothing (fail-closed)."""
    name = "E2E Keep Profile"
    profile_id = _create_profile(base_url, name)
    try:
        row = _goto_profiles(base_url=base_url, page=page, name=name)
        row.locator(".profile-checkbox").check()
        page.locator("#profiles-delete-button").click()
        page.locator(".confirm-modal").wait_for(state="visible", timeout=3_000)
        page.locator(".confirm-modal__btn--cancel").click()
        page.locator(".confirm-modal").wait_for(state="hidden", timeout=3_000)
        assert name in page.locator("#profiles-table-body").inner_text()
    finally:
        _delete_profile(base_url, profile_id)

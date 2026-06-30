"""
E2E test for issue #265 — the live Run-card header must keep showing the running
profile's name (and run name) when the operator navigates away from /run and back
mid-run.

The header previously read the profile name straight from the #mySelect dropdown's
selected <option>. On a fresh load into a running state, if loadProfiles() cannot
re-select the running profile in the dropdown (e.g. the device's profile filtering
hides it from the list), the dropdown falls back to its disabled "Select a profile"
placeholder and the header displayed that placeholder text as if it were the
profile. The run name (sourced from /run/name) was unaffected — matching the
reported symptom.

The fix sources the running header from server-authoritative state, so the header
shows the real profile name regardless of what the dropdown could resolve.

Requires a running backend at base_url (default http://localhost:8090).
Run with: pytest -m e2e tests/e2e/test_run_header_persist.py
"""
import json

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

PLACEHOLDER = "Select a profile"


def _post(page, base_url, path, body):
    return page.request.post(
        f"{base_url}{path}",
        data=json.dumps(body),
        headers={"content-type": "application/json"},
    )


def _reset(page, base_url):
    """Return the backend to a clean idle state."""
    _post(page, base_url, "/change_screen/", {"title": "READY", "text": "x", "screen": "ready"})
    page.request.post(f"{base_url}/run_status/reset")


def test_running_header_shows_profile_when_dropdown_cannot_resolve(page, base_url):
    # A real profile is the active run, server-side.
    try:
        profiles = page.request.get(f"{base_url}/profiles", timeout=10_000).json()
    except Exception as exc:  # backend not reachable
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    if not profiles:
        pytest.skip("No profiles available on backend")

    profile = profiles[0]
    profile_id = profile["id"]
    profile_name = profile.get("name") or profile.get("label") or profile_id

    _post(page, base_url, "/profile/select", {"profile": profile_id})
    _post(page, base_url, "/run/name", {"name": "navtest7"})
    _post(page, base_url, "/change_screen/", {"title": "RUN", "text": "x", "screen": "running"})

    # Simulate the device condition: the running profile is NOT present in the
    # /profiles list the page loads, so the dropdown cannot re-select it.
    def _filter_out_running_profile(route):
        remaining = [p for p in profiles if p["id"] != profile_id]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(remaining),
        )

    page.route("**/profiles", _filter_out_running_profile)

    try:
        page.goto(f"{base_url}/run", timeout=10_000)
        page.wait_for_load_state("domcontentloaded")

        profile_header = page.locator("#run-start-profile")
        runname_header = page.locator("#run-start-runname")

        # The header must show the real running profile, never the dropdown
        # placeholder, and the run name must remain correct.
        expect(profile_header).to_have_text(profile_name, timeout=5_000)
        expect(profile_header).not_to_have_text(PLACEHOLDER)
        expect(runname_header).to_have_text("navtest7", timeout=5_000)
    finally:
        _reset(page, base_url)


def test_running_header_shows_profile_for_listed_profile(page, base_url):
    """Happy path: a running profile that IS in the dropdown still shows in the
    header (server-authoritative path must not regress the common case)."""
    try:
        profiles = page.request.get(f"{base_url}/profiles", timeout=10_000).json()
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    if not profiles:
        pytest.skip("No profiles available on backend")

    profile = profiles[0]
    profile_name = profile.get("name") or profile.get("label") or profile["id"]

    _post(page, base_url, "/profile/select", {"profile": profile["id"]})
    _post(page, base_url, "/run/name", {"name": "navtest8"})
    _post(page, base_url, "/change_screen/", {"title": "RUN", "text": "x", "screen": "running"})

    try:
        page.goto(f"{base_url}/run", timeout=10_000)
        page.wait_for_load_state("domcontentloaded")
        expect(page.locator("#run-start-profile")).to_have_text(profile_name, timeout=5_000)
        expect(page.locator("#run-start-runname")).to_have_text("navtest8", timeout=5_000)
    finally:
        _reset(page, base_url)


def test_run_header_hidden_on_ready(page, base_url):
    """On the ready screen the summary header is hidden (no leftover run identity)."""
    _reset(page, base_url)
    try:
        page.goto(f"{base_url}/run", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    page.wait_for_load_state("domcontentloaded")
    # The summary carries the is-hidden class while not running/complete.
    expect(page.locator("#run-start-summary")).to_have_class("run-start-summary is-hidden", timeout=5_000)

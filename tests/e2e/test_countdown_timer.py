"""
E2E DOM checks for the countdown-timer feature.

These confirm the new UI elements render into the page in the correct initial
state. They do NOT drive a live run — the timing-dependent countdown behavior
(label flip, finishing flag, stop precedence) is covered by the manual dev
checklist in spec §9.4.

Requires a running backend at base_url (default http://localhost:8090).
Run with: pytest -m e2e tests/e2e/test_countdown_timer.py
"""
import json

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def _goto(page, base_url, path):
    """Navigate to *path*; skip the test if the backend is not reachable."""
    try:
        page.goto(f"{base_url}{path}", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")


def _route_details(page, *, estimate_seconds, title="Beer Spoilage"):
    """Stub GET /profiles/details so the active profile reports *estimate_seconds*
    (or None for no estimate), independent of the selection-warmed client cache."""
    body = json.dumps(
        {
            "id": "beer.json",
            "title": title,
            "labels": {},
            "rox_unavailable": False,
            "time_unavailable": estimate_seconds is None,
            "estimated_completion_seconds": estimate_seconds,
            "steps": [],
        }
    )
    page.route(
        "**/profiles/details*",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=body
        ),
    )


def _drive_running(page, *, profile_name="Beer Spoilage", cached_estimate="null"):
    """Drive the real WebSocket 'running' transition with a cold-or-warm estimate
    cache, mirroring a reset -> re-run where the selection cache was never re-warmed.
    Goes through wsHandleMessage() — the same path the live socket uses."""
    page.evaluate(
        """([name, cached]) => {
            cachedEstimateSeconds = cached;   // simulate post-reset cache state
            lastScreen = 'ready';
            wsHandleMessage({ data: JSON.stringify({
                screen: 'running', profile_name: name, elapsed: 1
            }) });
        }""",
        [profile_name, None if cached_estimate == "null" else cached_estimate],
    )


# ---------------------------------------------------------------------------
# Run screen
# ---------------------------------------------------------------------------

def test_finishing_modal_present_and_hidden(page, base_url):
    """The 'Finishing Run' overlay exists in the DOM and is hidden by default."""
    _goto(page, base_url, "/run")
    modal = page.locator("#run-finishing-modal")
    assert modal.count() == 1, "#run-finishing-modal not found"
    assert "is-hidden" in (modal.get_attribute("class") or ""), (
        "Finishing modal should start hidden"
    )
    assert "Finishing Run" in modal.inner_text(), "Finishing modal text missing"


def test_timer_label_element_present(page, base_url):
    """The timer label (#run-timer-label) the JS toggles must exist."""
    _goto(page, base_url, "/run")
    assert page.locator("#run-timer-label").count() == 1, "#run-timer-label not found"


# ---------------------------------------------------------------------------
# #312 regression: countdown must survive Reset + re-run (cold estimate cache)
# ---------------------------------------------------------------------------

def test_countdown_shown_when_cache_cold_but_profile_has_estimate(page, base_url):
    """#312: after a run completes and Reset clears the selection, re-running the
    same estimate-bearing profile must STILL show the countdown. The mode is
    re-derived from the authoritative active profile at run start, not from the
    selection-only cache (which is cold here)."""
    _route_details(page, estimate_seconds=3900)
    _goto(page, base_url, "/run")
    _drive_running(page, cached_estimate="null")  # cold cache, as after Reset
    expect(page.locator("#run-timer-label")).to_have_text("Time Remaining")


def test_stopwatch_stays_stopwatch_when_profile_has_no_estimate(page, base_url):
    """A profile with no estimate must keep the stopwatch on every run — the
    authoritative fetch must not wrongly force countdown mode."""
    _route_details(page, estimate_seconds=None)
    _goto(page, base_url, "/run")
    _drive_running(page, cached_estimate="null")
    expect(page.locator("#run-timer-label")).to_have_text("Elapsed Time")


def test_late_estimate_fetch_after_reset_is_ignored(page, base_url):
    """#312 race guard: a /profiles/details response that resolves AFTER Reset must
    not flip the timer back to countdown. The run-start fetch is held pending, Reset
    happens, then the estimate arrives late — the label must stay on the stopwatch."""
    pending = []
    page.route("**/profiles/details*", lambda route: pending.append(route))
    _goto(page, base_url, "/run")
    _drive_running(page, cached_estimate="null")  # issues the estimate fetch
    for _ in range(50):  # wait until the fetch is actually intercepted
        if pending:
            break
        page.wait_for_timeout(50)
    assert pending, "expected /profiles/details to be requested at run start"

    page.evaluate("() => resetTimerMode()")  # Reset before the estimate resolves
    expect(page.locator("#run-timer-label")).to_have_text("Elapsed Time")

    pending[0].fulfill(  # the late estimate now arrives — must be ignored
        status=200,
        content_type="application/json",
        body=json.dumps(
            {"time_unavailable": False, "estimated_completion_seconds": 3900}
        ),
    )
    page.wait_for_timeout(200)
    expect(page.locator("#run-timer-label")).to_have_text("Elapsed Time")


# ---------------------------------------------------------------------------
# Edit / Create profile form
# ---------------------------------------------------------------------------

def test_estimate_field_present_with_optional_placeholder(page, base_url):
    """The estimated-time input renders with the greyed-out (Optional) placeholder."""
    _goto(page, base_url, "/profiles/edit")
    inp = page.locator("#profile-estimated-minutes")
    assert inp.count() == 1, "#profile-estimated-minutes not found on edit form"
    assert inp.get_attribute("placeholder") == "(Optional)", (
        "Estimate input should have placeholder '(Optional)'"
    )

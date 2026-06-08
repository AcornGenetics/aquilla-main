"""
E2E DOM checks for the countdown-timer feature.

These confirm the new UI elements render into the page in the correct initial
state. They do NOT drive a live run — the timing-dependent countdown behavior
(label flip, finishing flag, stop precedence) is covered by the manual dev
checklist in spec §9.4.

Requires a running backend at base_url (default http://localhost:8090).
Run with: pytest -m e2e tests/e2e/test_countdown_timer.py
"""
import pytest

pytestmark = pytest.mark.e2e


def _goto(page, base_url, path):
    """Navigate to *path*; skip the test if the backend is not reachable."""
    try:
        page.goto(f"{base_url}{path}", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")


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

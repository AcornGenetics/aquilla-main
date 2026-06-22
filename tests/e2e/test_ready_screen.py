"""
E2E tests for the Run / Ready screen of the Sentri PCR kiosk UI.
Requires a running backend at base_url (default http://localhost:8090).
Run with: pytest -m e2e tests/e2e/test_ready_screen.py
"""
import pytest

pytestmark = pytest.mark.e2e


def _goto_run(page, base_url):
    """Navigate to /run and skip if backend is not available."""
    try:
        page.goto(f"{base_url}/run", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")


# ---------------------------------------------------------------------------
# Page load
# ---------------------------------------------------------------------------

def test_page_loads_without_console_errors(page, base_url):
    """No JS console errors should appear when the run page first loads."""
    errors = []
    page.on("console", lambda msg: errors.append(msg) if msg.type == "error" else None)
    _goto_run(page, base_url)
    page.wait_for_load_state("domcontentloaded")
    # WebSocket errors are expected in a test env – filter those out
    real_errors = [
        e for e in errors
        if "WebSocket" not in e.text and "ws://" not in e.text
    ]
    assert real_errors == [], f"Unexpected console errors: {[e.text for e in real_errors]}"


# ---------------------------------------------------------------------------
# Visible elements
# ---------------------------------------------------------------------------

def test_start_run_heading_visible(page, base_url):
    _goto_run(page, base_url)
    heading = page.locator("h2", has_text="Start Run")
    assert heading.is_visible(), "'Start Run' h2 not visible"


def test_profile_dropdown_exists_and_visible(page, base_url):
    _goto_run(page, base_url)
    select = page.locator("#mySelect")
    assert select.count() == 1, "Profile <select> not found"
    assert select.is_visible(), "Profile <select> not visible"


def test_run_name_input_exists(page, base_url):
    _goto_run(page, base_url)
    inp = page.locator("#run-name-input")
    assert inp.count() == 1, "Run name input not found"
    assert inp.is_visible(), "Run name input not visible"


def test_run_button_exists(page, base_url):
    _goto_run(page, base_url)
    # Match either via aria-label or class
    btn = page.locator("[aria-label='Run'], .run-cta")
    assert btn.first.is_visible(), "Run CTA button not visible"


def test_open_drawer_button_exists(page, base_url):
    _goto_run(page, base_url)
    btn = page.get_by_text("Open Drawer", exact=True)
    assert btn.count() >= 1, "Open Drawer button not found"
    assert btn.first.is_visible(), "Open Drawer button not visible"


def test_close_drawer_button_exists(page, base_url):
    _goto_run(page, base_url)
    btn = page.get_by_text("Close Drawer", exact=True)
    assert btn.count() >= 1, "Close Drawer button not found"
    assert btn.first.is_visible(), "Close Drawer button not visible"


def test_reset_button_exists(page, base_url):
    _goto_run(page, base_url)
    btn = page.locator("#run-reset-button")
    assert btn.count() == 1, "Reset button not found"
    # Reset may be hidden until state updates; just confirm it exists in the DOM
    assert btn.count() == 1


def test_help_link_exists(page, base_url):
    _goto_run(page, base_url)
    link = page.locator("a.help-link")
    assert link.count() >= 1, "Help link not found"


# ---------------------------------------------------------------------------
# Navigation links
# ---------------------------------------------------------------------------

def test_nav_run_link_visible(page, base_url):
    _goto_run(page, base_url)
    assert page.locator("a.run-nav-link[href='/run']").is_visible()


def test_nav_history_link_visible(page, base_url):
    _goto_run(page, base_url)
    assert page.locator("a.run-nav-link[href='/history']").is_visible()


def test_nav_profiles_link_visible(page, base_url):
    _goto_run(page, base_url)
    # href may include query params (e.g. ?v=2)
    link = page.locator("a.run-nav-link[href*='/profiles-page']")
    assert link.is_visible(), "Profiles nav link not visible"


# ---------------------------------------------------------------------------
# Ready pill
# ---------------------------------------------------------------------------

def test_ready_pill_shows_ready_text(page, base_url):
    _goto_run(page, base_url)
    pill_text = page.locator("#ready-status")
    assert pill_text.is_visible(), "#ready-status span not visible"
    assert pill_text.inner_text().strip() == "Ready", (
        f"Expected 'Ready', got '{pill_text.inner_text().strip()}'"
    )


def test_default_run_start_dot_color_is_purple(page, base_url):
    """The decorative dot next to 'Start Run' should be purple (#8b5cf6) by default."""
    _goto_run(page, base_url)
    dot = page.locator(".run-start-dot")
    assert dot.count() >= 1, ".run-start-dot not found"
    bg_color = dot.first.evaluate(
        "el => window.getComputedStyle(el).backgroundColor"
    )
    # Browsers return rgb(r, g, b) – convert #8b5cf6 → rgb(139, 92, 246)
    assert bg_color == "rgb(139, 92, 246)", (
        f"Expected rgb(139, 92, 246) for purple dot, got '{bg_color}'"
    )

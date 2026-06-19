"""
E2E tests for the on-screen keyboard on the Sentri PCR kiosk UI.
Requires a running backend at base_url (default http://localhost:8090).
Run with: pytest -m e2e tests/e2e/test_keyboard.py
"""
import pytest

pytestmark = pytest.mark.e2e

KEYBOARD_SELECTOR = ".onscreen-keyboard"
RUN_NAME_INPUT = "#run-name-input"


def _goto_run(page, base_url):
    try:
        page.goto(f"{base_url}/run", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    page.wait_for_load_state("domcontentloaded")


def _show_keyboard(page):
    """Click the run-name input to trigger the on-screen keyboard."""
    inp = page.locator(RUN_NAME_INPUT)
    inp.click()
    # Give the keyboard animation a moment to apply is-visible
    page.wait_for_function(
        "() => document.querySelector('.onscreen-keyboard')?.classList.contains('is-visible')",
        timeout=3_000,
    )


def _hide_keyboard(page):
    """Click the close (✕) button to dismiss the keyboard."""
    close_btn = page.locator(".keyboard-close-btn")
    close_btn.click()
    page.wait_for_function(
        "() => !document.querySelector('.onscreen-keyboard')?.classList.contains('is-visible')",
        timeout=3_000,
    )


# ---------------------------------------------------------------------------
# Keyboard visibility
# ---------------------------------------------------------------------------

def test_clicking_run_name_shows_keyboard(page, base_url):
    _goto_run(page, base_url)
    _show_keyboard(page)
    keyboard = page.locator(KEYBOARD_SELECTOR)
    assert keyboard.count() == 1, "On-screen keyboard element not found in DOM"
    assert keyboard.is_visible(), "On-screen keyboard not visible after clicking input"


def test_keyboard_has_letter_keys(page, base_url):
    _goto_run(page, base_url)
    _show_keyboard(page)
    for letter in ("a", "q", "z"):
        key_btn = page.locator(f"[data-value='{letter}']")
        assert key_btn.count() >= 1, f"Key '{letter}' not found in keyboard"


# ---------------------------------------------------------------------------
# Key input behaviour
# ---------------------------------------------------------------------------

def test_pressing_key_a_inserts_into_input(page, base_url):
    _goto_run(page, base_url)
    # Clear any existing value first
    page.locator(RUN_NAME_INPUT).fill("")
    _show_keyboard(page)
    page.locator("[data-value='a']").click()
    value = page.locator(RUN_NAME_INPUT).input_value()
    assert "a" in value, f"Expected 'a' in input after pressing key, got '{value}'"


def test_backspace_removes_last_character(page, base_url):
    _goto_run(page, base_url)
    page.locator(RUN_NAME_INPUT).fill("hello")
    _show_keyboard(page)
    page.locator("[data-value='backspace']").click()
    value = page.locator(RUN_NAME_INPUT).input_value()
    assert value == "hell", f"Expected 'hell' after backspace, got '{value}'"


# ---------------------------------------------------------------------------
# Close / dismiss behaviour
# ---------------------------------------------------------------------------

def test_close_button_dismisses_keyboard(page, base_url):
    _goto_run(page, base_url)
    _show_keyboard(page)
    assert page.locator(KEYBOARD_SELECTOR).is_visible(), "Keyboard should be visible before close"
    _hide_keyboard(page)
    keyboard = page.locator(KEYBOARD_SELECTOR)
    # After dismissal the element stays in the DOM but loses is-visible
    assert not keyboard.evaluate("el => el.classList.contains('is-visible')"), (
        "Keyboard still has 'is-visible' class after close"
    )


def test_body_padding_bottom_cleared_after_dismiss(page, base_url):
    _goto_run(page, base_url)
    _show_keyboard(page)
    _hide_keyboard(page)
    padding = page.evaluate("() => document.body.style.paddingBottom")
    assert padding == "", f"Expected empty paddingBottom after dismiss, got '{padding}'"


def test_body_gets_keyboard_visible_class_when_shown(page, base_url):
    _goto_run(page, base_url)
    _show_keyboard(page)
    has_class = page.evaluate(
        "() => document.body.classList.contains('keyboard-visible')"
    )
    assert has_class, "body should have 'keyboard-visible' class while keyboard is open"


def test_body_loses_keyboard_visible_class_after_dismiss(page, base_url):
    _goto_run(page, base_url)
    _show_keyboard(page)
    _hide_keyboard(page)
    has_class = page.evaluate(
        "() => document.body.classList.contains('keyboard-visible')"
    )
    assert not has_class, "body should NOT have 'keyboard-visible' class after keyboard dismissed"


# ---------------------------------------------------------------------------
# Keyboard should not appear on non-input elements
# ---------------------------------------------------------------------------

def test_keyboard_does_not_appear_on_non_input_click(page, base_url):
    _goto_run(page, base_url)
    # Click a heading – not an input
    page.locator("h2", has_text="Start Run").click()
    is_visible = page.evaluate(
        "() => document.querySelector('.onscreen-keyboard')?.classList.contains('is-visible') ?? false"
    )
    assert not is_visible, "Keyboard should NOT be visible after clicking a non-input element"

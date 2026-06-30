"""
E2E tests for the custom-styled Run-screen dropdowns (issue #166).

Profile picker (custom listbox over a hidden native <select>), Run Name autofill
suppression, and the dev-only optics-path typeahead.

Requires a running backend at base_url (default http://localhost:8090; override
with AQUILA_TEST_URL). Run with: pytest -m e2e tests/e2e/test_run_dropdowns.py
"""
import pytest

pytestmark = pytest.mark.e2e

PROFILE_BUTTON = "#profile-combo-button"
PROFILE_LIST = "#profile-combo-list"
PROFILE_OPTION = "#profile-combo-list [role='option']"
RUN_NAME_INPUT = "#run-name-input"
OPTICS_INPUT = "#dev-optics-path"
OPTICS_LIST = "#optics-suggestions"
OPTICS_OPTION = "#optics-suggestions [role='option']"


def _goto_run(page, base_url):
    try:
        page.goto(f"{base_url}/run", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    page.wait_for_load_state("domcontentloaded")


def test_clicking_profile_button_opens_listbox_with_options(page, base_url):
    _goto_run(page, base_url)
    # Profiles load asynchronously; wait for at least one custom option to exist.
    page.wait_for_selector(PROFILE_OPTION, state="attached", timeout=5_000)

    page.locator(PROFILE_BUTTON).click()

    assert page.locator(PROFILE_LIST).is_visible()
    assert page.locator(PROFILE_OPTION).count() >= 1


def test_selecting_option_updates_label_and_fires_native_change(page, base_url):
    _goto_run(page, base_url)
    page.wait_for_selector(PROFILE_OPTION, state="attached", timeout=5_000)
    page.locator(PROFILE_BUTTON).click()

    option = page.locator(PROFILE_OPTION).first
    value = option.get_attribute("data-value")
    text = option.inner_text()
    option.click()

    # Button label reflects the selection.
    assert page.locator("#profile-combo-label").inner_text() == text
    # Hidden native <select> (source of truth) is updated.
    assert page.locator("#mySelect").input_value() == value
    # Native `change` propagated to the backend (/profile/select via change handler).
    page.wait_for_function(
        "(v) => fetch('/button_status').then(r => r.json()).then(s => s.profile === v)",
        arg=value,
        timeout=3_000,
    )


def test_escape_and_outside_click_dismiss_the_list(page, base_url):
    _goto_run(page, base_url)
    page.wait_for_selector(PROFILE_OPTION, state="attached", timeout=5_000)

    # Escape closes.
    page.locator(PROFILE_BUTTON).click()
    assert page.locator(PROFILE_LIST).is_visible()
    page.keyboard.press("Escape")
    assert not page.locator(PROFILE_LIST).is_visible()

    # Outside click closes.
    page.locator(PROFILE_BUTTON).click()
    assert page.locator(PROFILE_LIST).is_visible()
    page.locator("body").click(position={"x": 5, "y": 5})
    assert not page.locator(PROFILE_LIST).is_visible()


def test_run_name_input_suppresses_native_autofill(page, base_url):
    _goto_run(page, base_url)
    assert page.locator(RUN_NAME_INPUT).get_attribute("autocomplete") == "off"


def test_profile_combo_force_closes_when_leaving_ready(page, base_url):
    _goto_run(page, base_url)
    page.wait_for_selector(PROFILE_OPTION, state="attached", timeout=5_000)

    page.locator(PROFILE_BUTTON).click()
    assert page.locator(PROFILE_LIST).is_visible()

    # Screen leaves ready (a run starts) then returns (run completes). Without a
    # force-close, the list would re-appear stale-open when ready is shown again.
    page.evaluate("updateDashboardSections('running')")
    page.evaluate("updateDashboardSections('ready')")

    assert "is-open" not in (page.locator(PROFILE_LIST).get_attribute("class") or "")
    assert not page.locator(PROFILE_LIST).is_visible()


def _require_optics(page):
    optics = page.locator(OPTICS_INPUT)
    if optics.count() == 0 or not optics.is_visible():
        pytest.skip("Optics field is only present in dev/simulation mode")
    return optics


def test_optics_typeahead_filters_server_history(page, base_url):
    _goto_run(page, base_url)
    optics = _require_optics(page)

    page.request.post(f"{base_url}/dev/optics_path", data={"path": "/data/alpha.log"})
    page.request.post(f"{base_url}/dev/optics_path", data={"path": "/data/beta.log"})
    page.reload()
    page.wait_for_load_state("domcontentloaded")

    optics = _require_optics(page)
    optics.click()
    optics.fill("alpha")

    page.wait_for_selector(OPTICS_OPTION, timeout=3_000)
    texts = page.locator(OPTICS_OPTION).all_inner_texts()
    assert any("alpha" in t for t in texts)
    assert all("beta" not in t for t in texts)


def test_selecting_optics_suggestion_sets_input(page, base_url):
    _goto_run(page, base_url)
    optics = _require_optics(page)

    page.request.post(f"{base_url}/dev/optics_path", data={"path": "/data/gamma.log"})
    page.reload()
    page.wait_for_load_state("domcontentloaded")

    optics = _require_optics(page)
    optics.click()
    optics.fill("gamma")
    page.wait_for_selector(OPTICS_OPTION, timeout=3_000)
    page.locator(OPTICS_OPTION, has_text="gamma").first.click()

    assert page.locator(OPTICS_INPUT).input_value() == "/data/gamma.log"
    assert not page.locator(OPTICS_LIST).is_visible()


def test_optics_input_is_excluded_from_onscreen_keyboard(page, base_url):
    _goto_run(page, base_url)
    optics = _require_optics(page)
    classes = optics.get_attribute("class") or ""
    assert "keyboard-ignore" in classes
    assert optics.get_attribute("autocomplete") == "off"


# ---------------------------------------------------------------------------
# Long profile name truncation (issue #266)
# ---------------------------------------------------------------------------

import httpx

LONG_PROFILE_NAME = (
    "Very Long Profile Name That Should Definitely Overflow The Run Screen Picker Box"
)


def _create_long_profile(base_url: str, name: str) -> str:
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


def test_long_profile_name_truncates_with_ellipsis(page, base_url):
    """A long selected profile name stays inside the box: single-line, clipped,
    text-overflow: ellipsis — while the full text remains in the DOM and the
    chevron is not pushed out."""
    profile_id = _create_long_profile(base_url, LONG_PROFILE_NAME)
    try:
        _goto_run(page, base_url)
        page.wait_for_selector(PROFILE_OPTION, state="attached", timeout=5_000)
        page.locator(PROFILE_BUTTON).click()
        page.locator(PROFILE_OPTION, has_text=LONG_PROFILE_NAME).first.click()

        label = page.locator("#profile-combo-label")
        # The full name stays in the DOM — only the *display* is clipped.
        assert label.inner_text() == LONG_PROFILE_NAME

        metrics = label.evaluate(
            "el => ({"
            "  scroll: el.scrollWidth, client: el.clientWidth,"
            "  overflow: getComputedStyle(el).textOverflow,"
            "  whiteSpace: getComputedStyle(el).whiteSpace"
            "})"
        )
        assert metrics["scroll"] > metrics["client"], "label is not clipped (no overflow)"
        assert metrics["overflow"] == "ellipsis"
        assert metrics["whiteSpace"] == "nowrap"

        # The button must not overflow its own box (chevron stays put).
        button_overflow = page.locator(PROFILE_BUTTON).evaluate(
            "el => el.scrollWidth - el.clientWidth"
        )
        assert button_overflow <= 1, f"profile button overflows its box by {button_overflow}px"
    finally:
        try:
            httpx.post(f"{base_url}/profiles/delete", json={"profiles": [profile_id]}, timeout=5)
        except Exception:
            pass

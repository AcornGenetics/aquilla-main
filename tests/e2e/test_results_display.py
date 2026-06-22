"""
E2E tests for results rendering on the Sentri PCR kiosk run page.
Requires a running backend at base_url (default http://localhost:8090).
Run with: pytest -m e2e tests/e2e/test_results_display.py
"""
import pathlib

import httpx
import pytest

pytestmark = pytest.mark.e2e

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "results"

# Colour constants (as returned by window.getComputedStyle)
COLOR_PURPLE = "rgb(139, 92, 246)"    # #8b5cf6 – default / no result
COLOR_ORANGE = "rgb(252, 96, 2)"      # #fc6002 – detected
COLOR_GREEN = "rgb(194, 242, 130)"    # #c2f282 – not detected
COLOR_YELLOW = "rgb(242, 201, 125)"   # #f2c97d – inconclusive
COLOR_WHITE = "rgb(255, 255, 255)"    # default half colour before any result


def _goto_run(page, base_url):
    try:
        page.goto(f"{base_url}/run", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    page.wait_for_load_state("domcontentloaded")


def _set_results_path(base_url: str, fixture_name: str) -> None:
    """POST to /results/path to tell the backend which results file to serve."""
    fixture_path = (FIXTURES_DIR / fixture_name).resolve()
    try:
        resp = httpx.post(
            f"{base_url}/results/path",
            json={"path": str(fixture_path)},
            timeout=5,
        )
        resp.raise_for_status()
    except Exception as exc:
        pytest.skip(f"Could not set results path: {exc}")


def _clear_results(base_url: str) -> None:
    try:
        httpx.post(f"{base_url}/results/clear", timeout=5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Default / pre-run state
# ---------------------------------------------------------------------------

def test_default_dot_halves_are_white_before_any_run(page, base_url):
    """Before any run the dot halves have no status class and appear white."""
    _clear_results(base_url)
    _goto_run(page, base_url)
    halves = page.locator(".results-dot__half")
    assert halves.count() == 8, f"Expected 8 dot halves (4 tubes × 2), got {halves.count()}"
    for i in range(halves.count()):
        half = halves.nth(i)
        bg = half.evaluate("el => window.getComputedStyle(el).backgroundColor")
        # Without a status class the halves render white
        assert bg == COLOR_WHITE, (
            f"Half {i} expected white (no result), got '{bg}'"
        )


def test_run_for_results_shown_before_run(page, base_url):
    _clear_results(base_url)
    _goto_run(page, base_url)
    summary = page.locator("#results-summary")
    assert summary.is_visible(), "#results-summary not visible"
    text = summary.inner_text().strip()
    assert "Run for results" in text or text == "Run for results!", (
        f"Unexpected summary text before run: '{text}'"
    )


def test_four_tube_dots_visible(page, base_url):
    _goto_run(page, base_url)
    dots = page.locator(".results-dot")
    assert dots.count() == 4, f"Expected 4 tube dots, found {dots.count()}"
    for i in range(4):
        assert dots.nth(i).is_visible(), f"Tube dot {i + 1} not visible"


def test_four_tube_label_inputs_visible(page, base_url):
    _goto_run(page, base_url)
    inputs = page.locator(".results-tube__label-input")
    assert inputs.count() == 4, f"Expected 4 tube label inputs, found {inputs.count()}"
    for i in range(4):
        assert inputs.nth(i).is_visible(), f"Tube label input {i + 1} not visible"


# ---------------------------------------------------------------------------
# Results rendering after setting a results file
# ---------------------------------------------------------------------------

def _reload_results(page, base_url):
    """Navigate to the run page in 'complete' state by using the detail path trick.

    Because the run page only shows coloured dots when currentScreen === 'complete'
    (driven by WebSocket), we instead read the results by navigating to a history
    detail page seeded with the fixture, or we call loadResults() directly via JS.
    For the purposes of these tests we call the JS function directly after setting
    the path, bypassing the WS state check.
    """
    _goto_run(page, base_url)
    # Override the screen guard so loadResults() will actually render colours
    page.evaluate("""
        () => {
            // Bypass the 'currentScreen !== complete' guard
            window.currentScreen = 'complete';
            if (typeof loadResults === 'function') loadResults();
        }
    """)
    # Give the async fetch a moment to complete
    page.wait_for_timeout(800)


def test_detected_tube_dot_half_is_orange(page, base_url):
    """Tube 1 FAM/ROX detected → both halves should be orange."""
    _set_results_path(base_url, "detected.json")
    _reload_results(page, base_url)
    tube1_dot = page.locator(".results-tube[data-tube='1'] .results-dot__half")
    assert tube1_dot.count() == 2
    for i in range(2):
        bg = tube1_dot.nth(i).evaluate("el => window.getComputedStyle(el).backgroundColor")
        assert bg == COLOR_ORANGE, (
            f"Tube 1 half {i} expected orange (detected), got '{bg}'"
        )


def test_not_detected_tube_dot_half_is_green(page, base_url):
    """Tube 1 not-detected → both halves should be green."""
    _set_results_path(base_url, "not_detected.json")
    _reload_results(page, base_url)
    tube1_dot = page.locator(".results-tube[data-tube='1'] .results-dot__half")
    assert tube1_dot.count() == 2
    for i in range(2):
        bg = tube1_dot.nth(i).evaluate("el => window.getComputedStyle(el).backgroundColor")
        assert bg == COLOR_GREEN, (
            f"Tube 1 half {i} expected green (not detected), got '{bg}'"
        )


def test_inconclusive_tube_dot_half_is_yellow(page, base_url):
    """Tube 1 inconclusive → both halves should be yellow."""
    _set_results_path(base_url, "inconclusive.json")
    _reload_results(page, base_url)
    tube1_dot = page.locator(".results-tube[data-tube='1'] .results-dot__half")
    assert tube1_dot.count() == 2
    for i in range(2):
        bg = tube1_dot.nth(i).evaluate("el => window.getComputedStyle(el).backgroundColor")
        assert bg == COLOR_YELLOW, (
            f"Tube 1 half {i} expected yellow (inconclusive), got '{bg}'"
        )


def test_detected_tubes_show_results_summary(page, base_url):
    """Summary text should not say 'Run for results!' when results are loaded."""
    _set_results_path(base_url, "detected.json")
    _reload_results(page, base_url)
    summary = page.locator("#results-summary")
    text = summary.inner_text().strip()
    assert "Run for results" not in text, (
        f"Summary still shows 'Run for results!' after loading results: '{text}'"
    )

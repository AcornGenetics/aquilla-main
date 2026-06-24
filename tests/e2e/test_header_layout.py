"""
E2E layout regression tests for the kiosk header at 768px (issue #167).

The kiosk display is 768px wide, so the `@media (max-width: 820px)` layout
always applies on the device. Adding the Settings nav link widened the nav; on
title-heavy pages ("Saved Profiles", "Edit Run Profile") that pushed the nav
onto a second row, doubling the header height and shoving the table down. The
dev-only optics field on the Run page did the same in simulation mode.

These tests assert the header stays a single row at kiosk width — i.e. the nav
does not wrap below the title — which contract tests can't see (pure layout).

Run with: pytest -m e2e tests/e2e/test_header_layout.py
"""
import pytest

pytestmark = pytest.mark.e2e

# Titles wide enough to compete with the nav at 768px.
TITLE_HEAVY_ROUTES = ["/profiles-page", "/profiles/edit", "/history/run", "/history"]


def _goto(page, base_url, route):
    page.set_viewport_size({"width": 768, "height": 1024})
    try:
        page.goto(f"{base_url}{route}", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    page.wait_for_load_state("networkidle")


def _header_metrics(page):
    return page.evaluate(
        """() => {
            const h = document.querySelector('.run-header');
            if (!h) return null;
            const t = h.querySelector('.run-header__title');
            const n = h.querySelector('.run-header__nav');
            if (!t || !n) return null;
            const hr = h.getBoundingClientRect();
            const tr = t.getBoundingClientRect();
            const nr = n.getBoundingClientRect();
            return {headerH: hr.height, titleTop: tr.top, navTop: nr.top};
        }"""
    )


@pytest.mark.parametrize("route", TITLE_HEAVY_ROUTES)
def test_header_stays_single_row_at_kiosk_width(page, base_url, route):
    """At 768px the nav must sit beside the title, not wrap to a second row."""
    _goto(page, base_url, route)
    m = _header_metrics(page)
    if m is None:
        pytest.skip(f"{route} renders no .run-header")
    assert m["navTop"] <= m["titleTop"] + 10, (
        f"{route}: nav wrapped below the title at 768px "
        f"(titleTop={m['titleTop']:.0f}, navTop={m['navTop']:.0f}, "
        f"headerH={m['headerH']:.0f}) — header grew to two rows"
    )


def test_run_page_header_single_row_with_dev_optics(page, base_url):
    """The dev-only optics field must not push the nav to a second row at 768px."""
    _goto(page, base_url, "/run")
    # Force the dev-only optics field visible, as in AQ_DEV_SIMULATE mode.
    page.eval_on_selector_all(
        "#run-optics-tab", "els => els.forEach(e => e.classList.remove('is-hidden'))"
    )
    page.wait_for_timeout(50)
    m = _header_metrics(page)
    assert m is not None, "/run renders no .run-header"
    assert m["navTop"] <= m["titleTop"] + 10, (
        f"/run with dev optics visible: nav wrapped below the title at 768px "
        f"(titleTop={m['titleTop']:.0f}, navTop={m['navTop']:.0f}, "
        f"headerH={m['headerH']:.0f})"
    )

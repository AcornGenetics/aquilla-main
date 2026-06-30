"""
Contract tests for the Settings nav item and the Help reorganization (issue #167).

These exercise the highest existing seam — the FastAPI TestClient (`client`
fixture) plus direct reads of served static files — mirroring the style of
tests/contract/test_wifi_endpoints.py.

Run with:
    pytest tests/contract/test_settings_nav.py -m contract -v
"""
import pytest
from pathlib import Path


STATIC = Path("aquila_web/static")

# Live, route-reachable nav-bearing pages.
# Note: ready.html exists and carries the nav, but no /ready route serves it
# (script.js references it but the app returns 404), so it is not testable here.
NAV_ROUTES = [
    "/run",
    "/history",
    "/history/run",
    "/profiles-page",
    "/profiles/edit",
    "/complete",
    "/help",
]


# ---------------------------------------------------------------------------
# Slice 1 — /settings route exists
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_settings_page_returns_200(client):
    """GET /settings serves the Settings HTML page."""
    response = client.get("/settings")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# Slice 2 — Settings renders both sub-pages as tabs
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_settings_renders_both_subtabs(client):
    """Settings has Wi-Fi & System and Updates sub-pages, shown as pill-tabs."""
    html = client.get("/settings").text
    # Both sub-tab labels present
    assert "Wi-Fi &amp; System" in html or "Wi-Fi & System" in html
    assert "Updates" in html
    # Rendered with the shared pill-tab pattern (same as Help)
    assert "help-tab" in html
    assert "help-section" in html


# ---------------------------------------------------------------------------
# Slice 3 — Settings Wi-Fi is the richer UI (ADR-012): Forget + Saved Connections
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_settings_wifi_has_forget_and_saved_connections(client):
    """Settings adopts the richer Wi-Fi UI: Forget action + Saved Connections."""
    html = client.get("/settings").text
    assert "Saved Connections" in html
    assert "doForget" in html or "Forget" in html
    assert "/wifi/forget" in html
    assert "/wifi/saved" in html


@pytest.mark.contract
def test_settings_wifi_preserves_original_ssid_in_dom_dataset():
    """Connect/forget must use the original SSID from the dataset, not labels/IDs."""
    html = (STATIC / "settings.html").read_text()
    assert "form.dataset.ssid" in html
    assert '.textContent.replace("Connect to ", "")' not in html


# ---------------------------------------------------------------------------
# Slice 4 — Nav order: Run | History | Profiles | Settings | ?
# ---------------------------------------------------------------------------

def _nav_positions(html):
    """Return (profiles_idx, settings_idx, help_idx) of the nav links."""
    return (
        html.find('href="/profiles-page'),
        html.find('href="/settings"'),
        html.find('href="/help"'),
    )

@pytest.mark.contract
def test_run_page_nav_has_settings_between_profiles_and_help(client):
    """The Run screen nav reads Run | History | Profiles | Settings | ?."""
    html = client.get("/run").text
    profiles_idx, settings_idx, help_idx = _nav_positions(html)
    assert profiles_idx != -1 and settings_idx != -1 and help_idx != -1
    assert profiles_idx < settings_idx < help_idx


# ---------------------------------------------------------------------------
# Slice 5 — Settings link present and ordered on every live nav page
# ---------------------------------------------------------------------------

@pytest.mark.contract
@pytest.mark.parametrize("route", NAV_ROUTES)
def test_settings_link_on_every_nav_page(client, route):
    """Every live nav-bearing page shows Settings between Profiles and ?."""
    html = client.get(route).text
    profiles_idx, settings_idx, help_idx = _nav_positions(html)
    assert settings_idx != -1, f"{route} is missing the Settings nav link"
    assert profiles_idx != -1 and help_idx != -1
    assert profiles_idx < settings_idx < help_idx


# ---------------------------------------------------------------------------
# Slice 6 — Update badge rides the Settings link, not the ? (help) link
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_update_badge_targets_settings_link_not_help():
    """nav.js paints the update-available badge on the Settings nav link."""
    navjs = (STATIC / "nav.js").read_text()
    # Badge is attached to the Settings link
    assert "settings-link" in navjs
    # Badge no longer queries the help (?) link for placement
    assert 'querySelectorAll("a.help-link")' not in navjs
    assert 'querySelectorAll(".help-link")' not in navjs


# ---------------------------------------------------------------------------
# Slice 7 — /wifi redirects to /settings (Wi-Fi UI consolidated there)
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_wifi_redirects_to_settings(client):
    """The old standalone /wifi page now redirects to /settings."""
    response = client.get("/wifi", follow_redirects=False)
    assert response.status_code in (301, 302, 307, 308)
    assert response.headers["location"] == "/settings"


# ---------------------------------------------------------------------------
# Slice 8 — Help no longer hosts the functional Wi-Fi / Updates controls
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_help_has_no_functional_wifi_or_update_controls(client):
    """Help is informational only; the live Wi-Fi/Updates logic moved to Settings."""
    html = client.get("/help").text
    # Functional Wi-Fi markers gone
    assert "wifiDoScan" not in html
    assert "/wifi/scan" not in html
    assert "wifi-rescan-btn-inline" not in html
    # Functional Updates markers gone
    assert "openUpdateTab" not in html
    assert "/update/apply" not in html
    assert "update-now-btn" not in html


# ---------------------------------------------------------------------------
# Slice 9 — Help gains informational Wi-Fi Setup and Updates how-to pages
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_help_has_new_howto_pages(client):
    """Help offers informational 'Wi-Fi Setup' and 'Updates' how-to pages."""
    html = client.get("/help").text
    assert "Wi-Fi Setup" in html
    assert "tab-wifi-howto" in html
    assert "tab-updates-howto" in html
    # They direct the user to the Settings screen
    assert "Settings" in html


# ---------------------------------------------------------------------------
# Slice 10 — Existing Help pages are unchanged (regression guard)
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_help_keeps_existing_pages(client):
    """Run / History / Profiles / Run Detail help pages remain."""
    html = client.get("/help").text
    for target in ("tab-run", "tab-history", "tab-profiles", "tab-detail"):
        assert target in html, f"Help lost its {target} page"
    assert "Run Detail" in html
    assert "Starting a Run" in html


# ---------------------------------------------------------------------------
# Slice 11 — Settings nav must not push the header taller (layout regression)
# ---------------------------------------------------------------------------
#
# The wider nav (extra Settings link) squeezed the no-wrap flex header, wrapping
# multi-word titles like "Saved Profiles" onto two lines, growing the header
# height and shoving the table down. The base .run-header__title rule must pin
# the title to a single line so the header height stays constant.

import re


def _base_title_rule(css):
    """Return the body of the top-level `.run-header__title { ... }` rule.

    Excludes the responsive `@media` override (which is nested and only
    restates font-size).
    """
    match = re.search(r"\n\.run-header__title\s*\{([^}]*)\}", css)
    assert match, "styles.css lost its base .run-header__title rule"
    return match.group(1)


@pytest.mark.contract
def test_header_title_does_not_wrap():
    """The title stays on one line so the wider nav can't grow header height."""
    css = (STATIC / "styles.css").read_text()
    rule = _base_title_rule(css)
    assert "white-space: nowrap" in rule, (
        "run-header__title must set white-space: nowrap so multi-word titles "
        "(e.g. 'Saved Profiles') don't wrap when the nav widens"
    )


# ---------------------------------------------------------------------------
# Slice 12 — OTA update badge needs a positioned ancestor on the Settings link
# ---------------------------------------------------------------------------
#
# .help-badge is position:absolute (top/right:-4px). nav.js appends it to
# a.settings-link, so the badge needs a positioned ancestor there or it anchors
# to the viewport and floats the red "1" into the screen corner. The Settings
# link (.settings-link, a .run-nav-link) must establish a positioning context.

def _rule_body(css, selector):
    """Return the body of the top-level `selector { ... }` rule, or None."""
    match = re.search(r"\n" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return match.group(1) if match else None


@pytest.mark.contract
def test_update_badge_has_positioned_ancestor_on_settings_link():
    """The Settings link must be position:relative so the badge anchors to it."""
    css = (STATIC / "styles.css").read_text()
    # The badge is positioned relative to its nearest positioned ancestor; for
    # the Settings tab that must be .settings-link itself or the shared
    # .run-nav-link rule.
    candidates = [_rule_body(css, ".settings-link"), _rule_body(css, ".run-nav-link")]
    assert any(
        body and "position: relative" in body for body in candidates
    ), (
        "the OTA badge appended to a.settings-link has no positioned ancestor; "
        "add position: relative to .settings-link (or .run-nav-link) so the "
        "badge anchors to the Settings tab instead of the viewport corner"
    )


# ===========================================================================
# Suite — defensive coverage for the new Settings-nav + OTA-badge wiring.
#
# The two visual bugs we hit (header height growth, badge in the viewport
# corner) shared a root cause: a cross-file contract (HTML class <-> nav.js
# selector <-> CSS rule) that no test enforced. These slices lock those
# contracts down so a future markup/JS/CSS rename can't silently break the
# Settings tab or its update badge. NB: true pixel layout (overflow, wrapping
# under a real viewport) can't be asserted from a TestClient — those remain
# manual/visual checks; here we pin the structural invariants behind them.
# ===========================================================================

# Live, route-reachable nav pages and their backing static files.
# (profiles.html, ready.html, login.html are NOT live nav pages: the first two
# have no route, login carries no nav.)
LIVE_NAV_ROUTES = NAV_ROUTES + ["/settings"]
LIVE_NAV_PAGE_FILES = [
    "run.html",
    "history.html",
    "history_detail.html",
    "profiles/index.html",
    "profiles/edit_form.html",
    "profiles/builder.html",
    "complete.html",
    "help.html",
    "settings.html",
]


def _navjs_badge_class():
    """The class nav.js assigns to the update-badge element it creates."""
    navjs = (STATIC / "nav.js").read_text()
    match = re.search(r"\.className\s*=\s*[\"']([^\"']+)[\"']", navjs)
    assert match, "nav.js no longer sets a className on the update badge element"
    return match.group(1)


def _navjs_badge_target_class():
    """The anchor class nav.js queries to host the update badge."""
    navjs = (STATIC / "nav.js").read_text()
    match = re.search(r'querySelectorAll\(\s*[\"\']a\.([A-Za-z0-9_-]+)[\"\']', navjs)
    assert match, "nav.js no longer queries an anchor class for the update badge"
    return match.group(1)


# ---------------------------------------------------------------------------
# Slice 13 — the badge class nav.js creates is actually styled & positioned
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_update_badge_class_is_styled_and_absolutely_positioned():
    """nav.js's badge class must map to a CSS rule that positions it as a dot.

    Guards against a rename drift where nav.js creates e.g. .update-badge but
    CSS only styles .help-badge, leaving a bare unstyled '1' in the layout.
    """
    badge_class = _navjs_badge_class()
    css = (STATIC / "styles.css").read_text()
    body = _rule_body(css, "." + badge_class)
    assert body is not None, (
        f"nav.js creates <span class='{badge_class}'> but styles.css has no "
        f".{badge_class} rule; the badge would render unstyled"
    )
    assert "position: absolute" in body, (
        f".{badge_class} must be position:absolute to sit on the tab corner"
    )


# ---------------------------------------------------------------------------
# Slice 14 — badge insertion is idempotent (no stacking duplicate dots)
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_update_badge_insertion_is_idempotent():
    """nav.js must check for an existing badge (same class) before appending."""
    navjs = (STATIC / "nav.js").read_text()
    badge_class = _navjs_badge_class()
    assert f'querySelector(".{badge_class}")' in navjs, (
        "nav.js appends the update badge without first checking for an existing "
        f".{badge_class}; re-running checkUpdateBadge would stack duplicate dots"
    )


# ---------------------------------------------------------------------------
# Slice 15 — the nav.js selector matches the served Settings link element
# ---------------------------------------------------------------------------

@pytest.mark.contract
@pytest.mark.parametrize("route", LIVE_NAV_ROUTES)
def test_navjs_badge_target_present_as_anchor(client, route):
    """Every live nav page renders an <a> carrying the class nav.js queries.

    If the HTML class and the nav.js selector drift apart, querySelectorAll
    returns nothing and the badge silently never appears.
    """
    target = _navjs_badge_target_class()  # e.g. "settings-link"
    html = client.get(route).text
    assert re.search(rf'<a[^>]*class="[^"]*\b{re.escape(target)}\b', html), (
        f"{route}: nav.js targets a.{target} for the badge, but no anchor on "
        f"the page carries that class"
    )


# ---------------------------------------------------------------------------
# Slice 16 — every live nav page actually loads nav.js
# ---------------------------------------------------------------------------

@pytest.mark.contract
@pytest.mark.parametrize("route", LIVE_NAV_ROUTES)
def test_nav_pages_load_navjs(client, route):
    """The badge logic only runs if the page includes nav.js."""
    html = client.get(route).text
    assert "nav.js" in html, (
        f"{route} renders the nav but never loads nav.js, so the update badge "
        f"can never appear there"
    )


# ---------------------------------------------------------------------------
# Slice 17 — exactly one Settings link per page (one badge anchor)
# ---------------------------------------------------------------------------

@pytest.mark.contract
@pytest.mark.parametrize("route", LIVE_NAV_ROUTES)
def test_single_settings_link_per_page(client, route):
    """Duplicate settings-link anchors would each receive their own badge."""
    target = _navjs_badge_target_class()
    html = client.get(route).text
    count = len(re.findall(rf'class="[^"]*\b{re.escape(target)}\b', html))
    assert count == 1, (
        f"{route} has {count} '{target}' anchors; expected exactly one so the "
        f"badge has a single, unambiguous home"
    )


# ---------------------------------------------------------------------------
# Slice 18 — shared stylesheet cache-buster is uniform across live pages
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_stylesheet_cache_buster_is_uniform_across_live_pages():
    """All live pages must pin the same styles.css?v=N.

    They share one stylesheet, so a divergent ?v= means some pages render with
    stale cached CSS — exactly how a CSS fix can ship yet not take effect.
    """
    versions = {}
    for rel in LIVE_NAV_PAGE_FILES:
        text = (STATIC / rel).read_text()
        match = re.search(r"styles\.css\?v=(\d+)", text)
        assert match, f"{rel} does not version-pin styles.css"
        versions[rel] = match.group(1)
    unique = sorted(set(versions.values()))
    assert len(unique) == 1, (
        f"live nav pages disagree on the styles.css cache-buster {unique}; some "
        f"will load stale CSS. Per-page versions: {versions}"
    )

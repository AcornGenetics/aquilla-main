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

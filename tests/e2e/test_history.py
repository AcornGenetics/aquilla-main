"""
E2E tests for the Run History page of the Aquila PCR kiosk UI.
Requires a running backend at base_url (default http://localhost:8090).
Run with: pytest -m e2e tests/e2e/test_history.py
"""
import httpx
import pytest

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _goto_history(page, base_url):
    try:
        page.goto(f"{base_url}/history", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    page.wait_for_load_state("domcontentloaded")


def _clear_history(base_url: str) -> None:
    try:
        httpx.post(f"{base_url}/history/clear", timeout=5).raise_for_status()
    except Exception as exc:
        pytest.skip(f"Could not clear history: {exc}")


def _append_history(base_url: str, **kwargs) -> None:
    payload = {
        "run_name": "Test Run",
        "profile": "BasicPCR",
        "results_path": None,
        "graph_path": None,
    }
    payload.update(kwargs)
    try:
        httpx.post(f"{base_url}/history/append", json=payload, timeout=5).raise_for_status()
    except Exception as exc:
        pytest.skip(f"Could not append history entry: {exc}")


# ---------------------------------------------------------------------------
# Page load
# ---------------------------------------------------------------------------

def test_history_page_loads(page, base_url):
    _goto_history(page, base_url)
    assert "Run History" in page.title() or page.locator("h1").inner_text()


def test_history_page_has_table(page, base_url):
    _goto_history(page, base_url)
    table = page.locator(".profiles-table")
    assert table.count() >= 1, "History table not found"
    assert table.is_visible()


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

def test_empty_state_shows_no_runs_yet(page, base_url):
    _clear_history(base_url)
    _goto_history(page, base_url)
    page.wait_for_function(
        "() => document.getElementById('history-table-body')?.childElementCount > 0"
        " || document.getElementById('history-table-body')?.textContent.trim() !== ''",
        timeout=5_000,
    )
    body_text = page.locator("#history-table-body").inner_text()
    assert "No runs yet" in body_text, (
        f"Expected 'No runs yet' for empty history, got: '{body_text}'"
    )


# ---------------------------------------------------------------------------
# Entry appears after append
# ---------------------------------------------------------------------------

def test_history_entry_appears_after_append(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="Alpha Run", profile="BasicPCR")
    _goto_history(page, base_url)
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#history-table-body tr td'))"
        "     .some(td => td.textContent.includes('Alpha Run'))",
        timeout=5_000,
    )
    body = page.locator("#history-table-body")
    assert "Alpha Run" in body.inner_text(), "Run name not found in history table"


def test_history_entry_shows_timestamp(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="Timestamp Run")
    _goto_history(page, base_url)
    page.wait_for_function(
        "() => document.querySelectorAll('#history-table-body tr').length > 0",
        timeout=5_000,
    )
    # The timestamp column contains a date-like string (YYYY-MM-DD)
    body_text = page.locator("#history-table-body").inner_text()
    import re
    assert re.search(r"\d{4}-\d{2}-\d{2}", body_text), (
        f"No date-like timestamp found in history body: '{body_text}'"
    )


def test_history_entry_shows_profile(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="Profile Run", profile="MyProfile")
    _goto_history(page, base_url)
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#history-table-body tr td'))"
        "     .some(td => td.textContent.includes('MyProfile'))",
        timeout=5_000,
    )
    body_text = page.locator("#history-table-body").inner_text()
    assert "MyProfile" in body_text, "Profile name not found in history table"


def test_view_link_present_when_graph_path_set(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="Graph Run", graph_path="/static/some_graph.png")
    _goto_history(page, base_url)
    page.wait_for_function(
        "() => document.querySelector('a.history-graph-link') !== null",
        timeout=5_000,
    )
    link = page.locator("a.history-graph-link")
    assert link.count() >= 1, "'View' graph link not found"
    assert link.first.is_visible()
    assert link.first.inner_text().strip() == "View"


def test_no_view_link_when_no_graph_path(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="No Graph Run", graph_path=None)
    _goto_history(page, base_url)
    page.wait_for_function(
        "() => document.querySelectorAll('#history-table-body tr').length > 0"
        " && !document.getElementById('history-table-body').textContent.includes('No runs yet')",
        timeout=5_000,
    )
    link = page.locator("a.history-graph-link")
    assert link.count() == 0, "Graph link should not be present when graph_path is None"


# ---------------------------------------------------------------------------
# Select-all checkbox
# ---------------------------------------------------------------------------

def test_select_all_checkbox_selects_all_rows(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="Row 1")
    _append_history(base_url, run_name="Row 2")
    _goto_history(page, base_url)
    page.wait_for_function(
        "() => document.querySelectorAll('.history-checkbox').length >= 2",
        timeout=5_000,
    )
    page.locator("#history-select-all-checkbox").check()
    checkboxes = page.locator(".history-checkbox")
    for i in range(checkboxes.count()):
        assert checkboxes.nth(i).is_checked(), f"Row {i} checkbox not checked after select-all"


# ---------------------------------------------------------------------------
# Delete behaviour
# ---------------------------------------------------------------------------

def test_delete_with_nothing_selected_does_nothing(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="Keep Me")
    _goto_history(page, base_url)
    page.wait_for_function(
        "() => document.querySelectorAll('#history-table-body tr').length > 0",
        timeout=5_000,
    )
    # Click delete without selecting anything – no dialog should appear, row stays
    page.locator("#history-clear").click()
    page.wait_for_timeout(500)
    body_text = page.locator("#history-table-body").inner_text()
    assert "Keep Me" in body_text, "Entry was removed even though nothing was selected"


def test_delete_with_confirmation_removes_entry(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="Delete Me")
    _goto_history(page, base_url)
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#history-table-body tr td'))"
        "     .some(td => td.textContent.includes('Delete Me'))",
        timeout=5_000,
    )
    # Accept the confirm() dialog
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(".history-checkbox").first.check()
    page.locator("#history-clear").click()
    # Wait for the row to disappear or for "No runs yet" to appear
    page.wait_for_function(
        "() => !Array.from(document.querySelectorAll('#history-table-body tr td'))"
        "     .some(td => td.textContent.includes('Delete Me'))",
        timeout=5_000,
    )
    body_text = page.locator("#history-table-body").inner_text()
    assert "Delete Me" not in body_text, "Entry still present after confirmed delete"

"""
E2E tests for the Legacy Profile read-only view (issue #211, Structured Profiles B4).

The Legacy viewer is the existing `edit_form.html` / `edit.js`, which B3 (#203)
routes Legacy Profiles to via `?view=1`. B4 locks it (no Edit View toggle), adds a
summary header (name/FAM/ROX/estimate), aligns the step layout, and removes the
flash of the editable editor before read-only applies.

Requires a running backend at base_url (default http://localhost:8090; override
with AQUILA_TEST_URL). Run with: pytest -m e2e tests/e2e/test_legacy_view.py
"""
from urllib.parse import quote

import pytest

pytestmark = pytest.mark.e2e


def _seed_legacy(page, base_url, name, **fields):
    """Create a Legacy Profile (no `stages`) and return its id."""
    body = {"name": name, "steps": [{"setpoint": 95, "duration": 30}], **fields}
    resp = page.request.post(f"{base_url}/profiles", data=body)
    assert resp.status == 200, resp.text()
    return resp.json()["id"]


def _delete(page, base_url, pid):
    page.request.post(f"{base_url}/profiles/delete", data={"profiles": [pid]})


def _goto(page, base_url, path):
    try:
        page.goto(f"{base_url}{path}", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    page.wait_for_load_state("networkidle")


def _view_url(pid, view=True):
    return f"/profiles/edit-form?id={quote(pid)}" + ("&view=1" if view else "")


def test_read_view_hides_edit_toggle_edit_mode_shows_it(page, base_url):
    """Read-only entry hides the Edit View toggle (no escape to editing); normal
    edit entry keeps it."""
    pid = _seed_legacy(page, base_url, "B4 Lock")
    try:
        _goto(page, base_url, _view_url(pid, view=True))
        assert not page.locator("#toggle-read-view").is_visible(), (
            "Edit View toggle must be hidden in the read-only view"
        )

        _goto(page, base_url, _view_url(pid, view=False))
        assert page.locator("#toggle-read-view").is_visible(), (
            "toggle stays available in normal edit mode"
        )
    finally:
        _delete(page, base_url, pid)


def test_summary_header_shows_name_labels_and_estimate(page, base_url):
    """The read view's summary header shows the profile name, FAM/ROX labels and
    the estimated minutes when one is set."""
    pid = _seed_legacy(
        page, base_url, "B4 Header",
        fam_label="MyFAM", rox_label="MyROX", estimated_minutes=42,
    )
    try:
        _goto(page, base_url, _view_url(pid, view=True))
        meta = page.locator("#profile-summary-meta")
        page.wait_for_selector("#profile-summary-meta", state="attached", timeout=5_000)
        text = meta.inner_text()
        assert "B4 Header" in text
        assert "MyFAM" in text
        assert "MyROX" in text
        assert "42" in text  # estimated minutes
    finally:
        _delete(page, base_url, pid)


def test_summary_header_omits_estimate_when_unset(page, base_url):
    """With no estimate set, the summary header has no estimated-minutes row."""
    pid = _seed_legacy(page, base_url, "B4 NoEst", fam_label="FAM", rox_label="ROX")
    try:
        _goto(page, base_url, _view_url(pid, view=True))
        page.wait_for_selector("#profile-summary-meta", state="attached", timeout=5_000)
        text = page.locator("#profile-summary-meta").inner_text()
        assert "B4 NoEst" in text
        assert "Est. Time" not in text and "Estimated" not in text
    finally:
        _delete(page, base_url, pid)


def test_summary_step_rows_share_one_column_layout(page, base_url):
    """Step rows align: every row uses the same column tracks regardless of how
    many fields it has (no field-count zig-zag)."""
    pid = _seed_legacy(
        page, base_url, "B4 Align",
        steps=[
            {"setpoint": 95, "duration": 30, "description": "Hold"},  # 5 fields
            {"ramp_rate": 1.6},                                        # 3 fields
            {"enable": 0, "duration": 1},                              # 4 fields
        ],
    )
    try:
        _goto(page, base_url, _view_url(pid, view=True))
        page.wait_for_selector(".profile-summary-step", state="attached", timeout=5_000)
        cols = page.eval_on_selector_all(
            ".profile-summary-step",
            "els => els.map(e => getComputedStyle(e).gridTemplateColumns)",
        )
        assert len(cols) >= 2, f"need multiple step rows, got {len(cols)}"
        # Aligned == every row has the same number of grid tracks regardless of
        # field count (auto-fit gave 5/3/4; fixed columns give the same count).
        # Exact px can differ by sub-pixel fr rounding, so compare track counts.
        track_counts = [len(c.split()) for c in cols]
        assert len(set(track_counts)) == 1, f"rows must share track count, got {track_counts}"
    finally:
        _delete(page, base_url, pid)


def test_no_flash_read_only_applied_before_paint(page, base_url):
    """`?view=1` gets the pre-paint `view-only` class on <html> (so the editable
    sections never paint); a normal edit load does not."""
    pid = _seed_legacy(page, base_url, "B4 Flash")
    try:
        _goto(page, base_url, _view_url(pid, view=True))
        assert "view-only" in (page.eval_on_selector("html", "el => el.className") or ""), (
            "read-only view must set html.view-only before paint"
        )
        assert page.locator(".profile-edit").first.is_visible() is False, (
            "editable sections must not show in the read-only view"
        )

        _goto(page, base_url, _view_url(pid, view=False))
        assert "view-only" not in (page.eval_on_selector("html", "el => el.className") or ""), (
            "edit mode must not be view-only"
        )
        assert page.locator("#profile-edit-details").is_visible(), (
            "edit mode shows the editable sections"
        )
    finally:
        _delete(page, base_url, pid)

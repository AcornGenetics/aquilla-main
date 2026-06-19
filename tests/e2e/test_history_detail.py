"""
E2E tests for the Run Detail page (/history/run?index=N) of the Sentri PCR kiosk UI.
Requires a running backend at base_url (default http://localhost:8090).
Run with: pytest -m e2e tests/e2e/test_history_detail.py
"""
import pathlib

import httpx
import pytest

pytestmark = pytest.mark.e2e

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "results"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_history(base_url: str) -> None:
    try:
        httpx.post(f"{base_url}/history/clear", timeout=5).raise_for_status()
    except Exception as exc:
        pytest.skip(f"Could not clear history: {exc}")


def _append_history(base_url: str, **kwargs) -> None:
    payload = {
        "run_name": "Detail Test Run",
        "profile": "BasicPCR",
        "results_path": None,
        "graph_path": None,
    }
    payload.update(kwargs)
    try:
        httpx.post(f"{base_url}/history/append", json=payload, timeout=5).raise_for_status()
    except Exception as exc:
        pytest.skip(f"Could not append history entry: {exc}")


def _goto_detail(page, base_url, index: int = 0):
    try:
        page.goto(f"{base_url}/history/run?index={index}", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    page.wait_for_load_state("domcontentloaded")


def _wait_for_detail(page, timeout: int = 6_000):
    """Wait until history_detail.js has finished rendering into #run-detail."""
    page.wait_for_function(
        "() => {"
        "  const el = document.getElementById('run-detail');"
        "  return el && el.textContent.trim() !== '';"
        "}",
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Basic page load
# ---------------------------------------------------------------------------

def test_detail_page_loads_for_valid_index(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="Load Test")
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    assert page.locator("#run-detail").count() == 1, "#run-detail container not found"


def test_detail_page_shows_run_not_found_for_invalid_index(page, base_url):
    _clear_history(base_url)
    _goto_detail(page, base_url, index=999)
    _wait_for_detail(page)
    text = page.locator("#run-detail").inner_text().strip()
    assert "Run not found" in text, (
        f"Expected 'Run not found' for index 999, got: '{text}'"
    )


# ---------------------------------------------------------------------------
# Run Information section
# ---------------------------------------------------------------------------

def test_run_information_section_visible(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="Info Test")
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    header = page.locator(".run-detail-card__header", has_text="Run Information")
    assert header.count() >= 1, "'Run Information' section header not found"
    assert header.first.is_visible()


def test_run_information_shows_run_name(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="My Unique Run Name")
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    text = page.locator("#run-detail").inner_text()
    assert "My Unique Run Name" in text, "Run name not found in detail page"


def test_run_information_shows_profile(page, base_url):
    _clear_history(base_url)
    _append_history(base_url, run_name="Prof Test", profile="MyDetailProfile")
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    text = page.locator("#run-detail").inner_text()
    assert "MyDetailProfile" in text, "Profile name not found in detail page"


# ---------------------------------------------------------------------------
# Per-tube pills
# ---------------------------------------------------------------------------

def _seed_with_detected(base_url: str) -> None:
    """Seed history with a detected.json results path so pills render with statuses."""
    _clear_history(base_url)
    fixture_path = str((FIXTURES_DIR / "detected.json").resolve())
    _append_history(
        base_url,
        run_name="Detected Run",
        profile="BasicPCR",
        results_path=fixture_path,
        graph_path="/static/dummy_graph.png",
    )


def _seed_with_inconclusive(base_url: str) -> None:
    _clear_history(base_url)
    fixture_path = str((FIXTURES_DIR / "inconclusive.json").resolve())
    _append_history(
        base_url,
        run_name="Inconclusive Run",
        profile="BasicPCR",
        results_path=fixture_path,
    )


def test_per_tube_pills_rendered(page, base_url):
    _seed_with_detected(base_url)
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    pills = page.locator(".run-detail-pill")
    assert pills.count() == 4, f"Expected 4 per-tube pills, found {pills.count()}"


def test_detected_pill_has_correct_class(page, base_url):
    """Tube 1 is Detected in detected.json – its pill should have run-detail-pill--detected."""
    _seed_with_detected(base_url)
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    detected_pills = page.locator(".run-detail-pill--detected")
    assert detected_pills.count() >= 1, (
        "No pill with class 'run-detail-pill--detected' found; "
        "check that detected.json is being served correctly"
    )


def test_not_detected_pill_has_correct_class(page, base_url):
    """Tubes 2-4 are Not Detected in detected.json → pills should carry --not-detected."""
    _seed_with_detected(base_url)
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    nd_pills = page.locator(".run-detail-pill--not-detected")
    assert nd_pills.count() >= 1, (
        "No pill with class 'run-detail-pill--not-detected' found"
    )


def test_inconclusive_pill_has_correct_class(page, base_url):
    """Tube 1 is Inconclusive in inconclusive.json → pill should have --inconclusive."""
    _seed_with_inconclusive(base_url)
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    inc_pills = page.locator(".run-detail-pill--inconclusive")
    assert inc_pills.count() >= 1, (
        "No pill with class 'run-detail-pill--inconclusive' found"
    )


# ---------------------------------------------------------------------------
# KPI section
# ---------------------------------------------------------------------------

def test_kpi_section_shows_detected_count(page, base_url):
    _seed_with_detected(base_url)
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    kpi_labels = page.locator(".run-detail-kpi__label")
    labels_text = [kpi_labels.nth(i).inner_text().strip() for i in range(kpi_labels.count())]
    assert "Detected" in labels_text, f"'Detected' KPI label not found; labels: {labels_text}"


def test_kpi_section_shows_inconclusive_count(page, base_url):
    _seed_with_detected(base_url)
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    kpi_labels = page.locator(".run-detail-kpi__label")
    labels_text = [kpi_labels.nth(i).inner_text().strip() for i in range(kpi_labels.count())]
    assert "Inconclusive" in labels_text, (
        f"'Inconclusive' KPI label not found; labels: {labels_text}"
    )


# ---------------------------------------------------------------------------
# QC Status
# ---------------------------------------------------------------------------

def test_qc_status_pass_when_no_inconclusive(page, base_url):
    """detected.json has no inconclusive results → QC Status should be 'Pass'."""
    _seed_with_detected(base_url)
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    # The QC value element carries run-detail-kpi__value--pass or --review
    qc_value = page.locator(".run-detail-kpi__value--pass")
    assert qc_value.count() >= 1, (
        "Expected QC Status 'Pass' (.run-detail-kpi__value--pass) not found"
    )
    assert "Pass" in qc_value.first.inner_text(), (
        f"QC value element text: '{qc_value.first.inner_text()}'"
    )


def test_qc_status_review_when_inconclusive_present(page, base_url):
    """inconclusive.json has inconclusive tube → QC Status should be 'Review'."""
    _seed_with_inconclusive(base_url)
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    qc_value = page.locator(".run-detail-kpi__value--review")
    assert qc_value.count() >= 1, (
        "Expected QC Status 'Review' (.run-detail-kpi__value--review) not found"
    )
    assert "Review" in qc_value.first.inner_text(), (
        f"QC value element text: '{qc_value.first.inner_text()}'"
    )


# ---------------------------------------------------------------------------
# Graph / Amplification Curves section
# ---------------------------------------------------------------------------

def test_amplification_curves_section_visible(page, base_url):
    _seed_with_detected(base_url)
    _goto_detail(page, base_url, index=0)
    _wait_for_detail(page)
    header = page.locator(".run-detail-card__header", has_text="Amplification Curves")
    assert header.count() >= 1, "'Amplification Curves' section header not found"
    assert header.first.is_visible()

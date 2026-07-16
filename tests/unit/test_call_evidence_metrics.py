"""
Unit tests for call_evidence Metric/Check emission (#298).

Refactored engine: each Check returns ``(passed, rows)`` — the value it computed —
so ``evaluate_curve`` emits the full Metric/Check detail with NO recomputation. The
decision logic (the cascade) is unchanged; the regression suite (which asserts the
Calls) proves that separately.

Behaviors:
  1. summarize_call_evidence attaches each curve's metrics to its record.
  2. evaluate_curve emits Check verdicts + Metric values + shared pure measures.
  3. a curve that FAILS a Check still logs that Check's number (the key fix vs. the
     old _run_check-swallows-to-False loss).
  4. results_to_json threads the metrics into the evidence records.
"""
import numpy as np
import pytest

from aq_curve import evaluator
from aq_curve.evaluator import evaluate_curve
from aq_curve.curve import Curve, summarize_call_evidence

pytestmark = pytest.mark.unit


def _sigmoid():
    xdata = np.arange(1, 41)
    y = 100.0 / (1.0 + np.exp(-(xdata - 20) / 2.0))
    y_corrected = y - y[:10].mean()
    return (xdata, y_corrected, y_corrected + 60.0)


def test_summarize_attaches_metrics_per_record():
    fam = {1: "Detected"}
    rox = {1: "Detected"}
    metrics_by_curve = {
        ("fam", 1): [{"name": "cq", "value": 22.5, "threshold": None, "passed": None}],
        ("rox", 1): [{"name": "cq", "value": 24.0, "threshold": None, "passed": None}],
    }

    evidence = summarize_call_evidence(
        fam, rox, dict(rox), rox_unavailable=False, metrics_by_curve=metrics_by_curve
    )

    fam_rec = next(r for r in evidence if r["channel"] == "fam")
    assert fam_rec["metrics"] == metrics_by_curve[("fam", 1)]


def test_evaluate_curve_emits_checks_values_and_pure_measures(monkeypatch):
    monkeypatch.setattr(evaluator, "get_curve_data", lambda *a: _sigmoid())

    ev = evaluate_curve(Curve(), "log", "fam", 1)
    by_name = {m["name"]: m for m in ev["metrics"]}

    # shared pure measures (emitted once, value-only)
    for name in ("cq", "threshold", "n_cycles", "signal_range"):
        assert name in by_name
        assert by_name[name]["passed"] is None

    # a Check verdict is a passed-only row
    assert by_name["check_baseline_stability"]["value"] is None
    assert by_name["check_baseline_stability"]["passed"] in (True, False)

    # a composite Check's underlying Metrics are their own value+threshold+passed rows
    for name in ("baseline_std", "baseline_slope"):
        assert by_name[name]["value"] is not None
        assert by_name[name]["threshold"] is not None
        assert by_name[name]["passed"] in (True, False)


def test_evaluate_curve_emits_baseline_rfu_as_pure_measure(monkeypatch):
    # baseline_rfu (the raw baseline floor) feeds the upstream Baseline Increase
    # metric. It is a pure measure -- a number, with no per-curve pass/fail (the
    # 10%/20% banding lives in the acorn-analytics view, not on the device).
    monkeypatch.setattr(evaluator, "get_curve_data", lambda *a: _sigmoid())

    ev = evaluate_curve(Curve(), "log", "fam", 1)
    by_name = {m["name"]: m for m in ev["metrics"]}

    assert "baseline_rfu" in by_name
    assert by_name["baseline_rfu"]["threshold"] is None
    assert by_name["baseline_rfu"]["passed"] is None


def test_baseline_rfu_reports_the_raw_floor_not_the_corrected_baseline(monkeypatch):
    # The raw curve sits on a 500-count floor; baseline correction flattens that
    # region to ~0. baseline_rfu must report the RAW floor (the drift signal),
    # NOT the corrected ~0 -- otherwise the upstream % -increase metric never moves.
    xdata = np.arange(1, 41)
    sig = 100.0 / (1.0 + np.exp(-(xdata - 20) / 2.0))
    y_corrected = sig - sig[5:15].mean()          # baseline slice (5,15) -> mean 0
    floor = 500.0
    y_raw = y_corrected + floor
    monkeypatch.setattr(evaluator, "get_curve_data", lambda *a: (xdata, y_corrected, y_raw))

    ev = evaluate_curve(Curve(), "log", "fam", 1)
    by_name = {m["name"]: m for m in ev["metrics"]}

    # Curve default baseline_slice = (5, 15); value is the mean raw fluorescence there.
    assert by_name["baseline_rfu"]["value"] == pytest.approx(float(np.mean(y_raw[5:15])))
    # And it clearly reflects the raw floor (~500), not the corrected ~0.
    assert by_name["baseline_rfu"]["value"] == pytest.approx(floor, abs=1.0)


def test_failing_curve_still_logs_its_check_values(monkeypatch):
    # Pure noise, no amplification -> Checks fail, but the numbers are still computed
    # (baseline std/slope are computed before the pass/fail).
    xdata = np.arange(1, 41)
    y_corrected = np.random.RandomState(0).normal(0.0, 40.0, 40)
    monkeypatch.setattr(evaluator, "get_curve_data", lambda *a: (xdata, y_corrected, y_corrected + 60.0))

    ev = evaluate_curve(Curve(), "log", "fam", 1)
    by_name = {m["name"]: m for m in ev["metrics"]}

    assert by_name["baseline_std"]["value"] is not None
    assert by_name["baseline_slope"]["value"] is not None


def test_empty_curve_emits_zero_signal_range_without_crashing(monkeypatch):
    # A well/channel with no signal (ROX Unavailable, or an aborted/truncated read)
    # yields an empty corrected curve. The metric emission must not call np.max on it
    # and sink the whole Run's results -- an empty curve has no range, so 0.0.
    monkeypatch.setattr(
        evaluator, "get_curve_data",
        lambda *a: (np.array([]), np.array([]), np.array([])),
    )

    ev = evaluate_curve(Curve(), "log", "rox", 1)
    by_name = {m["name"]: m for m in ev["metrics"]}

    assert by_name["signal_range"]["value"] == 0.0
    assert by_name["n_cycles"]["value"] == 0.0
    # baseline_rfu over an empty raw curve is UNKNOWN, not 0: emit None (like cq).
    # A 0 would pool into the upstream all-time-median reference and drag it to 0,
    # NULLing out the increase for every real run on the device (#319 follow-up).
    assert by_name["baseline_rfu"]["value"] is None
    assert by_name["cq"]["value"] is None


def test_results_to_json_evidence_records_carry_the_metrics(tmp_path, monkeypatch):
    import json
    from aq_curve import curve as curve_module

    metrics = [
        {"name": "check_baseline_stability", "value": None, "threshold": None, "passed": True},
        {"name": "cq", "value": 22.5, "threshold": None, "passed": None},
        {"name": "baseline_std", "value": 3.1, "threshold": 5.0, "passed": True},
    ]
    monkeypatch.setattr(
        curve_module, "evaluate_curve",
        lambda self, src, dye, well: {"status": "detected", "metrics": metrics},
    )
    monkeypatch.setattr(curve_module, "get_curve_data", lambda self, src, dye, well: _sigmoid())

    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())

    fam1 = next(r for r in data["evidence"] if r["well"] == 1 and r["channel"] == "fam")
    names = {m["name"] for m in fam1["metrics"]}
    assert {"check_baseline_stability", "cq", "baseline_std"} <= names

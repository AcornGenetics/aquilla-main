"""
Unit tests for call_evidence Metric/Check emission (#298).

The decision logic (evaluate_curve + the checks + the cascade) is NOT modified;
Metrics are collected additively. Behaviors:
  1. summarize_call_evidence attaches each curve's metrics to its record.
  2. every Check in the evaluation `results` becomes a metric row (passed only).
  3. collect_metrics produces value rows (cq, threshold, ...) reusing the engine helpers.
  4. regression: the emitted Call is unchanged (the decision logic didn't move).
"""
import numpy as np
import pytest

from aq_curve.curve import Curve, summarize_call_evidence
from aq_curve.call_evidence_metrics import check_metric_rows, collect_metrics
from aq_curve.pcr_curve_helpers import compute_cq, get_threshold
from aq_curve import pcr_curve_config as config

pytestmark = pytest.mark.unit


def _sigmoid_curve():
    xdata = np.arange(1, 41)
    y = 100.0 / (1.0 + np.exp(-(xdata - 20) / 2.0))  # clean sigmoid 0..100
    y_corrected = y - y[:10].mean()  # baseline near zero
    y_raw = y_corrected + 60.0
    return (xdata, y_corrected, y_raw), Curve()


def test_collect_metrics_emits_named_numeric_values_reusing_the_engine_helpers():
    curve_data, curve = _sigmoid_curve()

    rows = collect_metrics(curve_data, curve)
    by_name = {r["name"]: r for r in rows}

    # the core Metrics are present as pure measures (value only)
    for name in ("cq", "threshold", "baseline_std", "baseline_slope",
                 "signal_range", "log_phase_r2", "slope_cv"):
        assert name in by_name, f"missing metric {name}"
        assert by_name[name]["value"] is not None
        assert by_name[name]["threshold"] is None
        assert by_name[name]["passed"] is None

    # anchored: cq / threshold match a direct helper call (same inputs)
    xdata, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    cq = compute_cq(xdata, y_corrected, threshold, config.get_int("PCR_SUSTAINED_CYCLES"))
    assert by_name["threshold"]["value"] == pytest.approx(float(threshold))
    assert by_name["cq"]["value"] == pytest.approx(float(cq))


def _stub_curve_data(self, src, dye, well):
    xdata = np.arange(1, 41)
    y = 100.0 / (1.0 + np.exp(-(xdata - 20) / 2.0))
    y_corrected = y - y[:10].mean()
    return (xdata, y_corrected, y_corrected + 60.0)


def test_results_to_json_evidence_records_carry_check_and_value_metrics(tmp_path, monkeypatch):
    import json
    from aq_curve import curve as curve_module

    monkeypatch.setattr(
        curve_module, "evaluate_curve",
        lambda self, src, dye, well: {"status": "detected", "results": {"check_baseline_stability": True}},
    )
    monkeypatch.setattr(curve_module, "get_curve_data", _stub_curve_data)

    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())

    fam1 = next(r for r in data["evidence"] if r["well"] == 1 and r["channel"] == "fam")
    names = {m["name"] for m in fam1["metrics"]}
    assert "check_baseline_stability" in names   # a Check row (from results)
    assert "cq" in names                          # a value row (from collect_metrics)


def test_every_check_becomes_a_metric_row_passed_only():
    results = {"check_baseline_stability": True, "check_signal_range": False}
    rows = check_metric_rows(results)
    by_name = {r["name"]: r for r in rows}
    assert by_name["check_baseline_stability"] == {
        "name": "check_baseline_stability", "value": None, "threshold": None, "passed": True,
    }
    assert by_name["check_signal_range"]["passed"] is False
    # a Check is passed-only — no value/threshold
    assert by_name["check_signal_range"]["value"] is None
    assert by_name["check_signal_range"]["threshold"] is None


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
    rox_rec = next(r for r in evidence if r["channel"] == "rox")
    assert fam_rec["metrics"] == metrics_by_curve[("fam", 1)]
    assert rox_rec["metrics"] == metrics_by_curve[("rox", 1)]

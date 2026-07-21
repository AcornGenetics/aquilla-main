"""
Unit tests for call_evidence derived flags + Decision Reason (#299).

evaluate_curve additively exposes the derived decision flags and the Decision Reason
(the cascade branch that produced the status) it already computes. The cascade logic
is unchanged; the regression suite (which asserts the Calls) proves that separately.
"""
import numpy as np
import pytest

from aq_curve import evaluator
from aq_curve.evaluator import evaluate_curve
from aq_curve.curve import Curve, summarize_call_evidence

pytestmark = pytest.mark.unit

FLAG_KEYS = {
    "threshold_pass", "spike_only_crossings", "test_run", "typical_pass",
    "biphasic_pass", "baseline_fail", "mountain_shape_detected",
    "rapid_rise_detected", "late_ok", "late_confident", "signal_range_pass",
    "cq_after_hard_max",
}


def _sigmoid():
    xdata = np.arange(1, 41)
    y = 100.0 / (1.0 + np.exp(-(xdata - 20) / 2.0))
    y_corrected = y - y[:10].mean()
    return (xdata, y_corrected, y_corrected + 60.0)


def test_evaluate_curve_returns_decision_reason_and_flags(monkeypatch):
    monkeypatch.setattr(evaluator, "get_curve_data", lambda *a: _sigmoid())

    ev = evaluate_curve(Curve(), "log", "fam", 1)

    assert isinstance(ev["decision_reason"], str) and ev["decision_reason"]
    assert set(ev["flags"]) == FLAG_KEYS
    assert all(isinstance(v, bool) for v in ev["flags"].values())


def test_decision_reason_names_the_branch_taken(monkeypatch):
    # This sigmoid rises through the baseline window, so it fails baseline checks and
    # lands on the else branch -> Inconclusive / both_paths_failed. The Decision Reason
    # names exactly that branch (and the derived flag agrees) — emitted, not inferred.
    monkeypatch.setattr(evaluator, "get_curve_data", lambda *a: _sigmoid())

    ev = evaluate_curve(Curve(), "log", "fam", 1)

    assert ev["status"] == "inconclusive"
    assert ev["decision_reason"] == "both_paths_failed"
    assert ev["flags"]["baseline_fail"] is True
    assert ev["flags"]["typical_pass"] is False


def test_no_signal_curve_is_not_detected_with_a_closed_set_reason(monkeypatch):
    # Flat noise: never Detected, and the reason is a member of the closed set.
    xdata = np.arange(1, 41)
    y_corrected = np.random.RandomState(1).normal(0.0, 5.0, 40)
    monkeypatch.setattr(evaluator, "get_curve_data", lambda *a: (xdata, y_corrected, y_corrected + 60.0))

    ev = evaluate_curve(Curve(), "log", "fam", 1)

    assert ev["status"] in ("undetected", "inconclusive")
    assert ev["decision_reason"] in {
        "threshold_fail", "signal_range_fail", "mountain_shape", "rapid_rise",
        "no_cq_no_increase", "late_cq_not_confident", "both_paths_failed", "test_run",
    }


def test_summary_record_carries_flags_and_decision_reason():
    fam = {1: "Detected"}
    rox = {1: "Detected"}
    decision_by_curve = {
        ("fam", 1): {"decision_reason": "typical_or_biphasic_pass", "flags": {"typical_pass": True}},
    }

    evidence = summarize_call_evidence(
        fam, rox, dict(rox), rox_unavailable=False, decision_by_curve=decision_by_curve
    )

    fam_rec = next(r for r in evidence if r["channel"] == "fam")
    assert fam_rec["decision_reason"] == "typical_or_biphasic_pass"
    assert fam_rec["flags"] == {"typical_pass": True}


def test_results_to_json_evidence_carries_decision_reason_and_flags(tmp_path, monkeypatch):
    import json
    from aq_curve import curve as curve_module

    ev_ret = {
        "status": "detected", "metrics": [],
        "decision_reason": "typical_or_biphasic_pass", "flags": {"typical_pass": True},
    }
    monkeypatch.setattr(curve_module, "evaluate_curve", lambda self, src, dye, well: ev_ret)
    monkeypatch.setattr(curve_module, "get_curve_data", lambda self, src, dye, well: _sigmoid())

    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())

    fam1 = next(r for r in data["evidence"] if r["well"] == 1 and r["channel"] == "fam")
    assert fam1["decision_reason"] == "typical_or_biphasic_pass"
    assert fam1["flags"]["typical_pass"] is True

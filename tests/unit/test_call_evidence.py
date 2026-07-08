"""
Unit tests for the summary call_evidence derivation (#297).

Behaviors tested (pure logic — no hardware, no optics logs):
  1. canonical_call maps the engine's "undetected" -> "Not Detected" (ADR-017)
     and never lets "undetected" escape.
  2. summarize_call_evidence emits one record per evaluated Call, with
     raw_status == call for fam (no suppression runs on fam).
  3. A ROX-suppressed Call shows a divergent raw_status ("Detected") vs
     call ("Not Detected").
  4. A ROX-Unavailable Run emits fam records only — no rox record, and never a
     record whose call is "ROX Unavailable".
"""
import pytest

from aq_curve.curve import canonical_call, summarize_call_evidence

pytestmark = pytest.mark.unit


class TestCanonicalCall:
    def test_undetected_maps_to_not_detected(self):
        # ADR-017: the engine's "undetected" must never be emitted.
        assert canonical_call("undetected") == "Not Detected"

    def test_detected_and_inconclusive_map_to_canonical(self):
        assert canonical_call("detected") == "Detected"
        assert canonical_call("inconclusive") == "Inconclusive"

    def test_already_canonical_values_pass_through(self):
        # Idempotent: safe to apply to values that are already canonical.
        assert canonical_call("Not Detected") == "Not Detected"
        assert canonical_call("ROX Unavailable") == "ROX Unavailable"


class TestSummarizeCallEvidence:
    def test_one_record_per_evaluated_call(self):
        fam = {1: "Detected", 2: "Not Detected", 3: "Inconclusive", 4: "Not Detected"}
        rox = {1: "Detected", 2: "Not Detected", 3: "Not Detected", 4: "Not Detected"}
        evidence = summarize_call_evidence(fam, rox, dict(rox), rox_unavailable=False)
        # 4 fam + 4 rox curves were evaluated -> 8 summary records.
        assert len(evidence) == 8
        assert {(r["well"], r["channel"]) for r in evidence} == {
            (w, ch) for ch in ("fam", "rox") for w in (1, 2, 3, 4)
        }
        # Never emit the engine's internal "undetected".
        assert all(r["raw_status"] != "undetected" for r in evidence)
        assert all(r["call"] != "undetected" for r in evidence)

    def test_fam_raw_status_equals_call(self):
        # No suppression runs on fam, so raw_status and call always agree.
        fam = {1: "Detected", 2: "Inconclusive", 3: "Not Detected", 4: "Not Detected"}
        rox = {1: "Not Detected", 2: "Not Detected", 3: "Not Detected", 4: "Not Detected"}
        evidence = summarize_call_evidence(fam, rox, dict(rox), rox_unavailable=False)
        fam_records = [r for r in evidence if r["channel"] == "fam"]
        assert all(r["raw_status"] == r["call"] for r in fam_records)
        assert {r["well"]: r["call"] for r in fam_records} == fam

    def test_rox_suppressed_call_diverges_from_raw_status(self):
        # ROX suppression fired on well 1: the curve evaluated as Detected but the
        # final call became Not Detected. Both must be captured.
        fam = {1: "Not Detected", 2: "Not Detected", 3: "Not Detected", 4: "Not Detected"}
        rox_raw = {1: "Detected", 2: "Not Detected", 3: "Not Detected", 4: "Not Detected"}
        rox_final = {1: "Not Detected", 2: "Not Detected", 3: "Not Detected", 4: "Not Detected"}
        evidence = summarize_call_evidence(fam, rox_final, rox_raw, rox_unavailable=False)
        rox1 = next(r for r in evidence if r["channel"] == "rox" and r["well"] == 1)
        assert rox1["raw_status"] == "Detected"
        assert rox1["call"] == "Not Detected"
        # An untouched rox curve keeps raw_status == call.
        rox2 = next(r for r in evidence if r["channel"] == "rox" and r["well"] == 2)
        assert rox2["raw_status"] == rox2["call"] == "Not Detected"

    def test_rox_unavailable_emits_no_rox_record(self):
        fam = {1: "Detected", 2: "Not Detected", 3: "Not Detected", 4: "Not Detected"}
        rox = {1: "ROX Unavailable", 2: "ROX Unavailable", 3: "ROX Unavailable", 4: "ROX Unavailable"}
        evidence = summarize_call_evidence(fam, rox, dict(rox), rox_unavailable=True)
        assert {r["channel"] for r in evidence} == {"fam"}
        assert len(evidence) == 4
        # The ROX-Unavailable sentinel must never appear as a call.
        assert all(r["call"] != "ROX Unavailable" for r in evidence)

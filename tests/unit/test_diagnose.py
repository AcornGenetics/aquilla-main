"""
Unit tests for diagnose.py — study-session orchestrator (issue #163).

Pure logic (consolidate_verdict, format_verdict, _watch_cmd); the tmux/subprocess
I/O layer is on-device only. Imported via sys.path like the sibling test files.
"""
import sys
from collections import namedtuple
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))

import diagnose as d  # noqa: E402

# Minimal stand-ins that mirror the real namedtuples from the sibling scripts.
_Verdict = namedtuple("_Verdict", ["code", "label", "evidence"])
_CancelReport = namedtuple("_CancelReport", ["timestamp", "verdict", "coincidence_delta", "last_app_line"])
_Flag = namedtuple("_Flag", ["metric", "hypothesis", "direction", "series"])


def _report(code):
    return _CancelReport(None, _Verdict(code, code, []), None, None)


def _flag(hypothesis):
    return _Flag("metric", hypothesis, "up", [1.0, 2.0])


# ---------------------------------------------------------------------------
# Slice 1 — tracer bullet: empty session yields Outcome D
# ---------------------------------------------------------------------------

class TestConsolidateVerdictOutcomeD:
    def test_no_cancels_no_flags_is_outcome_d(self):
        v = d.consolidate_verdict([], [])
        assert v.code == "H0"
        assert v.outcome == "D"


# ---------------------------------------------------------------------------
# Slice 2 — single H1 cancel → culprit H1
# ---------------------------------------------------------------------------

class TestConsolidateVerdictH1:
    def test_h1_cancel_reports_h1(self):
        v = d.consolidate_verdict([_report("H1")], [])
        assert v.code == "H1"
        assert v.outcome == "culprit"


# ---------------------------------------------------------------------------
# Slice 3 — single H3 cancel → culprit H3
# ---------------------------------------------------------------------------

class TestConsolidateVerdictH3:
    def test_h3_cancel_reports_h3(self):
        v = d.consolidate_verdict([_report("H3")], [])
        assert v.code == "H3"
        assert v.outcome == "culprit"


# ---------------------------------------------------------------------------
# Slice 4 — TRIGGER2 + H4 resource flag → culprit H4
# ---------------------------------------------------------------------------

class TestConsolidateVerdictTrigger2Narrowed:
    def test_trigger2_plus_h4_flag_is_h4(self):
        v = d.consolidate_verdict([_report("TRIGGER2")], [_flag("H4")])
        assert v.code == "H4"
        assert v.outcome == "culprit"

    def test_trigger2_plus_h5_flag_is_h5(self):
        v = d.consolidate_verdict([_report("TRIGGER2")], [_flag("H5")])
        assert v.code == "H5"
        assert v.outcome == "culprit"

    def test_trigger2_plus_h6_flag_is_h6(self):
        v = d.consolidate_verdict([_report("TRIGGER2")], [_flag("H6")])
        assert v.code == "H6"
        assert v.outcome == "culprit"

    def test_trigger2_plus_h2_flag_is_h2(self):
        v = d.consolidate_verdict([_report("TRIGGER2")], [_flag("H2")])
        assert v.code == "H2"
        assert v.outcome == "culprit"

    def test_trigger2_no_flags_is_outcome_d(self):
        v = d.consolidate_verdict([_report("TRIGGER2")], [])
        assert v.code == "H0"
        assert v.outcome == "D"


# ---------------------------------------------------------------------------
# Slice 5 — H1 beats TRIGGER2 in priority
# ---------------------------------------------------------------------------

class TestConsolidateVerdictPriority:
    def test_h1_beats_trigger2(self):
        v = d.consolidate_verdict([_report("H1"), _report("TRIGGER2")], [_flag("H4")])
        assert v.code == "H1"

    def test_h3_beats_trigger2(self):
        v = d.consolidate_verdict([_report("H3"), _report("TRIGGER2")], [_flag("H5")])
        assert v.code == "H3"

    def test_trigger2_beats_h8(self):
        v = d.consolidate_verdict([_report("TRIGGER2"), _report("H8")], [_flag("H6")])
        assert v.code == "H6"


# ---------------------------------------------------------------------------
# Slice 6 — H8 cancel with no TRIGGER2
# ---------------------------------------------------------------------------

class TestConsolidateVerdictH8:
    def test_h8_cancel_reports_h8(self):
        v = d.consolidate_verdict([_report("H8")], [])
        assert v.code == "H8"
        assert v.outcome == "culprit"


# ---------------------------------------------------------------------------
# Slice 7 — evidence included in verdict
# ---------------------------------------------------------------------------

class TestConsolidateVerdictEvidence:
    def test_evidence_is_non_empty_for_named_culprit(self):
        v = d.consolidate_verdict([_report("H1")], [])
        assert len(v.evidence) > 0

    def test_outcome_d_mentions_next_steps(self):
        v = d.consolidate_verdict([], [])
        # evidence should guide operator rather than be empty
        assert len(v.evidence) > 0


# ---------------------------------------------------------------------------
# Slice 8 — format_verdict renders key phrases
# ---------------------------------------------------------------------------

class TestFormatVerdict:
    def test_outcome_d_says_unknown(self):
        v = d.consolidate_verdict([], [])
        text = d.format_verdict(v)
        assert "unknown" in text.lower() or "outcome d" in text.lower()

    def test_culprit_shows_code(self):
        v = d.consolidate_verdict([_report("H1")], [])
        text = d.format_verdict(v)
        assert "H1" in text

    def test_format_includes_evidence(self):
        v = d.consolidate_verdict([_report("H3")], [])
        text = d.format_verdict(v)
        assert v.evidence[0] in text


# ---------------------------------------------------------------------------
# Slice 9 — _watch_cmd builds correct argv
# ---------------------------------------------------------------------------

class TestWatchCmd:
    def test_required_args_present(self):
        cmd = d._watch_cmd("/logs/logger.log", "/logs/app.log")
        assert "--logger" in cmd
        assert "/logs/logger.log" in cmd
        assert "--app" in cmd
        assert "/logs/app.log" in cmd

    def test_no_lid_arg_when_absent(self):
        cmd = d._watch_cmd("/logs/logger.log", "/logs/app.log")
        assert "--lid" not in cmd

    def test_lid_arg_when_provided(self):
        cmd = d._watch_cmd("/logs/logger.log", "/logs/app.log", lid="/logs/lid.log")
        assert "--lid" in cmd
        assert "/logs/lid.log" in cmd

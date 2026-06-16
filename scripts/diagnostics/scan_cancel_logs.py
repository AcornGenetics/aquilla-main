#!/usr/bin/env python3
"""Scan controller + web-app logs and classify each SENTRI self-cancel.

Part of the self-cancellation study. Stdlib-only, pure logic — runs anywhere.
See specs/analysis/scan-cancel-logs.md.
"""
import argparse
import re
import sys
from collections import Counter, namedtuple
from datetime import datetime, timedelta

_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})")

Verdict = namedtuple("Verdict", ["code", "label", "evidence"])

_LIVE = re.compile(r"live=(\d+)")


def _has(lines, substr):
    return any(substr in line for line in lines)


def _max_live(lid_lines):
    """Highest concurrent lid-worker count seen in the lid log (0 if none)."""
    counts = [int(m.group(1)) for line in lid_lines for m in [_LIVE.search(line)] if m]
    return max(counts) if counts else 0


def parse_timestamp(line):
    """Parse the leading 'YYYY-MM-DD HH:MM:SS,mmm'; None if absent."""
    m = _TS.match(line)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")


def find_cancels(logger_lines):
    """Indices of self-cancel events (the canonical 'Stop request detected')."""
    return [i for i, line in enumerate(logger_lines) if "Stop request detected" in line]


def classify_window(logger_lines, app_lines, lid_lines=None):
    """Classify one cancel's window against the study fingerprints (§3)."""
    app_lines = app_lines or []
    evidence = []

    if _has(app_lines, "Stop button pressed"):
        evidence.append("'Stop button pressed' in app log with no human tap")
        return Verdict("H3", "Trigger 1 — phantom touch / frontend re-fire", evidence)

    peak = _max_live(lid_lines or [])
    if peak > 1:
        evidence.append("lid workers live peaked at %d (leak)" % peak)
        return Verdict("H1", "Threading — lid-heater thread leak", evidence)

    if _has(logger_lines, "Backend unreachable") and not _has(app_lines, "Stop button pressed"):
        evidence.append("forced-stop safety net fired with no 'Stop button pressed'")
        return Verdict("TRIGGER2", "Safety net — web app unreachable (H2/H4/H5/H6)", evidence)

    if _has(logger_lines, "Stop request detected"):
        evidence.append("cancel fired with no press, safety net, leak, or restart")
        return Verdict("H8", "Trigger 1 — stale stop flag / failed reset", evidence)

    return Verdict("H0", "Unknown — no fingerprint matched", evidence)


def coincidence_delta(app_lines, cancel_ts):
    """Seconds the web app was silent before the cancel.

    The gap between the last app-log line at/before ``cancel_ts`` and the cancel.
    A large gap means the web app went quiet right as the controller gave up.
    None if no timestamped app line precedes the cancel.
    """
    befores = [
        ts for line in app_lines
        for ts in [parse_timestamp(line)]
        if ts is not None and ts <= cancel_ts
    ]
    if not befores:
        return None
    return (cancel_ts - max(befores)).total_seconds()


CancelReport = namedtuple(
    "CancelReport", ["timestamp", "verdict", "coincidence_delta", "last_app_line"]
)


def _read_lines(path):
    if not path:
        return []
    try:
        with open(path, errors="replace") as fh:
            return fh.readlines()
    except FileNotFoundError:
        return []


def _window(lines, center_ts, window_s):
    """Timestamped lines within +/- window_s of center_ts."""
    lo = center_ts - timedelta(seconds=window_s)
    hi = center_ts + timedelta(seconds=window_s)
    out = []
    for line in lines:
        ts = parse_timestamp(line)
        if ts is not None and lo <= ts <= hi:
            out.append(line)
    return out


def scan(logger_path, app_path, lid_path=None, window=30):
    """Read the logs, classify each self-cancel, return CancelReports."""
    logger_lines = _read_lines(logger_path)
    app_lines = _read_lines(app_path)
    lid_lines = _read_lines(lid_path)

    reports = []
    for idx in find_cancels(logger_lines):
        cancel_ts = parse_timestamp(logger_lines[idx])
        if cancel_ts is None:
            continue
        log_win = _window(logger_lines, cancel_ts, window)
        app_win = _window(app_lines, cancel_ts, window)
        lid_win = _window(lid_lines, cancel_ts, window) if lid_lines else []
        verdict = classify_window(log_win, app_win, lid_lines=lid_win)
        delta = coincidence_delta(app_lines, cancel_ts)
        last_app = next(
            (l.rstrip("\n") for l in reversed(app_lines)
             if (parse_timestamp(l) or cancel_ts) <= cancel_ts and parse_timestamp(l)),
            None,
        )
        reports.append(CancelReport(cancel_ts, verdict, delta, last_app))
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description="Classify SENTRI self-cancels from logs.")
    parser.add_argument("--logger", required=True, help="path to logger.log (controller)")
    parser.add_argument("--app", required=True, help="path to app_logger.log (web app)")
    parser.add_argument("--lid", default=None, help="path to lid_heater_logger.log (optional)")
    parser.add_argument("--window", type=int, default=30, help="seconds around each cancel")
    args = parser.parse_args(argv)

    reports = scan(args.logger, args.app, args.lid, args.window)
    if not reports:
        print("No self-cancels detected.")
        return 0
    if not args.lid:
        print("(note: --lid not provided; H1 lid-thread-leak detection disabled)\n")

    for r in reports:
        print("=" * 70)
        print("Cancel at %s" % r.timestamp)
        print("  Verdict : %s — %s" % (r.verdict.code, r.verdict.label))
        for ev in r.verdict.evidence:
            print("    - %s" % ev)
        if r.coincidence_delta is not None:
            print("  Web app silent for %.1fs before the cancel" % r.coincidence_delta)
        if r.last_app_line:
            print("  Last app line before cancel: %s" % r.last_app_line)

    print("=" * 70)
    tally = Counter(r.verdict.code for r in reports)
    summary = ", ".join("%dx %s" % (n, code) for code, n in tally.most_common())
    print("Summary: %d cancel(s): %s" % (len(reports), summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())

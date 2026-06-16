#!/usr/bin/env python3
"""Study-session orchestrator for the SENTRI self-cancel investigation.

One command runs the whole session: live tmux monitor alongside the control
pane, baseline + per-run resource snapshots, post-hoc log scan, and a single
consolidated verdict. Stdlib-only. See GitHub issue #163.
"""
from collections import namedtuple

# ---------------------------------------------------------------------------
# Pure logic — unit-testable
# ---------------------------------------------------------------------------

FinalVerdict = namedtuple("FinalVerdict", ["code", "label", "outcome", "evidence"])

_LABELS = {
    "H0":       "Outcome D — cause still unknown",
    "H1":       "Threading — lid-heater thread leak",
    "H2":       "Trigger 2 — event-loop / button-latency block (H2)",
    "H3":       "Trigger 1 — phantom touch / frontend re-fire (H3)",
    "H4":       "Trigger 2 — SoC thermal throttle (H4)",
    "H5":       "Trigger 2 — FD/socket leak (H5)",
    "H6":       "Trigger 2 — controller/app memory growth (H6)",
    "H7":       "Trigger 1 — web app restarted mid-run (H7)",
    "H8":       "Trigger 1 — stale stop flag / failed reset (H8)",
    "TRIGGER2": "Trigger 2 — safety net fired (H2/H4/H5/H6, unresolved)",
}

# Resource hypothesis codes that narrow TRIGGER2, in disambiguation priority.
_TRIGGER2_NARROW = ["H4", "H5", "H6", "H2"]

_OUTCOME_D_STEPS = (
    "add --lid to capture lid_heater_logger.log and detect H1 leaks",
    "run multiple consecutive runs so snapshot_resources.py can trend metrics",
    "check dmesg for OOM kills that might explain web-app silence",
)


def consolidate_verdict(cancel_reports, resource_flags):
    """Map all signals → most-likely culprit per the §8 decision matrix.

    Priority: H1 > H3 > H7 > TRIGGER2 (→ narrow via resource flags) > H8 > H0.
    """
    codes = {r.verdict.code for r in cancel_reports}
    flag_hypotheses = {f.hypothesis for f in resource_flags}

    for code in ("H1", "H3", "H7"):
        if code in codes:
            return FinalVerdict(
                code=code,
                label=_LABELS[code],
                outcome="culprit",
                evidence=["cancel classified as %s in log scan" % code],
            )

    if "TRIGGER2" in codes:
        for hyp in _TRIGGER2_NARROW:
            if hyp in flag_hypotheses:
                matching = [f for f in resource_flags if f.hypothesis == hyp]
                ev = ["TRIGGER2 cancel + resource metric '%s' trending %s → %s" % (
                    f.metric, f.direction, hyp) for f in matching]
                return FinalVerdict(code=hyp, label=_LABELS[hyp], outcome="culprit", evidence=ev)
        # TRIGGER2 but no resource flags to narrow it
        return FinalVerdict(
            code="H0",
            label=_LABELS["H0"],
            outcome="D",
            evidence=list(_OUTCOME_D_STEPS),
        )

    if "H8" in codes:
        return FinalVerdict(
            code="H8",
            label=_LABELS["H8"],
            outcome="culprit",
            evidence=["cancel classified as H8 (stale stop flag) in log scan"],
        )

    # No actionable signal
    return FinalVerdict(
        code="H0",
        label=_LABELS["H0"],
        outcome="D",
        evidence=list(_OUTCOME_D_STEPS),
    )


def format_verdict(verdict):
    """Render the final verdict as a printable string."""
    lines = [
        "=" * 70,
        "VERDICT: %s — %s" % (verdict.code, verdict.label),
        "Outcome: %s" % verdict.outcome,
        "",
    ]
    if verdict.evidence:
        lines.append("Evidence / next steps:")
        for ev in verdict.evidence:
            lines.append("  • %s" % ev)
    lines.append("=" * 70)
    return "\n".join(lines)


def _watch_cmd(logger, app, lid=None):
    """Build the subprocess argv for watch_cancel.py."""
    import sys
    import os
    script = os.path.join(os.path.dirname(__file__), "watch_cancel.py")
    cmd = [sys.executable, script, "--logger", logger, "--app", app]
    if lid is not None:
        cmd += ["--lid", lid]
    return cmd


# ---------------------------------------------------------------------------
# I/O glue — not unit-tested (on-device / tmux)
# ---------------------------------------------------------------------------

import argparse  # noqa: E402
import os        # noqa: E402
import shutil    # noqa: E402
import subprocess  # noqa: E402
import sys        # noqa: E402
import time       # noqa: E402

_DEFAULT_OUT = "diagnostics_out"
_DEFAULT_CSV = os.path.join(_DEFAULT_OUT, "snapshots.csv")


def _have_tmux():
    return shutil.which("tmux") is not None


def _launch_tmux(session, logger, app, lid):
    """Create a tmux session; right pane runs watch_cancel.py live."""
    watch = _watch_cmd(logger, app, lid)
    watch_str = " ".join(watch)
    subprocess.call(["tmux", "new-session", "-d", "-s", session, "-x", "220", "-y", "50"])
    subprocess.call(["tmux", "split-window", "-h", "-t", session])
    subprocess.call(["tmux", "send-keys", "-t", "%s:0.1" % session, watch_str, "Enter"])
    subprocess.call(["tmux", "select-pane", "-t", "%s:0.0" % session])
    print("tmux session '%s' started. Attach with: tmux attach -t %s" % (session, session))
    print("Right pane is running watch_cancel.py live.\n")


def _inline_watch(logger, app, lid):
    """Fallback: run watch_cancel.py as a tagged subprocess in the same stream."""
    print("(tmux not available — running watch_cancel.py inline; install tmux for split-pane)")
    cmd = _watch_cmd(logger, app, lid)
    return subprocess.Popen(cmd)


def _import_sibling(name):
    """Import a sibling script from the same directory."""
    import importlib.util
    here = os.path.dirname(__file__)
    spec = importlib.util.spec_from_file_location(name, os.path.join(here, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _take_snapshot(label, csv_path, backend_pid, app_pid, app_url):
    sr = _import_sibling("snapshot_resources")
    os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
    row = sr.collect(label, backend_pid, app_pid, app_url)
    sr.write_snapshot(csv_path, row)
    print("Snapshot '%s' recorded." % label)


def _run_scan(logger, app, lid, window):
    scl = _import_sibling("scan_cancel_logs")
    return scl.scan(logger, app, lid, window)


def _read_snapshots(csv_path):
    sr = _import_sibling("snapshot_resources")
    return sr.read_snapshots(csv_path), sr.analyze(sr.read_snapshots(csv_path))


def _collect_bundle(out_dir, logger, app, lid, csv_path, verdict_text):
    """Bundle logs + snapshots + verdict into out_dir/bundle/."""
    bundle = os.path.join(out_dir, "bundle")
    os.makedirs(bundle, exist_ok=True)
    for src in [logger, app, lid, csv_path]:
        if src and os.path.exists(src):
            shutil.copy2(src, bundle)
    verdict_file = os.path.join(bundle, "verdict.txt")
    with open(verdict_file, "w") as fh:
        fh.write(verdict_text + "\n")
    archive = shutil.make_archive(bundle, "zip", bundle)
    shutil.rmtree(bundle)
    print("Bundle written to %s" % archive)
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="SENTRI self-cancel study orchestrator — runs the full session end-to-end."
    )
    parser.add_argument("--logger", required=True, help="controller logger.log path")
    parser.add_argument("--app", required=True, help="web-app app_logger.log path")
    parser.add_argument("--lid", default=None, help="lid_heater_logger.log (optional)")
    parser.add_argument("--backend-pid", default=None, help="controller PID for resource snapshots")
    parser.add_argument("--app-pid", default=None, help="web-app PID for resource snapshots")
    parser.add_argument("--app-url", default="http://127.0.0.1:8090", help="web-app base URL")
    parser.add_argument("--out", default=_DEFAULT_OUT, help="output directory")
    parser.add_argument("--csv", default=_DEFAULT_CSV, help="snapshot CSV path")
    parser.add_argument("--window", type=int, default=30, help="log window (seconds) around each cancel")
    parser.add_argument("--collect", action="store_true", help="bundle logs+snapshots+verdict for offline handoff")
    parser.add_argument("--session", default="sentri-diagnose", help="tmux session name")
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)

    # 1. Live monitor
    inline_proc = None
    if _have_tmux():
        _launch_tmux(args.session, args.logger, args.app, args.lid)
    else:
        inline_proc = _inline_watch(args.logger, args.app, args.lid)

    # 2. Baseline snapshot
    print("\nTaking baseline snapshot...")
    _take_snapshot("baseline", args.csv, args.backend_pid, args.app_pid, args.app_url)

    # 3. Operator loop
    run_num = 0
    print("\nReproduce the bug: press Enter after each run, type 'done' when finished.\n")
    try:
        while True:
            raw = input("After run (or 'done'): ").strip().lower()
            if raw == "done":
                break
            run_num += 1
            _take_snapshot("after-run-%d" % run_num, args.csv, args.backend_pid, args.app_pid, args.app_url)
    except (KeyboardInterrupt, EOFError):
        print("\nSession stopped.")
    finally:
        if inline_proc is not None:
            inline_proc.terminate()
        if _have_tmux():
            subprocess.call(["tmux", "kill-session", "-t", args.session], stderr=subprocess.DEVNULL)

    # 4. Batch analysis
    print("\n--- Batch analysis ---\n")
    cancel_reports = _run_scan(args.logger, args.app, args.lid, args.window)
    if not cancel_reports:
        print("No self-cancels found in logs.\n")
    else:
        for r in cancel_reports:
            print("Cancel at %s → %s (%s)" % (r.timestamp, r.verdict.code, r.verdict.label))

    rows, resource_flags = _read_snapshots(args.csv)
    sr = _import_sibling("snapshot_resources")
    print("\n" + sr.report(rows) + "\n")

    # 5. Consolidated verdict
    verdict = consolidate_verdict(cancel_reports, resource_flags)
    verdict_text = format_verdict(verdict)
    print(verdict_text)

    # 6. Optional collect bundle
    if args.collect:
        _collect_bundle(args.out, args.logger, args.app, args.lid, args.csv, verdict_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())

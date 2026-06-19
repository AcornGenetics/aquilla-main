#!/usr/bin/env python3
"""Per-run host/process resource snapshots for the SENTRI self-cancel study.

Snapshot mode captures metrics to a CSV; --report mode prints the run-over-run
diff and flags metrics that worsen monotonically (disambiguates Trigger 2).
Stdlib-only, self-contained. See specs/analysis/snapshot-resources.md.
"""


import csv
import os
from collections import namedtuple

# metric -> (bad direction, hypothesis it points to, description)
METRICS = {
    "soc_temp": ("up", "H4", "SoC thermal throttle"),
    "ctrl_fds": ("up", "H5", "controller FD/socket leak"),
    "app_fds": ("up", "H5", "web-app FD/socket leak"),
    "time_wait": ("up", "H5", "TIME_WAIT socket buildup"),
    "ctrl_rss": ("up", "H6", "controller memory growth"),
    "app_rss": ("up", "H6", "web-app memory growth"),
    "button_p95": ("up", "H2", "/button_status latency climbing"),
    "ctrl_threads": ("up", "H1", "controller thread leak"),
    "history_bytes": ("up", "H2", "history.json growing (blocking work)"),
    "disk_free_mb": ("down", "DISK", "disk filling up"),
}

Flag = namedtuple("Flag", ["metric", "hypothesis", "direction", "series"])


def _numeric_series(rows, metric):
    """Float values for a metric across rows, skipping blank/non-numeric cells."""
    series = []
    for row in rows:
        raw = row.get(metric, "")
        if raw is None or str(raw).strip() == "":
            continue
        try:
            series.append(float(raw))
        except (TypeError, ValueError):
            continue
    return series


def analyze(rows):
    """Flag metrics that worsen monotonically across the given snapshot rows."""
    flags = []
    for metric, (direction, hypothesis, _desc) in METRICS.items():
        series = _numeric_series(rows, metric)
        if monotonic_trend(series, direction=direction):
            flags.append(Flag(metric, hypothesis, direction, series))
    return flags


# Ordered CSV columns. "label" first; metrics follow in a stable order.
SNAPSHOT_FIELDS = [
    "label", "soc_temp", "throttled", "ctrl_fds", "app_fds", "time_wait",
    "ctrl_rss", "app_rss", "button_p95", "ctrl_threads", "disk_free_mb",
    "history_bytes", "oom",
]


def write_snapshot(path, row):
    """Append one labeled snapshot row to the CSV, writing the header once."""
    path = os.fspath(path)
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SNAPSHOT_FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def read_snapshots(path):
    """Read snapshot rows back as a list of dicts (empty if file absent)."""
    path = os.fspath(path)
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def monotonic_trend(values, direction="up"):
    """True iff values strictly trend the 'bad' way every step (>=2 points)."""
    if len(values) < 2:
        return False
    if direction == "up":
        return all(b > a for a, b in zip(values, values[1:]))
    return all(b < a for a, b in zip(values, values[1:]))


def report(rows):
    """Format a run-over-run diff table; FLAG metrics trending the bad way."""
    if not rows:
        return "No snapshots recorded."
    labels = [r.get("label", "?") for r in rows]
    flagged = {f.metric: f for f in analyze(rows)}

    lines = ["Run-over-run snapshot diff:", ""]
    header = "%-16s | %s" % ("metric", " | ".join("%10s" % lbl[:10] for lbl in labels))
    lines.append(header)
    lines.append("-" * len(header))
    for metric in SNAPSHOT_FIELDS:
        if metric == "label":
            continue
        cells = " | ".join("%10s" % (r.get(metric, "") or "") for r in rows)
        mark = ""
        if metric in flagged:
            mark = "  <== FLAG: %s (%s)" % (
                flagged[metric].hypothesis, METRICS[metric][2])
        lines.append("%-16s | %s%s" % (metric, cells, mark))

    lines.append("")
    if flagged:
        summary = ", ".join(
            "%s %s -> %s" % (f.metric, "up" if f.direction == "up" else "down", f.hypothesis)
            for f in flagged.values()
        )
        lines.append("Flagged: " + summary)
    else:
        lines.append("No metric trends monotonically yet (need more runs or no leak).")
    return "\n".join(lines)


# --- host metric collection: not unit-tested (on-device) --------------------

import subprocess  # noqa: E402
import sys         # noqa: E402
import time        # noqa: E402
import argparse    # noqa: E402
import urllib.request  # noqa: E402

_DEFAULT_CSV = os.path.join("diagnostics_out", "snapshots.csv")


def _sh(cmd):
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return ""


def _proc_field(pid, field):
    if not pid:
        return ""
    try:
        with open("/proc/%s/status" % pid) as fh:
            for line in fh:
                if line.startswith(field):
                    # e.g. "VmRSS:\t  12345 kB" -> "12345"
                    return line.split(":", 1)[1].strip().split()[0]
    except Exception:
        return ""
    return ""


def _fd_count(pid):
    if not pid:
        return ""
    try:
        return str(len(os.listdir("/proc/%s/fd" % pid)))
    except Exception:
        return ""


def _soc_temp():
    raw = _sh("vcgencmd measure_temp")  # temp=56.3'C
    if "=" in raw:
        return raw.split("=", 1)[1].rstrip("'C").rstrip("C")
    return ""


def _button_p95(app_url, n=20):
    if not app_url:
        return ""
    lat = []
    for _ in range(n):
        t0 = time.monotonic()
        try:
            urllib.request.urlopen("%s/button_status/" % app_url, timeout=6).read()
            lat.append(time.monotonic() - t0)
        except Exception:
            lat.append(6.0)  # treat timeout as the ceiling
        time.sleep(0.1)
    lat.sort()
    return "%.3f" % lat[int(0.95 * len(lat)) - 1]


# Where the run history file may live, most-specific first. The real device
# path is logs/history.json (sentri_web.main: BASE_DIR/"logs"/"history.json");
# data/ and bare are fallbacks for Docker/other layouts.
HISTORY_CANDIDATES = ("logs/history.json", "data/history.json", "history.json")


def first_existing_size(candidates):
    """Size (as str) of the first existing path in candidates, else ''."""
    for cand in candidates:
        if os.path.exists(cand):
            return str(os.path.getsize(cand))
    return ""


def collect(label, backend_pid=None, app_pid=None, app_url=None):
    """Gather one snapshot from the host. Missing sources yield blank cells."""
    statvfs_free = ""
    try:
        st = os.statvfs("logs") if os.path.exists("logs") else os.statvfs(".")
        statvfs_free = str(round(st.f_bavail * st.f_frsize / 1e6))
    except Exception:
        pass
    history = first_existing_size(HISTORY_CANDIDATES)
    return {
        "label": label,
        "soc_temp": _soc_temp(),
        "throttled": _sh("vcgencmd get_throttled"),
        "ctrl_fds": _fd_count(backend_pid),
        "app_fds": _fd_count(app_pid),
        "time_wait": _sh("ss -tan state time-wait | wc -l"),
        "ctrl_rss": _proc_field(backend_pid, "VmRSS"),
        "app_rss": _proc_field(app_pid, "VmRSS"),
        "button_p95": _button_p95(app_url),
        "ctrl_threads": _proc_field(backend_pid, "Threads"),
        "disk_free_mb": statvfs_free,
        "history_bytes": history,
        "oom": _sh("dmesg 2>/dev/null | grep -i 'killed process' | tail -1"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Per-run resource snapshot for the self-cancel study.")
    parser.add_argument("--label", help="label for this snapshot row (e.g. after-run-2)")
    parser.add_argument("--backend-pid", default=None, help="controller PID")
    parser.add_argument("--app-pid", default=None, help="web-app PID")
    parser.add_argument("--app-url", default="http://127.0.0.1:8090", help="web-app base URL")
    parser.add_argument("--csv", default=_DEFAULT_CSV, help="snapshot CSV path")
    parser.add_argument("--report", action="store_true", help="print the run-over-run diff and exit")
    args = parser.parse_args(argv)

    if args.report:
        print(report(read_snapshots(args.csv)))
        return 0

    if not args.label:
        parser.error("--label is required when taking a snapshot")
    os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
    row = collect(args.label, args.backend_pid, args.app_pid, args.app_url)
    write_snapshot(args.csv, row)
    print("Snapshot '%s' written to %s" % (args.label, args.csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())

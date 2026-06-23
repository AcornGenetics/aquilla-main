#!/usr/bin/env python3
"""Live terminal monitor for SENTRI self-cancellation.

Tails the controller, web-app, and lid logs while you reproduce the bug,
colorizing the diagnostic fingerprints and showing a live status header.
Stdlib-only, self-contained. See specs/analysis/watch-cancel.md.
"""
import re
from datetime import datetime


_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})")
_LIVE = re.compile(r"live=(\d+)")
_POLL = re.compile(r"Error polling stop request \((\d+)/\d+\)")


def _parse_ts(line):
    m = _TS.match(line)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")

_CANCEL_MARKERS = ("Stop request detected", "Run stopped by user", "Stop button pressed")


def classify_color(line):
    """Return the highlight color for a log line, or None for plain."""
    if "Backend unreachable" in line or "forcing stop" in line:
        return "red"
    if "Error polling stop request" in line:
        return "yellow"
    if any(marker in line for marker in _CANCEL_MARKERS):
        return "magenta"
    if "LID WORKER" in line or "LID JOIN DONE" in line or "live=" in line:
        return "cyan"
    return None


class Monitor:
    """Tracks live header state as log lines are fed in."""

    def __init__(self):
        self.live_workers = 0
        self.poll_failures = 0
        self.cancel_fired = False
        self._last_app_ts = None

    def feed(self, source, line):
        m = _LIVE.search(line)
        if m:
            self.live_workers = int(m.group(1))

        if "RUN START" in line:
            self.poll_failures = 0
        poll = _POLL.search(line)
        if poll:
            self.poll_failures = int(poll.group(1))

        if "Stop request detected" in line:
            self.cancel_fired = True

        if source == "app":
            ts = _parse_ts(line)
            if ts is not None:
                self._last_app_ts = ts

    def seconds_since_app(self, now):
        """Seconds since the web app last logged; None if it never has."""
        if self._last_app_ts is None:
            return None
        return (now - self._last_app_ts).total_seconds()

    def header(self, now, have_lid=True):
        """One-line status string for the live header."""
        parts = []
        if have_lid:
            parts.append("lid live=%d" % self.live_workers)
        parts.append("polls %d/10" % self.poll_failures)
        silent = self.seconds_since_app(now)
        parts.append("app silent %s" % ("--" if silent is None else "%.1fs" % silent))
        status = " | ".join(parts)
        if self.cancel_fired:
            status += "   *** CANCEL FIRED ***"
        return status


# --- I/O glue below: not unit-tested (manual / on-device) -------------------

import os       # noqa: E402
import sys      # noqa: E402
import time     # noqa: E402
import argparse  # noqa: E402

_ANSI = {
    "red": "\033[1;31m",
    "yellow": "\033[33m",
    "magenta": "\033[1;35m",
    "cyan": "\033[36m",
}
_RESET = "\033[0m"


def _wrap(text, color, use_color):
    if color and use_color:
        return "%s%s%s" % (_ANSI[color], text, _RESET)
    return text


def _follow(handles):
    """Yield (source, line) as new lines appear; tail -F style with re-open."""
    while True:
        idle = True
        for entry in handles:
            source, path = entry["source"], entry["path"]
            fh = entry["fh"]
            if fh is None:
                try:
                    fh = open(path, errors="replace")
                    fh.seek(0, os.SEEK_END)
                    entry["fh"] = fh
                except FileNotFoundError:
                    continue
            # detect truncation/rotation
            try:
                if os.stat(path).st_size < fh.tell():
                    fh.seek(0)
            except OSError:
                pass
            line = fh.readline()
            if line:
                idle = False
                yield source, line.rstrip("\n")
        if idle:
            yield None, None  # idle tick → repaint header


def main(argv=None):
    parser = argparse.ArgumentParser(description="Live monitor for SENTRI self-cancellation.")
    parser.add_argument("--logger", required=True, help="controller logger.log")
    parser.add_argument("--app", required=True, help="web-app app_logger.log")
    parser.add_argument("--lid", default=None, help="lid_heater_logger.log (optional)")
    args = parser.parse_args(argv)

    use_color = sys.stdout.isatty()
    have_lid = args.lid is not None
    handles = [
        {"source": "logger", "path": args.logger, "fh": None},
        {"source": "app", "path": args.app, "fh": None},
    ]
    if have_lid:
        handles.append({"source": "lid", "path": args.lid, "fh": None})

    monitor = Monitor()
    print("Watching for self-cancels (Ctrl-C to quit)...\n")
    try:
        for source, line in _follow(handles):
            if line is None:
                print("\r" + monitor.header(datetime.now(), have_lid), end="\r")
                time.sleep(0.2)
                continue
            monitor.feed(source, line)
            color = classify_color(line)
            print(_wrap("[%s] %s" % (source, line), color, use_color))
            print(monitor.header(datetime.now(), have_lid), end="\r")
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

# Analysis Spec: SENTRI Self-Cancellation Bug Study

**Status:** Draft
**Author:** Jack
**Last updated:** 2026-06-15
**GitHub issue:** #TBD
**Type:** Diagnostic study (read-only + temporary instrumentation). **No fix is in scope** — the deliverable is a *confirmed trigger* (or a documented "cause still unknown" with next steps).
**Source file(s):** `state_run_assay.py`, `aq_lib/regulate.py`, `aq_lib/state_requests.py`, `aq_lib/thermal_engine.py`, `aquila_web/main.py`, `application.py`

---

## 1. Purpose

A SENTRI run self-cancels ~20–30 s in, with **no user input**. The likelihood rises with each successive run (cancel by ~the 4th run), and a **power-cycle resets** the behavior. The device lands on the **`ready`** screen, identical to a user-initiated stop.

This study's single goal: **determine which mechanism sets `stop_event` when no one pressed Stop** — and prove it with evidence, not assertion. It must be able to conclude **"none of the named triggers is confirmed"** so we do not mislabel a cause while the real one remains at large (see §9, Outcome D).

This is **diagnosis-only**. Any fix is a separate follow-up spec written *after* a trigger is confirmed.

---

## 2. Confirmed mechanism (the part we already know)

This much is established from code and from the observed symptom (lands on `ready`):

1. A self-cancel always lands on `ready`. The only way to land on `ready` mid-run is the `except RunStopped` path (`state_run_assay.py:242-244, 269-270`).
2. `RunStopped` is raised **only** when `stop_event.is_set()` (`thermal_engine.py:13-14`).
3. `stop_event` is set **only** by `_monitor_stop_request` (`state_run_assay.py:315-322`), which sets it when `check_stop_request()` returns `True`.
4. `check_stop_request()` (`aq_lib/state_requests.py:138-153`) returns `True` in **exactly two** cases:
   - **Trigger 1 — real flag:** the web app returns `stop_requested: true`. The *only* code that sets that flag is `POST /button/stop` (`aquila_web/main.py:909-914`, logs `"Stop button pressed"` at line 913).
   - **Trigger 2 — safety net:** `_stop_poll_failures` reaches `_STOP_POLL_FAILURE_LIMIT` (10) consecutive failed polls (~5 s of the web app being unreachable), which **forces** a stop regardless of the flag (`state_requests.py:149-151`, logs `"Backend unreachable for N consecutive polls — forcing stop"`).

> A thermal/serial fault is **ruled out as the direct cause**: it would raise a plain exception and land on the **error screen `-1`** (`state_run_assay.py:248-251`), not `ready`. Heat can only matter *indirectly* (see Hypothesis H1 and H4).

Two-process architecture (critical to interpretation):
- **Controller process** = `application.py` → `AssayInterface` (`state_run_assay.py`). Owns the Meerstetter serial, the I2C ADC, GPIO, the lid heater, optics, motors. **One long-lived process**, looping `ready()/run()/end()` forever (`application.py:14-18`).
- **Web app process** = `aquila_web/main.py` (FastAPI/uvicorn on `:8090`). Holds the `stop_requested` flag and serves `/button_status/`.

The controller polls the web app over HTTP. They are **separate processes**, so a controller-side problem (e.g. leaked threads) does **not** directly freeze the web app — any link between them is via shared host resources (CPU, I2C bus, SoC temperature). Keep this in mind when reading evidence.

---

## 3. Hypotheses (what could make `check_stop_request()` return True)

Each hypothesis lists its **fingerprint** (what proves it) and its **falsification** (what rules it out). Ranked by fit to the symptom signature *(worsens per run + power-cycle fixes)*.

| ID | Hypothesis | Trigger | Fingerprint (confirms) | Falsification (rules out) |
|----|-----------|---------|------------------------|---------------------------|
| **H1** | **Lid-heater thread leak.** Each run starts a new `lid_heater_worker` thread (`state_run_assay.py:214-219`) but they share one `lid_heater_stop_event` created in `__init__` (`:49`). Teardown sets it and `join(timeout=5)` (`hw_deinitialize`, `:296-298`). If a lid ADC read blocks >5 s (`regulate.py:67-76`), the join gives up; the next run's `clear()` (`:218`) revives the abandoned thread. Threads accumulate, all driving GPIO 21 and the lockless module-level `adc` (`regulate.py:14`). | 2 (indirect) | Instrumented log shows lid-worker `live=N` climbing across runs without matching `EXIT`. Lid runs measurably hotter by run 4. | `live` returns to 0 after every run AND lid temp identical run-to-run. |
| **H4** | **Pi SoC thermal throttle.** Back-to-back runs heat the SoC; throttling slows the web app → poll timeouts. The *legitimate heat → cancel* bridge, possibly amplified by H1. | 2 | `vcgencmd get_throttled` non-zero / `measure_temp` climbing toward 80–85 °C before the cancel. **Experiment 1** (spacing runs) prevents the cancel. | Temp well under throttle threshold at cancel time AND spacing runs out does **not** help. |
| **H5** | **File-descriptor / socket leak.** `requests` is used with no `Session`, opening a new TCP connection every 0.5 s poll (`state_requests.py`). FDs / TIME_WAIT sockets accumulate → host degrades. | 2 | Open-FD count for either PID climbs monotonically across runs; high TIME_WAIT count. | FD/socket counts flat across runs. |
| **H6** | **Memory growth / OOM.** Either process leaks RSS → swap thrash or OOM-kill → stalls/restart. | 2 | RSS climbs per run; `dmesg` shows OOM killer; web app restarts. | RSS flat; no OOM lines. |
| **H2** | **Web-app event-loop blocking.** Sync work in async handlers freezes *all* endpoints incl. `/button_status`. Candidates: `/events/run_complete` + `/history/append` do sync file/SQLite I/O (`main.py:666-680, 760+`), growing with history size; `sync_pending_events()` is called synchronously in the async poller (`main.py:1711-1719`). | 2 | `app_logger.log` shows a multi-second **gap** (no lines) during the abort window; endpoint-latency probe spikes >5 s. | `/button_status` latency stays low throughout; no log gaps. |
| **H7** | **Watchtower / crash restart.** Container auto-update or crash restarts the web app mid-run (ADR-002). | 2 | `app_logger.log` shows `Application startup` / `Started server` mid-run; container uptime resets; watchtower logs a pull. | No restart markers; container uptime spans all runs. |
| **H3** | **Phantom touch / frontend re-fire.** A ghost capacitive touch or a JS re-POST on WebSocket reconnect hits `/button/stop`. | 1 | `app_logger.log` shows `"Stop button pressed"` at abort time with no human tap. | No `"Stop button pressed"` near any self-cancel. |
| **H8** | **Stale flag / failed reset.** `stop_requested` left `True` from a prior run; `reset_stop_request()` swallows exceptions (`state_requests.py:129-133`). | 1 | Controller sees `stop_requested: true` with no `"Stop button pressed"` AND a `"Stop reset"` was missing/failed at run start. | `"Stop reset"` present at each run start; flag observed `false` at run start. |

**H0 — Unknown.** None of H1–H8 fingerprints appear at the abort. This is a **valid, expected-possible outcome** (§9 Outcome D). The study must surface it rather than force-fit one of the above.

---

## 4. Step 0 — Confirm the environment (do this first)

Everything below has a **native** and a **Docker** variant. Determine which deployment the affected unit uses, then use that column throughout.

```bash
# Is it running in Docker?
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}'
# If the controller/web app appear as containers → DOCKER. If not → NATIVE.
```

| Thing | Native | Docker |
|---|---|---|
| Controller PID | `pgrep -f application.py` | `docker exec <backend> pgrep -f application.py` |
| Web app PID | `pgrep -f 'uvicorn\|aquila_web'` | `docker exec <backend> pgrep -f 'uvicorn\|aquila_web'` |
| Controller log | `logs/logger.log` | `data/logs/logger.log` (host mount) or `docker exec <c> cat /opt/aquila/logs/logger.log` |
| Web app log | `logs/app_logger.log` | `data/logs/app_logger.log` |
| Lid heater log | `logs/lid_heater/lid_heater_logger.log` | `data/logs/lid_heater/lid_heater_logger.log` |
| Run a script | `python scripts/diagnostics/<name>.py` | `docker exec <backend> python scripts/diagnostics/<name>.py` (or run on host against mounted `data/logs`) |
| `vcgencmd` (Pi temp) | host only — run on the Pi host, **not** inside a container | host only |

> Record which environment, the container names, and the resolved log paths at the top of your results sheet. All later commands assume you've substituted these.

---

## 5. Instrumentation to add (temporary, diagnosis-only)

These changes **only add logging** — no control flow changes. They are removed at the end of the study (§11). Purpose: make the lid-thread leak (H1) and heat behavior directly visible in logs, so no live shell is required.

### 5.1 `aq_lib/regulate.py` — lid-worker lifecycle + live count + heat visibility

Add a module-level live counter and instrument `lid_heater_worker`:

```python
import threading

_lid_workers_live = 0
_lid_workers_lock = threading.Lock()

def _lid_live_inc():
    global _lid_workers_live
    with _lid_workers_lock:
        _lid_workers_live += 1
        return _lid_workers_live

def _lid_live_dec():
    global _lid_workers_live
    with _lid_workers_lock:
        _lid_workers_live -= 1
        return _lid_workers_live

def lid_heater_worker(stop_event, quiet_event=None, setpoint=None, lower_bound=None):
    tid = threading.get_ident()
    live = _lid_live_inc()
    logger.info("LID WORKER START tid=%s live=%d", tid, live)   # <-- accumulation signal
    try:
        # ... existing body unchanged ...
        # inside the ADC read retry loop, time the read so we can see I2C stalls:
        #   t0 = time.monotonic()
        #   v = adc.read_continuous(pga_fs_v=4.096)
        #   dt = time.monotonic() - t0
        #   logger.info("lid AIN0: %.4f V (read %.3fs) tid=%s", v, dt, tid)
        # when commanding the heater:
        #   logger.debug("GPIO21 HIGH tid=%s v=%.4f", tid, v)
    finally:
        live = _lid_live_dec()
        logger.info("LID WORKER EXIT tid=%s live=%d", tid, live)  # <-- clean exit signal
        GPIO.output(pin_number, GPIO.LOW)
```

**What it tells you:**
- **Are threads accumulating?** Matched `START live=1` → `EXIT live=0` each run = healthy. `START live=1`, `START live=2`, … with no `EXIT` = leak.
- **How many?** `live=N` is the count of live lid workers — no baseline subtraction needed (counts lid workers only).
- **Which one leaked?** The `tid=` of a `START` with no matching `EXIT`.
- **I2C stalls (the leak's prerequisite):** `read %.3fs` > 5 s explains a join timeout.
- **Heat behavior:** density of `GPIO21 HIGH` lines = how hard the heater is being driven (multiple tids interleaving = over-driven).

### 5.2 `state_run_assay.py` — run index + post-join leak check

```python
# in __init__:
self._run_index = 0

# at the very start of run():
self._run_index += 1
logger.info("RUN START index=%d", self._run_index)

# in hw_deinitialize(), immediately AFTER the join:
if hasattr(self, "lid_thread") and self.lid_thread.is_alive():
    self.lid_thread.join(timeout=5)
from aq_lib.regulate import _lid_workers_live
still_alive = self.lid_thread.is_alive() if hasattr(self, "lid_thread") else False
logger.info("LID JOIN DONE run_index=%d thread_still_alive=%s lid_live=%d",
            self._run_index, still_alive, _lid_workers_live)
```

**What it tells you:** if `thread_still_alive=True` / `lid_live>0` right here, the join gave up on *this* run — pinning the leak to a run index and timestamp.

> Keep log volume sane: per-read timing at `INFO` is one line/sec/worker — fine for a study. `GPIO21 HIGH` at `DEBUG` so it can be silenced. Do **not** add logging inside the 5 s join window or anywhere that changes timing.

---

## 6. Scripts to build

All scripts live in a **new** `scripts/diagnostics/` directory. None of them modify app state; they read logs, sample `/proc` and `vcgencmd`, and probe HTTP. Each is self-contained and runnable on the Pi (Python 3, stdlib only — no new deps).

### 6.1 `scripts/diagnostics/scan_cancel_logs.py` — log fingerprint scanner (the trigger classifier)

**Does:** parses `logger.log` + `app_logger.log`, finds each self-cancel (a `Stop request detected` / `Run stopped by user` with the surrounding window), and classifies it against H1–H8 / H0 using the fingerprints in §3. Correlates timestamps between the two files (your key requirement: *did the web app go quiet at the exact instant the controller gave up?*).

**Detects strings (grounded in code):**

| String | File | Source | Meaning |
|---|---|---|---|
| `Backend unreachable for N consecutive polls — forcing stop` | logger | `state_requests.py:150` | **Trigger 2 confirmed** |
| `Error polling stop request (k/10)` | logger | `state_requests.py:148` | poll-failure ladder toward forced stop |
| `Stop request detected` | logger | `state_run_assay.py:318` | abort fired (both triggers) |
| `Run stopped by user` | logger | `state_run_assay.py:243` | confirms RunStopped path |
| `Error in timer request` / `Error in change screen` / `Error updating drawer` | logger | `state_requests.py` | web app unreachable across the board → corroborates Trigger 2 |
| `LID WORKER START/EXIT … live=N` | lid log | §5.1 | thread-leak accounting (H1) |
| `LID JOIN DONE … lid_live=N` | logger | §5.2 | join-timeout leak pin (H1) |
| `Stop button pressed` | app | `main.py:913` | **Trigger 1** (H3) — only flag setter |
| `Stop reset` / `Run button pressed` | app | `main.py:920/889` | flag reset accounting (H8) |
| `Application startup` / `Started server` | app | uvicorn | mid-run restart (H7) |

**Output:** for each detected cancel — timestamp, last normal line in each log before it, the time delta between "web app last spoke" and "controller gave up," and a **verdict** (`H1`…`H8`, or `H0/UNKNOWN` if no fingerprint matched). Prints a summary table across all cancels found.

```python
#!/usr/bin/env python3
"""Scan controller + web-app logs, classify each self-cancel against the H1-H8 fingerprints.
Usage: scan_cancel_logs.py --logger logs/logger.log --app logs/app_logger.log [--lid logs/lid_heater/lid_heater_logger.log] [--window 30]
"""
import argparse, re
from datetime import datetime

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})")
def parse_ts(line):
    m = TS.match(line)
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f") if m else None

SIGNATURES = {
    "forcing_stop":   re.compile(r"Backend unreachable for \d+ consecutive polls"),
    "poll_ladder":    re.compile(r"Error polling stop request \((\d+)/10\)"),
    "stop_detected":  re.compile(r"Stop request detected"),
    "run_stopped":    re.compile(r"Run stopped by user"),
    "comms_error":    re.compile(r"Error in timer request|Error in change screen|Error updating drawer"),
    "lid_event":      re.compile(r"LID WORKER (START|EXIT) tid=(\d+) live=(\d+)"),
    "lid_join":       re.compile(r"LID JOIN DONE .*lid_live=(\d+)"),
}
APP_SIG = {
    "stop_pressed":   re.compile(r"Stop button pressed"),
    "stop_reset":     re.compile(r"Stop reset"),
    "restart":        re.compile(r"Application startup|Started server|Uvicorn running"),
}

def load(path):
    try:
        with open(path, errors="replace") as f:
            return f.readlines()
    except FileNotFoundError:
        return []

def classify(window_logger, window_app):
    """Return (verdict, evidence[]) for one cancel window."""
    ev = []
    has = lambda lines, rx: any(rx.search(l) for l in lines)
    if has(window_logger, SIGNATURES["forcing_stop"]):
        ev.append("forced-stop safety net fired (state_requests.py:150)")
        if not has(window_app, APP_SIG["stop_pressed"]):
            return "H2/H4/H5/H6/H7 (Trigger 2 — web app unreachable; narrow with resource snapshot)", ev
    if has(window_app, APP_SIG["stop_pressed"]):
        ev.append("Stop button pressed in app log with no user tap")
        return "H3 (phantom touch / frontend re-fire)", ev
    lid_lives = [int(SIGNATURES["lid_event"].search(l).group(3))
                 for l in window_logger if SIGNATURES["lid_event"].search(l)]
    if lid_lives and max(lid_lives) > 1:
        ev.append(f"lid workers live peaked at {max(lid_lives)} (leak)")
        return "H1 (lid-heater thread leak)", ev
    if has(window_app, APP_SIG["restart"]):
        return "H7 (web app restart mid-run)", ev
    if has(window_logger, SIGNATURES["comms_error"]):
        ev.append("controller-wide comms errors → Trigger 2")
        return "H2/H4/H5/H6 (Trigger 2 — narrow with resource snapshot)", ev
    return "H0 / UNKNOWN — no fingerprint matched; capture more (see spec §9 Outcome D)", ev

# (main: find each 'Stop request detected' in logger.log, slice +/- window seconds in BOTH
#  files by timestamp, call classify(), print per-cancel report + summary. Also print the
#  delta between 'last app-log line before cancel' and 'cancel time' — the co-incidence test.)
```

> The classifier deliberately returns a **set** of candidate H-IDs for Trigger 2 (it can't distinguish leak-vs-throttle-vs-blocking from logs alone) and an explicit **H0/UNKNOWN** when nothing matches. It never asserts a single cause it can't prove.

### 6.2 `scripts/diagnostics/watch_cancel.py` — live terminal monitor

**Does:** the "small terminal app to watch logs change in real time." Tails `logger.log` + `app_logger.log` + `lid_heater_logger.log`, colorizes the §6.1 key strings, and shows a **live header**: current lid-worker `live=N`, consecutive poll-failure count, seconds since the web app last logged, and a banner when a cancel fires.

```python
#!/usr/bin/env python3
"""Live monitor for SENTRI self-cancellation. stdlib-only tail -F of the three logs.
Usage: watch_cancel.py --logger logs/logger.log --app logs/app_logger.log --lid logs/lid_heater/lid_heater_logger.log
Header shows: lid live workers | poll failures k/10 | secs since app log | last cancel verdict.
"""
import argparse, os, time, re

HILITE = {
    r"Backend unreachable": "\033[1;31m",        # red bold — forced stop
    r"Error polling stop request \(\d+/10\)": "\033[33m",
    r"Stop request detected|Run stopped by user": "\033[1;35m",
    r"LID WORKER (START|EXIT) .*live=\d+": "\033[36m",
    r"Stop button pressed": "\033[1;31m",
    r"Application startup|Started server": "\033[1;31m",
}
LID_LIVE = re.compile(r"live=(\d+)")
POLL = re.compile(r"Error polling stop request \((\d+)/10\)")

def follow(path):
    f = open(path, errors="replace"); f.seek(0, os.SEEK_END)
    while True:
        line = f.readline()
        if not line:
            time.sleep(0.2); continue
        yield line

# (main: select() across the three file generators; maintain live counters; on each new line,
#  print colorized + repaint a one-line status header. Banner in red when 'Stop request detected'
#  or 'Backend unreachable' appears. Track 'seconds since last app-log line' to expose H2 gaps.)
```

> Run this in a second SSH session **while** reproducing. The "seconds since app log" counter visibly climbing past 5 s as a cancel fires is direct evidence of H2 (event-loop block) or H7 (restart).

### 6.3 `scripts/diagnostics/snapshot_resources.py` — per-run resource snapshot (the Trigger-2 disambiguator)

**Does:** takes a labeled snapshot of every host/process metric that separates H4/H5/H6/H2 from each other. Run it **once per run** (before run 1, after each run). It appends a row to `diagnostics_out/snapshots.csv`; a `--report` mode prints the run-over-run **diff table** — the metric that climbs monotonically outs the cause.

**Captures:**

| Metric | Source | Tells us |
|---|---|---|
| controller thread count | `/proc/<pid>/status` `Threads:` | H1 + other thread leaks |
| controller + app open FDs | `ls /proc/<pid>/fd \| wc -l` | H5 |
| TIME_WAIT sockets | `ss -tan state time-wait \| wc -l` | H5 |
| controller + app RSS | `/proc/<pid>/status` `VmRSS:` | H6 |
| SoC temp | `vcgencmd measure_temp` | H4 |
| throttled flags | `vcgencmd get_throttled` | H4 |
| disk free | `os.statvfs` on log dir | disk-full stall |
| `history.json` size | `os.path.getsize` | H2 (growing blocking work) |
| `/button_status` latency p95 | 20 timed GETs | H2 / H4 (the actual symptom proxy) |
| web app container uptime | `docker inspect -f '{{.State.StartedAt}}'` | H7 |
| recent OOM lines | `dmesg \| grep -i oom \| tail` | H6 |

```python
#!/usr/bin/env python3
"""Snapshot host+process resources, one row per invocation. Diff across runs to find the
metric that worsens monotonically.
Usage:
  snapshot_resources.py --label "after-run-2" [--backend-pid N] [--app-pid N] [--app-url http://127.0.0.1:8090]
  snapshot_resources.py --report          # prints the run-over-run diff table
Writes diagnostics_out/snapshots.csv (stdlib only; degrades gracefully if a source is absent).
"""
import argparse, csv, os, subprocess, time, urllib.request

def sh(cmd):
    try: return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception: return ""

def proc_field(pid, field):
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith(field): return line.split(":",1)[1].strip()
    except Exception: return ""
    return ""

def fd_count(pid):
    try: return len(os.listdir(f"/proc/{pid}/fd"))
    except Exception: return -1

def button_latency_p95(url, n=20):
    lat = []
    for _ in range(n):
        t0 = time.monotonic()
        try:
            urllib.request.urlopen(f"{url}/button_status/", timeout=6).read()
            lat.append(time.monotonic() - t0)
        except Exception:
            lat.append(6.0)  # treat timeout as the ceiling
        time.sleep(0.25)
    lat.sort(); return round(lat[int(0.95*len(lat))-1], 3)

def snapshot(label, backend_pid, app_pid, app_url):
    return {
        "label": label,
        "ctrl_threads": proc_field(backend_pid, "Threads:"),
        "ctrl_fds": fd_count(backend_pid),
        "app_fds": fd_count(app_pid),
        "time_wait": sh("ss -tan state time-wait | wc -l"),
        "ctrl_rss": proc_field(backend_pid, "VmRSS:"),
        "app_rss": proc_field(app_pid, "VmRSS:"),
        "soc_temp": sh("vcgencmd measure_temp"),
        "throttled": sh("vcgencmd get_throttled"),
        "disk_free_mb": round(os.statvfs("logs").f_bavail*os.statvfs("logs").f_frsize/1e6) if os.path.exists("logs") else "",
        "history_bytes": os.path.getsize("data/history.json") if os.path.exists("data/history.json") else "",
        "button_p95_s": button_latency_p95(app_url),
        "oom": sh("dmesg 2>/dev/null | grep -i 'killed process' | tail -1"),
    }
# (main: append snapshot dict to CSV; --report reads CSV and prints a column-aligned diff,
#  flagging any metric that increases on every successive run as a prime suspect.)
```

---

## 7. Test procedure (runbook)

> Do these **in order**. Steps 1–2 are free and split the hypothesis tree in half before any instrumentation. Record everything in one results sheet.

**Step 0.** Confirm environment (§4). Note PIDs, container names, log paths.

**Step 1 — Spacing experiment (splits leak vs SoC heat).** Run once, **wait ~10 min** for the Pi to cool, repeat to 4+ runs.
- Still self-cancels by run 4 → **leak family** (H1/H5/H6); cooling didn't help. Continue to instrumentation.
- Spacing **prevents** the cancel → **H4 (thermal throttle)**; confirm with `snapshot_resources` temp/throttled. *(Falsifies H1/H5/H6 as primary.)*

**Step 2 — Simulation-mode experiment (splits controller vs web app).** Set `DEV_SIMULATE=1` (ADR-007) and reproduce. Simulated runs never spawn the lid/executor/stop-monitor threads or touch hardware.
- Sim **never** cancels → cause is in the **controller/hardware path** (H1 family). *(Falsifies H2/H7 as primary.)*
- Sim **still** cancels → cause is **web-app-side** (H2/H6/H7); the lid threads are a separate heat bug.

**Step 3 — Apply instrumentation (§5).** Deploy the logging changes to one affected unit. Restart so a clean process baseline exists.

**Step 4 — Reproduce with monitoring.** In parallel:
- Terminal A: `watch_cancel.py` (§6.2) running live.
- Run `snapshot_resources.py --label before-run-1`, then after **every** run (`--label after-run-N`).
- Reproduce: run repeatedly until a self-cancel occurs.

**Step 5 — Classify.** After a cancel:
- `scan_cancel_logs.py` (§6.1) → per-cancel verdict + the **co-incidence delta** (did the app log go silent at the controller's give-up instant?).
- `snapshot_resources.py --report` → which metric climbed monotonically.
- Cross-check the lid `live=N` trace and `LID JOIN DONE` lines for H1.

**Step 6 — Decide** against §9. If no fingerprint forces a single cause → **Outcome D** (do not guess).

---

## 8. Decision matrix

| Observation | Verdict |
|---|---|
| `scan` shows `Backend unreachable` + **no** `Stop button pressed`, and `snapshot` shows **temp/throttled climbing**, and **Step 1 spacing helped** | **H4 — SoC thermal throttle** |
| `Backend unreachable` + no `Stop button pressed`, and **lid `live=N` climbed** / `LID JOIN DONE thread_still_alive=True` | **H1 — lid-thread leak** (likely feeding H4) |
| `Backend unreachable` + no `Stop button pressed`, and **FDs/TIME_WAIT climb** | **H5 — FD/socket leak** |
| `Backend unreachable` + no `Stop button pressed`, and **RSS climbs / OOM in dmesg** | **H6 — memory/OOM** |
| `Backend unreachable` + **app-log gap** during abort, `button_p95` spikes, no restart marker | **H2 — event-loop block** |
| `Application startup` mid-run / container uptime reset | **H7 — restart** |
| `Stop button pressed` at abort with no human tap | **H3 — phantom touch / frontend re-fire** |
| Controller saw flag true, **no** `Stop button pressed`, **no** `Stop reset` at run start | **H8 — stale flag / failed reset** |
| **None of the above fingerprints present** | **H0 — Outcome D (unknown)** |

---

## 9. Outcomes

- **Outcome A — Single trigger confirmed.** One fingerprint present, its falsification absent, others' fingerprints absent. → Write the follow-up fix spec for that trigger only.
- **Outcome B — Compound.** Two fit a causal chain (e.g. H1 → H4). Document the chain; the fix spec addresses the root (H1) and verifies H4 clears.
- **Outcome C — Ambiguous Trigger 2.** `Backend unreachable` confirmed but **no** resource metric climbs and spacing/sim are inconclusive. → Trigger 2 is real but the *driver* is unidentified; treat as Outcome D for the driver while recording that the safety net (not Trigger 1) is firing.
- **Outcome D — Cause still unknown (required, not a failure).** No fingerprint forces a cause. **Do not name one.** Record:
  - which hypotheses were **falsified** (so we never re-chase them),
  - which remain **open**,
  - **next capture**: enable `py-spy dump` on the controller PID at the abort, raise log verbosity, add a `/debug/threads` endpoint to the web app, capture `strace`/`ss -tp` during the abort window, and bring both raw logs back for a deeper pass.

> The study **succeeds** if it either confirms a trigger *with evidence* or honestly reaches Outcome D. It **fails** only if it asserts a cause the data doesn't support.

---

## 10. Test coverage (per project rules)

The only pure logic worth unit-testing is the log classifier (the scripts otherwise read live system state). Add:

| Test | File | Verifies |
|---|---|---|
| Forced-stop window → Trigger 2 verdict | `unit_tests/test_scan_cancel_logs.py` | `classify()` returns Trigger-2 set when `Backend unreachable` present, no `Stop button pressed` |
| Phantom-touch window → H3 | `unit_tests/test_scan_cancel_logs.py` | `Stop button pressed` + no tap → `H3` |
| Lid-leak window → H1 | `unit_tests/test_scan_cancel_logs.py` | `live=` peaks >1 → `H1` |
| Empty/no-fingerprint window → H0 | `unit_tests/test_scan_cancel_logs.py` | nothing matches → `H0/UNKNOWN` |
| Timestamp co-incidence delta | `unit_tests/test_scan_cancel_logs.py` | correct delta between last app line and cancel |

Run: `pytest unit_tests/test_scan_cancel_logs.py -v`. The scripts that read `/proc`, `vcgencmd`, and Docker are hardware/host-dependent — mark any such test `@pytest.mark.hardware` and exclude from CI.

---

## 11. Cleanup

After a verdict is reached:
- Revert the §5 instrumentation (it's temporary observability, not a shipped feature) **unless** the team elects to keep the lid `live=N` lines as permanent leak telemetry — decide explicitly.
- Keep `scripts/diagnostics/` and this spec as the record.
- Open the follow-up **fix** spec referencing the confirmed outcome.

---

## 12. References

- Mechanism: `state_run_assay.py:169-289` (`run`), `:315-322` (`_monitor_stop_request`), `:292-298` (`hw_deinitialize`); `aq_lib/thermal_engine.py:9-14`; `aq_lib/state_requests.py:129-153`; `aquila_web/main.py:164, 909-921, 1003, 666-680, 760+, 1711-1719`.
- Lid heater: `aq_lib/regulate.py:14, 43-88` (module `adc` singleton, worker loop).
- Process model: `application.py:12-25`; `compose.yaml`.
- Glossary: `CONTEXT.md` (Abort, Stop Request, Self-Cancellation — pending).
- Related ADRs: ADR-002 (Watchtower updates → H7), ADR-004 (FastAPI/WebSocket state → H2/H3), ADR-007 (simulation mode → Step 2).
- Existing consecutive-run test: `tests/unit/test_consecutive_runs.py` (queue-drain path).
```

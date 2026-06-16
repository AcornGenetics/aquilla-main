# Analysis Spec: watch_cancel.py — Live Self-Cancel Monitor

**Status:** Draft
**Author:** Jack
**Last updated:** 2026-06-16
**GitHub issue:** #159
**Type:** Diagnostic tool (stdlib-only; live terminal UI). Self-contained — no dependency on #158.
**Source file(s):** `scripts/diagnostics/watch_cancel.py` (new)
**Parent study:** `specs/analysis/sentri-self-cancel-study.md` §6.2

---

## 1. Purpose

A live terminal monitor you run in a second SSH session **while reproducing** the self-cancel. It tails the controller, web-app, and lid logs in real time, colorizes the diagnostic fingerprints, and keeps a one-line status header so you can *watch the failure build* — rather than classifying logs after the fact (that is #158's job).

It targets, live:
- **Trigger 2** — the `Error polling stop request (k/10)` ladder climbing, and "seconds since the web app last logged" crossing ~5 s as the safety net fires.
- **Threading / H1** — the lid-worker `live=N` count rising across runs.

---

## 2. Inputs

| Input | Type | Source | Notes |
|-------|------|--------|-------|
| Controller log | `--logger` path | `aquila` logger | abort, poll ladder, comms errors |
| Web-app log | `--app` path | `aquila_app` logger | `Stop button pressed`, restarts; drives "secs since app" |
| Lid heater log | `--lid` path (optional) | `lid_heater` logger | `LID WORKER … live=N` (#157) |

Native paths `logs/…`; Docker host paths `data/logs/…`.

---

## 3. Public Interface

```python
classify_color(line: str) -> str | None
    # "red" | "yellow" | "magenta" | "cyan" | None  — which highlight a line gets.

class Monitor:
    live_workers: int        # latest lid live=N seen
    poll_failures: int       # latest k from "(k/10)"; reset to 0 on a new RUN START
    cancel_fired: bool       # True once a "Stop request detected" is seen
    def feed(self, source: str, line: str) -> None   # source: "logger"|"app"|"lid"
    def seconds_since_app(self, now: datetime) -> float | None

main(argv=None)              # argparse + tail-follow render loop (I/O glue; not unit-tested)
```

---

## 4. Color Mapping (`classify_color`)

| Fingerprint in line | Color | Why it matters |
|---------------------|-------|----------------|
| `Backend unreachable` / `forcing stop` | **red** | the safety net firing (Trigger 2) |
| `Error polling stop request (k/10)` | **yellow** | the countdown toward a forced stop |
| `Stop request detected` / `Run stopped by user` / `Stop button pressed` | **magenta** | the abort itself |
| `LID WORKER` / `LID JOIN DONE` / `live=` | **cyan** | thread lifecycle (H1) |
| anything else | **None** | printed plain |

---

## 5. Live Header

A single status line repainted as events arrive:

```
lid live=N | polls k/10 | app silent Ns | <CANCEL banner if fired>
```

- `live=N` — current lid workers (rising = leak forming).
- `k/10` — current consecutive poll-failure count (climbing = web app going unreachable).
- `app silent Ns` — `seconds_since_app(now)`; crossing ~5 s right before a cancel is the smoking gun.
- A red **CANCEL** banner latches when `cancel_fired` becomes true.

---

## 6. State Rules

- **live_workers:** set to the `N` of the most recent line containing `live=`.
- **poll_failures:** set to `k` from `Error polling stop request (k/10)`; reset to `0` when a `RUN START` line arrives (new run begins).
- **seconds_since_app:** `now - (timestamp of last app-log line fed)`; `None` until an app line with a timestamp is seen.
- **cancel_fired:** latches `True` on `Stop request detected`.

---

## 7. CLI Usage

```bash
# run in a second SSH session while reproducing
python scripts/diagnostics/watch_cancel.py \
    --logger logs/logger.log --app logs/app_logger.log \
    --lid logs/lid_heater/lid_heater_logger.log
```

Follows files `tail -F`-style (handles rotation/truncation), Ctrl-C to quit. `--lid` optional (disables the `live=N` field).

---

## 8. Edge Cases

- **Non-timestamped lines** (tracebacks): printed with color if matched, but do not update `seconds_since_app`.
- **Missing optional `--lid`:** header omits `live=N`.
- **File not yet created / rotated:** the follow loop retries rather than crashing.
- **Encoding:** read with `errors="replace"`.
- **ANSI:** color is applied only when stdout is a TTY; piped output stays plain.

---

## 9. Test Coverage

`tests/unit/test_watch_cancel.py` (imported via `sys.path`, like `test_wifi_helpers`). Pure logic — the follow loop / rendering is manual/on-device.

| Test | Verifies |
|------|----------|
| `classify_color` forced-stop → red | safety-net highlight |
| `classify_color` poll ladder → yellow | countdown highlight |
| `classify_color` cancel markers → magenta | abort highlight |
| `classify_color` lid line → cyan | thread-lifecycle highlight |
| `classify_color` plain → None | no false highlights |
| `Monitor.feed` lid line → `live_workers` | leak counter |
| `Monitor.feed` ladder → `poll_failures`; RUN START resets | Trigger-2 counter |
| `Monitor.seconds_since_app(now)` | app-silence gauge |
| `Monitor.feed` cancel → `cancel_fired` | banner latch |

Run: `pytest tests/unit/test_watch_cancel.py -v`

---

## 10. Related

- Parent study: `specs/analysis/sentri-self-cancel-study.md` §6.2
- Reads: #157 instrumentation (`live=N`)
- Sibling tools: #158 `scan_cancel_logs.py` (post-hoc classify), #160 `snapshot_resources.py`
- Consumed by: #162 runbook

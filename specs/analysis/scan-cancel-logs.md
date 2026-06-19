# Analysis Spec: scan_cancel_logs.py — Self-Cancel Log Classifier

**Status:** Draft
**Author:** Jack
**Last updated:** 2026-06-16
**GitHub issue:** #158
**Type:** Diagnostic tool (stdlib-only, pure logic — no hardware, no network)
**Source file(s):** `scripts/diagnostics/scan_cancel_logs.py` (new)
**Parent study:** `specs/analysis/sentri-self-cancel-study.md` §3 (hypotheses), §6.1 (tool)

---

## 1. Purpose

Given the logs pulled off a SENTRI that self-cancelled, **find each self-cancel and classify what most likely caused it** — automatically, so an operator does not have to eyeball thousands of log lines. It is the master discriminator of the study: it separates **Trigger 1** (a real stop flag) from **Trigger 2** (the forced-stop safety net) from the **threading leak (H1)**, and it refuses to name a cause when the evidence does not support one (**H0**).

It also reports the **co-incidence delta** — the seconds between the last thing the web app logged and the moment the controller gave up — which is the single most telling signal for "did the web app go silent exactly when the run died?"

---

## 2. Inputs

| Input | Type | Source | Notes |
|-------|------|--------|-------|
| Controller log | `logger.log` (native) / `data/logs/logger.log` (Docker) | `sentri` logger | The decisive file — holds the abort and the safety-net ladder |
| Web-app log | `app_logger.log` | `aquila_app` logger | Holds `Stop button pressed`, restart markers |
| Lid heater log (optional) | `lid_heater/lid_heater_logger.log` | `lid_heater` logger | Holds `LID WORKER … live=N` from issue #157 |
| Window | `int` seconds (default 30) | CLI arg | How far before/after a cancel to slice the other logs |

All inputs are plain text with lines prefixed `YYYY-MM-DD HH:MM:SS,mmm - LEVEL - message`.

---

## 3. Public Interface

```python
parse_timestamp(line: str) -> datetime | None
    # Parse the leading "YYYY-MM-DD HH:MM:SS,mmm". None if the line has no timestamp.

find_cancels(logger_lines: list[str]) -> list[int]
    # Indices of self-cancel events (a "Stop request detected" / "Run stopped by user" line).

classify_window(logger_lines, app_lines, lid_lines=None) -> Verdict
    # Classify ONE cancel's surrounding window. Pure function over in-memory lines.

coincidence_delta(app_lines: list[str], cancel_ts: datetime) -> float | None
    # Seconds between the last app-log line at/just before the cancel and the cancel.
    # None if no timestamped app line precedes the cancel.

scan(logger_path, app_path, lid_path=None, window=30) -> list[CancelReport]
    # File I/O orchestration: read files, find cancels, slice windows, classify each.

main(argv=None)
    # argparse CLI entry point; prints a per-cancel report + summary.
```

`Verdict` = `{code: str, label: str, evidence: list[str]}`.
`CancelReport` = `{timestamp, verdict, coincidence_delta, last_app_line}`.

---

## 4. Classification Logic

`classify_window` applies the fingerprints from study §3, **most-specific first**. The first match wins.

| Order | Condition (in the window) | Code | Meaning |
|-------|---------------------------|------|---------|
| 1 | `Stop button pressed` in app log | **H3** | Trigger 1 — phantom touch / frontend re-fire (a real tap that no human made) |
| 2 | lid `live=N` peak > 1 | **H1** | Threading — lid-heater thread leak |
| 3 | `Application startup` / `Started server` / `Uvicorn running` mid-window | **H7** | Web app restarted mid-run (Watchtower / crash / OOM) |
| 4 | `Backend unreachable … forcing stop` and **no** `Stop button pressed` | **TRIGGER2** | Safety net fired; candidate set H2/H4/H5/H6 — narrow with `snapshot_resources.py` (#160) |
| 5 | controller comms errors only (`Error in timer request` / `Error in change screen` / `Error updating drawer`) | **TRIGGER2** | Web app unreachable across the board (corroboration) |
| 6 | a cancel fired but none of the above | **H8** | Stale flag — `stop_requested` true with no fresh press and no safety net |
| 7 | no diagnostic signal at all | **H0** | Unknown — **never asserts an unproven cause**; bring richer captures (study §9 Outcome D) |

Notes:
- **TRIGGER2 is deliberately a candidate set**, not a single hypothesis — logs alone cannot distinguish thermal throttle (H4) from FD leak (H5) from memory (H6) from event-loop block (H2). The verdict says so and points at #160.
- **H8 vs H0:** H8 means a cancel definitely fired but nothing (press, safety net, leak, restart) explains it → the flag must have been stale. H0 means there is no clear signal to reason from.

---

## 5. Outputs

For each detected cancel, printed and returned as a `CancelReport`:

- **Timestamp** of the cancel (from `logger.log`).
- **Verdict** — code + human label + the evidence lines that drove it.
- **Co-incidence delta** — seconds the web app was silent before the cancel (large delta ⇒ web app stalled/restarted right as the run died).
- **Last normal app-log line** before the cancel (for manual cross-check).

A final summary tallies verdicts across all cancels found (e.g. "3 cancels: 2× TRIGGER2, 1× H1").

---

## 6. CLI Usage

```bash
# native paths
python scripts/diagnostics/scan_cancel_logs.py \
    --logger logs/logger.log --app logs/app_logger.log \
    --lid logs/lid_heater/lid_heater_logger.log --window 30

# Docker host (mounted volume)
python scripts/diagnostics/scan_cancel_logs.py \
    --logger data/logs/logger.log --app data/logs/app_logger.log
```

Exit code 0 always (it is a report, not a gate). Missing optional `--lid` simply disables H1 detection (logs a note).

---

## 7. Edge Cases

- **Non-timestamped lines** (tracebacks, blank lines): `parse_timestamp` returns `None`; windowing skips them.
- **No cancels found:** prints "no self-cancels detected" and returns `[]`.
- **Clock skew between logs:** the co-incidence delta is reported but flagged as approximate; both logs use the host clock so skew is normally zero.
- **Missing app log:** classification still runs on controller-only signals (forced-stop, comms, lid); H3/H7 simply cannot fire.
- **Encoding:** read with `errors="replace"` (Pi logs are UTF-8; guards against stray bytes).

---

## 8. Test Coverage

`tests/unit/test_scan_cancel_logs.py` (imported via `sys.path`, like `tests/unit/test_wifi_helpers.py`). All pure logic — runs on any machine.

| Test | Verifies |
|------|----------|
| `parse_timestamp` valid + non-timestamped | Foundational parse, `None` on no-timestamp |
| `find_cancels` locates an abort | Cancel-event detection |
| forced-stop + no stop-pressed → `TRIGGER2` | Safety-net classification |
| `Stop button pressed` → `H3` | Trigger-1 phantom/re-fire |
| lid `live>1` → `H1` | Threading-leak classification |
| cancel + nothing explanatory → `H8` | Stale-flag classification |
| no signal → `H0` | Refuses to guess |
| `coincidence_delta` | Correct seconds between last app line and cancel |

Run: `pytest tests/unit/test_scan_cancel_logs.py -v`

---

## 9. Related

- Parent study: `specs/analysis/sentri-self-cancel-study.md` (§3 fingerprints, §8 decision matrix)
- Consumes: issue #157 instrumentation lines (`LID WORKER … live=N`)
- Consumed by: #163 `diagnose.py` (orchestrator calls this), #162 runbook
- Sibling tools: #159 `watch_cancel.py` (live), #160 `snapshot_resources.py` (narrows TRIGGER2)

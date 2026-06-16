# Analysis Spec: snapshot_resources.py — Per-Run Resource Snapshot

**Status:** Draft
**Author:** Jack
**Last updated:** 2026-06-16
**GitHub issue:** #160
**Type:** Diagnostic tool (stdlib-only; host metric collection + trend analysis). Self-contained.
**Source file(s):** `scripts/diagnostics/snapshot_resources.py` (new)
**Parent study:** `specs/analysis/sentri-self-cancel-study.md` §6.3

---

## 1. Purpose

When the safety net fires (Trigger 2 — the web app went unreachable), the logs alone cannot say *why*. This tool captures a labeled snapshot of host/process metrics **once per run**, and in `--report` mode prints the **run-over-run diff**: the metric that worsens monotonically across runs points at the cause. It is the only tool that **disambiguates within Trigger 2**.

---

## 2. Metrics & Hypothesis Map

Each metric has a "bad direction" — the way it moves when the corresponding fault is present.

| Metric (CSV column) | Source (glue) | Bad direction | Points to |
|---------------------|---------------|---------------|-----------|
| `soc_temp` | `vcgencmd measure_temp` (host) | up | **H4** SoC thermal throttle |
| `throttled` | `vcgencmd get_throttled` (host) | non-zero | **H4** (corroboration) |
| `ctrl_fds` | `/proc/<pid>/fd` count | up | **H5** FD/socket leak |
| `app_fds` | `/proc/<pid>/fd` count | up | **H5** |
| `time_wait` | `ss -tan state time-wait` | up | **H5** |
| `ctrl_rss` | `/proc/<pid>/status` VmRSS | up | **H6** memory/OOM |
| `app_rss` | `/proc/<pid>/status` VmRSS | up | **H6** |
| `button_p95` | 20 timed `/button_status/` GETs | up | **H2** event-loop block (also H4) |
| `ctrl_threads` | `/proc/<pid>/status` Threads | up | **H1** thread leak (controller) |
| `disk_free_mb` | `os.statvfs` | **down** | disk-full stall |
| `history_bytes` | `os.path.getsize` | up | **H2** (growing blocking work) |
| `oom` | `dmesg \| grep -i oom` | present | **H6** |

---

## 3. Public Interface

```python
METRICS: dict[str, (direction, hypothesis, description)]   # "up" | "down"

monotonic_trend(values, direction="up") -> bool
    # True iff values STRICTLY trend the bad way every step (>=2 numeric points).

write_snapshot(path, row: dict) -> None    # append one labeled row to CSV (header once)
read_snapshots(path) -> list[dict]         # read rows back

analyze(rows) -> list[Flag]                # flags metrics trending the bad way
    # Flag = (metric, hypothesis, direction, series)

collect(label, backend_pid, app_pid, app_url) -> dict   # host glue — NOT unit-tested
report(rows) -> str                        # formatted run-over-run diff table
main(argv=None)                            # snapshot mode (default) + --report mode
```

---

## 4. Trend Rules

- **Strict monotonic.** A metric is flagged only if it moves the bad way on **every** consecutive run (e.g. `soc_temp` 56 → 61 → 68 → 74). One plateau or dip means no flag — keeps false positives low.
- **Minimum 2 points.** Fewer runs ⇒ no trend ⇒ no flag.
- **Numeric coercion.** Values are read from CSV as strings; `analyze` coerces with `float()` and **skips blank / non-numeric** entries (a snapshot whose source was unavailable does not break the analysis).
- **Direction per metric.** Most metrics flag on increase; `disk_free_mb` flags on decrease.

---

## 5. Outputs

- **Snapshot mode** (default): append one row labeled `--label "after-run-2"` to `diagnostics_out/snapshots.csv`.
- **`--report` mode**: print a column-aligned table of each metric across runs, with a **FLAG** marker and the pointed-to hypothesis on any metric that trends the bad way monotonically. A summary lists the flagged culprits (e.g. "soc_temp ↑ → H4, ctrl_fds ↑ → H5").

---

## 6. CLI Usage

```bash
# take a snapshot (run before run 1, then after each run)
python scripts/diagnostics/snapshot_resources.py --label before-run-1 \
    --backend-pid 1234 --app-pid 1235 --app-url http://127.0.0.1:8090

# after several runs, see what climbed
python scripts/diagnostics/snapshot_resources.py --report
```

Runs on the Pi host (for `vcgencmd`). Missing sources degrade gracefully (blank cell, never a crash).

---

## 7. Edge Cases

- **Missing source** (no `vcgencmd`, PID gone, no docker): that cell is blank; analysis skips it.
- **First snapshot / single row:** `--report` prints values but flags nothing (no trend yet).
- **CSV header drift:** header written once on file creation; later rows align to it.
- **Non-numeric metrics** (`throttled` flags, `oom` text): excluded from `monotonic_trend`; surfaced in the report as-is.

---

## 8. Test Coverage

`tests/unit/test_snapshot_resources.py` (imported via `sys.path`, like `test_wifi_helpers`). Pure logic — host collection is on-device.

| Test | Verifies |
|------|----------|
| `monotonic_trend` up → True | strictly increasing flagged |
| `monotonic_trend` down → True | strictly decreasing (disk) flagged |
| `monotonic_trend` non-monotonic / <2 → False | no false trend |
| `write_snapshot` + `read_snapshots` round-trip | CSV model, header once |
| `analyze` climbing `soc_temp` → H4 | up-metric → hypothesis |
| `analyze` falling `disk_free_mb` → disk-full | down-metric direction |
| `analyze` flat metric → no flag | no false positives |
| `analyze` blank/non-numeric skipped | graceful degradation |

Run: `pytest tests/unit/test_snapshot_resources.py -v`

---

## 9. Related

- Parent study: `specs/analysis/sentri-self-cancel-study.md` §6.3, §8 (narrows TRIGGER2 from #158)
- Sibling tools: #158 `scan_cancel_logs.py`, #159 `watch_cancel.py`
- Consumed by: #163 `diagnose.py` (orchestrator runs this + `--report`), #162 runbook

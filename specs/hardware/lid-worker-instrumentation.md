# Hardware Spec: Lid-Heater Worker Instrumentation

**Status:** Active
**Author:** Jack
**Last updated:** 2026-06-15
**Subsystem:** Lid
**GitHub issue:** #157
**Source file(s):** `sentri_lib/lid_worker_metrics.py` (new), `sentri_lib/regulate.py`, `state_run_assay.py`
**Parent study:** `specs/analysis/sentri-self-cancel-study.md` §5

---

## 1. Overview

Temporary, diagnosis-only instrumentation that makes the **lid-heater worker thread lifecycle visible in the logs**, so the suspected thread leak (study hypothesis H1) can be confirmed or ruled out **without a live shell** into the running controller process.

It adds:
- a **live-worker counter** (`live=N`) logged on every worker start/exit,
- **per-read I2C duration** logging (the stall that triggers the leak),
- **GPIO-21 command** logging (how hard the heater is driven),
- a **run index** and a **post-join leak check** (`LID JOIN DONE`).

No control flow changes — logging and a thread-safe counter only. It is safe to leave running for the duration of the study and revert afterward (study spec §11), or keep the `live=N` lines as permanent leak telemetry if the team elects to.

---

## 2. Hardware Components

| Component | Part / Model | Interface | Notes |
|-----------|-------------|-----------|-------|
| Lid heater element | resistive heater | GPIO 21 (BCM), active HIGH | Driven by `lid_heater_worker` duty loop |
| Lid thermistor / ADC | ADS1115 @ `0x48` | I2C (`/dev/i2c-1`) | Module-level singleton `adc` in `regulate.py`; **no lock** — shared by all workers |

---

## 3. Operating Parameters

| Parameter | Min | Nominal | Max | Unit |
|-----------|-----|---------|-----|------|
| Lid ADC lower bound | — | 0.20 | — | V |
| Lid ADC upper bound (setpoint) | — | 0.34 | — | V |
| Worker duty cycle | — | 0.9 on / 0.1 off | — | s |
| ADC read retry budget | — | 10 × 0.4 | ~4 | s |
| Teardown join timeout | — | 5 | — | s |

**Safety limits:** instrumentation must not change timing inside the 5 s teardown join window, must not alter the duty loop, and must not add blocking work to the worker. Logging is additive only.

---

## 4. Control Logic

The instrumentation wraps — but does not change — the existing worker loop:

```
enter(tid) → log "LID WORKER START live=N"
  ├─ start_continuous(ADC)
  ├─ while not stop_event.is_set():
  │     read ADC (timed) → log "lid AIN0: V (read Ns) tid="
  │     if in band and not quiet: GPIO21 HIGH → log (debug) "GPIO21 HIGH"
  │     sleep 0.9 → GPIO21 LOW → sleep 0.1
  └─ finally: GPIO21 LOW; exit(tid) → log "LID WORKER EXIT live=N"
```

Teardown (`hw_deinitialize`) after `join(timeout=5)`:
```
log "LID JOIN DONE run_index=I thread_still_alive=B lid_live=N"
```

- **Start/stop triggers:** unchanged — a worker starts per run (`state_run_assay.run`), stops when `lid_heater_stop_event` is set in `hw_deinitialize`.
- **On failure/timeout:** if the ADC read stalls > 5 s, the teardown join times out; `LID JOIN DONE` then reports `thread_still_alive=True` / `lid_live>0`, pinning the leak to that `run_index`.
- **Simulation mode:** `DEV_SIMULATE=1` runs never spawn the lid worker, so no instrumentation fires — by design (study Experiment 2).

---

## 5. Log Output Reference

All lines are emitted by the `lid_heater` logger (`logs/lid_heater/lid_heater_logger.log`) except `RUN START` / `LID JOIN DONE`, which use the `sentri` logger (`logs/logger.log`).

| Line | Logger | Meaning |
|------|--------|---------|
| `LID WORKER START tid=… live=N` | lid_heater | A worker registered; `N` live workers now exist |
| `LID WORKER EXIT tid=… live=N` | lid_heater | A worker deregistered; `N` remain |
| `lid AIN0: V (read Ns) tid=…` | lid_heater | One ADC read; `read Ns` > 5 s explains a join timeout |
| `GPIO21 HIGH tid=… v=…` (DEBUG) | lid_heater | Heater commanded on; multiple interleaved `tid`s = over-driven |
| `RUN START index=I` | sentri | Run `I` began (run counter for this process) |
| `LID JOIN DONE run_index=I thread_still_alive=B lid_live=N` | sentri | Post-join leak check; `True`/`N>0` = leak pinned to run `I` |

**Reading it:** healthy run = `START live=1` … `EXIT live=0`. Leak = `START live=1`, `START live=2`, … with no matching `EXIT`; the `tid` of a START with no EXIT is the leaked thread.

---

## 6. Calibration

Not applicable — no calibration values introduced. Lid bounds remain in `config_files/lid_heater_config.json` (unchanged).

---

## 7. Failure Modes

| Failure | Symptom | Cause | Recovery |
|---------|---------|-------|----------|
| Lid-thread leak | `live=N` climbs across runs, no matching `EXIT`; `LID JOIN DONE thread_still_alive=True` | ADC read stalls > 5 s → join times out → next run's shared-event `clear()` revives the abandoned worker | Power-cycle (kills process). Root-cause fix deferred to follow-up per study scope |
| I2C bus contention | `read Ns` durations rising, ADC `Hickup` warnings | Multiple leaked workers hitting the lockless `adc` singleton | Same as above |

---

## 8. Known Limitations

- The counter tracks **lid workers only** — it does not see executor or stop-monitor threads (those are covered by `snapshot_resources.py`, issue #160).
- Instrumentation **observes**, it does not fix: a confirmed leak still requires the follow-up remediation (per-run Event + ADC lock).
- `DEBUG`-level `GPIO21 HIGH` lines are silent unless the lid logger is at DEBUG (it is, per `LID_HEATER_LOGGING_CONFIG`).

---

## 9. Testing in Simulation Mode

The diagnostic core is hardware-free and fully unit-tested; the hardware wiring is Pi-only.

- **Unit (any machine):** `sentri_lib/lid_worker_metrics.py` — `enter`/`exit`/`live_count`/`live_tids` including concurrency and double-exit safety. Test file: `tests/unit/test_lid_worker_metrics.py` (7 tests, `-m unit`).
- **Cannot be simulated:** the GPIO/ADC logging inside `lid_heater_worker` (imports `RPi.GPIO` + I2C). Test file: `tests/unit/hardware/test_lid_worker_instrumentation.py`, marked `@pytest.mark.hardware` — run on device: `pytest tests/unit/hardware/test_lid_worker_instrumentation.py -m hardware`.

Run units: `pytest tests/unit/test_lid_worker_metrics.py -v`

---

## 10. Related

- Parent study: `specs/analysis/sentri-self-cancel-study.md` (§5 instrumentation, H1 hypothesis)
- Issue: #157 (this work); downstream consumers: #158 (`scan_cancel_logs.py` reads these lines), #162 (runbook)
- Source: `sentri_lib/lid_worker_metrics.py`, `sentri_lib/regulate.py` (`lid_heater_worker`), `state_run_assay.py` (`run`, `hw_deinitialize`)

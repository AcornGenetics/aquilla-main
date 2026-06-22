# Sentri Test Suite — Overarching Tests

Organized by functional area. Each test references the relevant source file(s) and describes what to assert.

---

## Testing Layers

Tests are organized into 5 layers from fastest/cheapest to slowest/most expensive. Run lower layers on every commit, higher layers on schedule or before release.

---

### Layer 1 — Hardware Simulation (Unit Tests)
**Runs on any machine. No Pi required. All hardware mocked.**

| Test | Mock needed | What to assert |
|---|---|---|
| Carousel moves correct steps to reach position 0–5 | Mock GPIO step/dir pins | Step count matches expected value per position |
| Carousel home detection stops movement | Mock HOME_PIN going HIGH mid-move | `home()` returns after flag detected, position = 0 |
| Thermal ramp sends correct setpoint to MeerStetter | `DummyMeer` | `change_setpoint()` called with correct temp at each ramp step |
| Thermal hold duration correct | `DummyMeer` | `log()` called with correct `endtime` for dwell |
| Thermal ramp ±0.5°C accuracy | `DummyMeer` tracking setpoints | All setpoints within 0.5°C of target |
| Optics FAM channel configuration | Mock SPI | Correct channel bits set when `set_channel_dye("fam")` called |
| Optics ROX channel configuration | Mock SPI | Correct channel bits set when `set_channel_dye("rox")` called |
| Optics parses known ADC buffer correctly | Mock SPI returning fixed bytes | `capture_blink()` produces expected float value |
| Lid heater engages at run start | Mock GPIO, mock ADC below threshold | GPIO pin goes HIGH when temp below `lower_bound` |
| Lid heater disengages above upper bound | Mock ADC above threshold | GPIO pin goes LOW |
| Lid heater pauses during optics (quiet event) | `quiet_event.set()` | GPIO not toggled while quiet event is set |
| Lid heater stops on stop event | `stop_event.set()` | Thread exits cleanly within 1s |
| Drawer open moves to correct step count | Mock GPIO | `open_steps` reached, position matches config |
| Drawer read moves to read position, not open | Mock GPIO | `read_steps` used, not `open_steps` |
| Fan turns on at init | Mock GPIO | GPIO pin set HIGH in `__init__` |
| Stop event halts thermal engine at next iteration | `stop_event.set()` before engine loop | `RunStopped` raised, no further setpoints sent |
| `RunStopped` does not write results | Mock `results_to_json` | Not called when `run_aborted=True` |
| `RunStopped` does not append history | Mock `log_history` | Not called when `run_aborted=True` |

**Existing coverage:** `unit_tests/test_meer_log_stop.py`, `unit_tests/test_force_stop.py`, `pcr_curve_tests/`

---

### Layer 2 — FastAPI Contract Tests (Integration)
**Backend running via `TestClient`. No hardware required.**

| Test | Endpoint | What to assert |
|---|---|---|
| All expected endpoints exist | All routes | Return 200 or documented status, not 404 |
| Run with missing profile returns `ok: false` | `POST /button/run` | Returns 200 with `{"ok": false}`, not 500 |
| Run with empty run name returns `ok: false` | `POST /button/run` | Returns 200 with `{"ok": false}` |
| Run with drawer open returns `ok: false` | `POST /button/run` | Returns 200 with `{"ok": false}` |
| `/results` returns correct schema | `GET /results` | `{"1": {"1": str, "2": str, "3": str, "4": str}, "2": {...}}` |
| Result values are only valid enum members | `GET /results` | Each value is `"Detected"`, `"Not Detected"`, or `"Inconclusive"` |
| `/button_status` returns all required keys | `GET /button_status` | All flags present: `run_requested`, `stop_requested`, `exit_button_status`, etc. |
| `/profiles` returns a list | `GET /profiles` | Response is a JSON array |
| Invalid profile ID returns 404 not 500 | `GET /profiles/details?id=nonexistent` | 404 response |
| Path traversal blocked on results | `GET /results/by-path?path=../../etc/passwd` | 400 or 404, not file contents |
| History append produces valid JSON | `POST /history/append` then `GET /history/data` | history.json parseable, entry present |
| Refactored endpoint still returns same schema | Any modified endpoint | Contract test catches breaking change before merge |

**Existing coverage:** partial in `unit_tests/test_force_stop.py`, `unit_tests/test_results_to_json_path.py`, `test_result_consistency.py`

---

### Layer 3 — State Machine Safety Tests (Integration)
**Backend + mocked hardware app. Verifies safety rules cannot be bypassed.**

| Test | What to assert |
|---|---|
| Cannot press Run while drawer is open | `drawer_state_open=True` → `/button/run` returns `ok: false` |
| Cannot press Run with no profile selected | `selected_profile=None` → `/button/run` returns `ok: false` |
| Cannot open drawer mid-run | Drawer open button has no effect while `screen="running"` |
| Abort returns to ready, not error state | After stop, `current_item.screen` becomes `"ready"`, not `"-1"` |
| Two stop presses don't crash | Rapid double-press of stop is idempotent |
| Exit requires confirmation | First exit press → screen `-5`; second press → `_exit_kiosk()` called |
| Force exit bypasses confirmation | Single force exit press → `_exit_kiosk()` called immediately |
| State after drawer open returns to ready | After open/close sequence, screen returns to `"1"` |
| Screen never stuck after any button sequence | All button combinations eventually resolve to a known screen |
| Power-cycle mid-run recovery | Backend restart clears `run_requested`, `stop_requested`, all in-memory flags |
| `run_complete_ack` does not carry over to next run | Flag is `False` at start of every new run |

**Existing coverage:** partial in `unit_tests/test_force_stop.py`

---

### Layer 4 — Full Workflow / Golden Path (End-to-End)
**Complete simulated run using `DEV_SIMULATE=1` or mocked hardware. Must pass before any PR merges.**

| Test | What to assert |
|---|---|
| Load profile → select → run → complete → results | Full cycle completes without error, results JSON written |
| Results appear on screen without user action | Frontend transitions to complete screen and loads results automatically |
| Results match optics fixture file | Known optics log produces known Detected/Not Detected/Inconclusive outputs |
| Run saved to history with correct metadata | History entry has correct profile, run_name, tube_names, graph_path |
| Fluorescence plot generated and accessible | PNG exists at `graph_path`, GET returns 200 with image |
| Next run name incremented after completion | After ack, run name input shows `run{N+1}` |
| Second run after first completes cleanly | No stale state from first run affects second run |
| Stop mid-golden-path → no results, no history | Stopping a run produces no history entry and no results file |
| Inconclusive signal injection | Inject borderline optics data → result is `"Inconclusive"`, not crash |

**Existing coverage:** none

---

### Layer 5 — UI Regression (Playwright / Cypress)
**Drives real Chromium kiosk against running frontend. Runs on schedule, not every commit.**

| Test | What to assert |
|---|---|
| Ready screen appears on boot | `h2` "Start Run" visible, run button enabled |
| Profile dropdown populates | At least one profile option in `<select>` |
| Profile selection updates labels | FAM/ROX label text changes after selecting a profile |
| Run button disabled with no profile | `run-cta` has `disabled` attribute when no profile selected |
| Drawer open warning appears | "Drawer is open" text visible when drawer state is open |
| Result dots render correct colors | After simulated run, dot CSS matches `#fc6002` (detected), `#c2f282` (not detected), `#f2c97d` (inconclusive) |
| Default dot color is purple | Before any run, dots show `#8b5cf6` |
| History screen shows completed run | After run, history page lists entry with correct run name |
| Fluorescence plot renders in history | `<img>` in history detail has non-zero dimensions and no broken image icon |
| Done modal appears on run complete | Modal visible when screen transitions to "complete" |
| Done modal dismisses and returns to ready | Clicking close → modal gone, screen returns to ready |
| Timer increments during run | Timer display value increases by 1 each second during running state |
| Timer resets after run complete ack | Timer shows "0:00" at start of next run |

**Existing coverage:** none

---

### Bonus Tests

| Test | Layer | What to assert |
|---|---|---|
| **Polling heartbeat** | 2 | Hardware app fires GET `/button_status` within 500ms; if backend down for 1.5s, app logs warning and retries, does not crash or enter unknown state |
| **OTA update smoke test** | 4 | Simulate Watchtower pulling new image → containers restart → device returns to ready screen → run history intact → no flags stuck True |
| **Inconclusive signal injection** | 1+4 | Inject optics data with signal at detection boundary → result is `"Inconclusive"` not `"Detected"` or crash |
| **1-tube run** | 4 | Run with only tube 1 loaded → result only for tube 1, others show "Not Detected" or empty |
| **6-tube run** | 4 | All 6 positions captured → 6 results in output |
| **Non-contiguous tubes** | 4 | Tubes in positions 1, 3, 5 only → correct per-tube results, no index errors |
| **Backend down during run** | 3 | Backend restart mid-thermal-cycle → hardware app reconnects and run completes or aborts cleanly |
| **Malformed profile JSON** | 2 | Profile with missing `steps` key → clear error, run blocked, no crash |
| **Very long run name** | 2 | 500-character run name → `_safe_name()` truncates safely, file created without error |
| **Concurrent profile edits** | 2 | Two clients select different profiles simultaneously → last write wins, no corruption |

---

## 1. Button Functionality

**Source:** `state_run_assay.py`, `sentri_web/main.py`, `sentri_web/static/script.js`

| Test | What to assert |
|---|---|
| Run button with no profile selected | Screen changes to error screen 4, run does not start |
| Run button with valid profile | `run_requested` flag set, state transitions to running |
| Stop button during run | `stop_requested` flag set, `_monitor_stop_request` thread signals stop event |
| Stop button outside run | No state change, no crash |
| Exit button (first press) | Screen changes to -5 (confirm screen), run does not exit |
| Exit button (second press / confirm) | `_exit_kiosk()` called, screen changes to -4 |
| Force exit button | `force_exit` flag set, `_exit_kiosk()` called immediately without confirmation |
| Drawer open button | `drawer_open_status` set, screen transitions to 6 then 1 |
| Drawer close button | `drawer_close_status` set, screen transitions to 7 then 1 |
| Run complete ack button | Screen returns to ready, `run_complete_ack` cleared |
| Button state cleared after handling | All button flags reset after state machine consumes them |

---

## 2. Exit GUI (Docker vs Native)

**Source:** `state_run_assay.py:_exit_kiosk()`, `fleet-config/docker-compose.yml`

| Test | What to assert |
|---|---|
| `KIOSK_CONTROL_URL` env var used | `_exit_kiosk()` calls `{KIOSK_CONTROL_URL}/exit-kiosk`, not hardcoded `127.0.0.1` |
| kiosk-control reachable | HTTP POST to `/exit-kiosk` returns 200, function returns without fallback |
| kiosk-control unreachable | Falls back to running `exit_kiosk.sh` subprocess |
| `exit_kiosk.sh` runs correctly | `pkill chromium` is called (native, non-Docker) |
| Docker: host.docker.internal resolves | `KIOSK_CONTROL_URL=http://host.docker.internal:9191` reaches host service |

---

## 3. Drawer State Synchronization

**Source:** `state_run_assay.py`, `sentri_web/main.py`, `sentri_lib/motor_class.py`

| Test | What to assert |
|---|---|
| Open drawer command | `Drawer.open()` called, hardware moves to `open_steps`, UI state updated |
| Close drawer command | Hardware moves to home, UI `drawer_state_closed` set |
| Drawer read position | `Drawer.read()` moves to `read_steps`, not open position |
| Drawer state mismatch recovery | If hardware and UI state differ, state is reconciled without crash |
| Open during run blocked | Drawer open is not triggered mid-thermal-cycle |

---

## 4. Run Lifecycle State Machine

**Source:** `state_run_assay.py`, `application.py`

| Test | What to assert |
|---|---|
| Full run happy path | State transitions: ready → run → end → ready |
| Run stopped mid-cycle | `RunStopped` exception raised, thermal engine halts, results not written as complete |
| Run with hardware failure | Exception caught, error screen displayed, hardware deinitialized |
| Profile not found | Error screen shown before run starts |
| `hw_deinitialize()` always called | Even if run raises exception, thermal controller is disabled |
| Thread cleanup on exit | All threads (executor, lid heater, stop monitor) join within timeout |

---

## 5. Thermal Cycling Engine

**Source:** `sentri_lib/thermal_engine.py`, `sentri_lib/thermal_parser.py`

| Test | What to assert |
|---|---|
| Profile parsed correctly | Steps array produces correct sequence of setpoints, holds, enables, repeats |
| Ramp timing calculated | Ramp duration = `abs(delta_temp) / ramp_rate`, within tolerance |
| Nested repeats flattened | Inner/outer repeat counts multiply correctly |
| Stop event halts engine | `stop_event.set()` mid-cycle raises `RunStopped` at next iteration |
| Optics callback triggered | `callback("optics")` called at correct cycle step |
| Fan callback triggered | `callback("fan_on")` / `callback("fan_off")` called at correct steps |
| Enable/disable actions sent | `output_stage_enable(True/False)` called at correct steps |
| Temperature setpoints sent | `change_setpoint(temp)` called with correct value for each step |

---

## 6. Optics / ADC Data Capture

**Source:** `sentri_lib/adc_class.py`, `state_run_assay.py:read_wells()`

| Test | What to assert |
|---|---|
| FAM channel capture | Correct SPI channel bits set for FAM, LED toggled correctly |
| ROX channel capture | Correct SPI channel bits set for ROX, LED toggled correctly |
| All 6 positions captured | `read_wells()` generates capture tasks for positions 0-5 |
| Data logged to file | Capture writes row to optics log with cycle, position, dye, value |
| ADC config written on init | SPI registers for control, filter, and channel configured |
| Capture during wrong position blocked | Axis at wrong position raises error or logs warning |

---

## 7. Curve Analysis & Results

**Source:** `sentri_curve/curve.py`, `sentri_lib/plot_utils.py`, `sentri_web/main.py`

| Test | What to assert |
|---|---|
| Detected result | Known optics log with strong signal → result = "Detected" |
| Not Detected result | Known optics log with no signal → result = "Not Detected" |
| Inconclusive result | Borderline signal → result = "Inconclusive" |
| Results JSON structure | Output contains correct keys: well results for all 4 tubes, FAM and ROX |
| Plot generated | PNG file created, non-zero file size |
| Malformed optics log | Raises exception or returns empty result, does not crash app |
| Empty optics log | Handled gracefully, all tubes return "Inconclusive" or known fallback |

---

## 8. Web API Endpoints

**Source:** `sentri_web/main.py`

### Button endpoints

| Test | Endpoint | Assert |
|---|---|---|
| POST `/button/run` with profile | `run_requested=True`, `profile` stored | |
| POST `/button/run` without profile | Returns 200, `run_requested` not set or error state |
| POST `/button/stop` | `stop_requested=True` |
| POST `/button/exit` | `exit_button=True` |
| POST `/button/exit/force` | `force_exit=True` |
| POST `/button/open` | `drawer_open=True` |
| POST `/button/close` | `drawer_close=True` |
| GET `/button_status` | Returns all flags as JSON with correct keys |

### Profile endpoints

| Test | Endpoint | Assert |
|---|---|---|
| GET `/profiles` | Returns list of profiles from disk |
| POST `/profiles` with valid payload | Profile saved to disk, returned ID usable |
| GET `/profiles/details?id=X` | Returns `fam_label`, `rox_label`, `steps` |
| POST `/profiles/delete` | Profile removed from disk |
| POST `/profiles` with invalid JSON | Returns 4xx, no crash |

### History endpoints

| Test | Endpoint | Assert |
|---|---|---|
| GET `/history/data` | Returns array (empty or populated) |
| POST `/history/append` | Entry added to history.json |
| POST `/history/delete` | Specified entries removed, others intact |
| POST `/history/clear` | history.json empty after call |

### Screen & Timer

| Test | Endpoint | Assert |
|---|---|---|
| POST `/change_screen/{state}` valid | Screen updates to new state |
| POST `/change_screen/{state}` invalid | Returns 4xx or no-op, no crash |
| POST `/timer` start | Timer running flag set |
| POST `/timer` stop | Timer stopped |
| POST `/timer` reset | Elapsed time = 0 |

---

## 9. Configuration Loading

**Source:** `config.py`, `sentri_lib/config_module.py`

| Test | What to assert |
|---|---|
| Valid hostname in `host_config.json` | Returns correct per-device config (pins, steps, etc.) |
| Hostname not in config | Falls back gracefully or raises informative error |
| `CONFIG_DIR` env var respected | Config loaded from env-specified path, not hardcoded |
| Malformed JSON | Exception raised with descriptive message |
| Missing required key | Exception identifies missing field by name |
| `get_src_basedir()` resolution | Returns correct path from env, config, and default fallback in order |

---

## 10. Lid Heater Control

**Source:** `sentri_lib/regulate.py`

| Test | What to assert |
|---|---|
| Heater turns on below lower bound | GPIO pin set HIGH when ADC reads below threshold |
| Heater turns off above upper bound | GPIO pin set LOW when ADC reads above threshold |
| Stop event halts worker thread | `stop_event.set()` causes thread to exit cleanly |
| Quiet event pauses heater | While `quiet_event` is set, GPIO not toggled |
| Config loaded from JSON | `lower_bound` / `upper_bound` read from `lid_heater_config.json` |
| ADC read failure handled | Exception caught, retried or logged, does not crash thread |

---

## 11. Motor / Hardware Positioning

**Source:** `sentri_lib/motor_class.py`

| Test | What to assert |
|---|---|
| Home returns to zero | After `home()`, position counter is 0 |
| `move_abs_wo_home_flag()` reaches target | Position equals requested target after move |
| `goto_position(N)` maps to correct well | Position matches expected step count for wells 0–5 |
| Home flag detected | Mock GPIO HOME_PIN triggers stop mid-move |
| Out-of-bounds position | Raises exception or clamps to valid range |
| Step count accumulation | Multiple sequential moves track cumulative position correctly |

---

## 12. Simulation Mode

**Source:** `sentri_web/main.py:_simulate_run()`, `_simulate_drawer()`

| Test | What to assert |
|---|---|
| `AQ_DEV_SIMULATE=1` enables sim | API calls trigger simulation paths, not hardware |
| Sim run uses optics file | Results generated from `DEV_OPTICS_PATH` file |
| Stop during sim run | `stop_requested` flag halts `_simulate_run()` before completion |
| Sim drawer open/close | 3-second delay, then drawer state updated correctly |
| Sim appends to history | History entry created after sim run completes |

---

## 13. Frontend UI State

**Source:** `sentri_web/static/script.js`

| Test | What to assert |
|---|---|
| Screen "ready" shows correct sections | Run panel visible, results panel hidden |
| Screen "running" shows correct sections | Timer visible, run button disabled |
| Screen "complete" shows correct sections | Results panel visible, timer stopped |
| Timer increments each second | After start, displayed value increases by 1 every second |
| Timer resets to 0:00 | After reset, display shows "0:00" |
| Error screens display message | Screens -1, -2, -3, -4, -5 show appropriate text |
| Tube names load from localStorage | On page load, saved names populate inputs |
| Tube names saved on edit | Blur event on input triggers POST to `/tube_names` |

---

## 14. Results Display

**Source:** `sentri_web/static/script.js`, `sentri_web/static/run.html`

| Test | What to assert |
|---|---|
| Detected result shows correct dot color | Dot for affected tube is orange (`#fc6002`) |
| Not Detected shows correct dot color | Dot is green (`#c2f282`) |
| Inconclusive shows correct dot color | Dot is yellow (`#f2c97d`) |
| Default (pre-run) dot color | Dot is purple (`#8b5cf6`) |
| Results summary text updates | Summary line reflects correct count and tube names |
| Tube labels shown in results | Custom tube names appear under each dot |

---

## 15. History Page

**Source:** `sentri_web/static/history.html`, `sentri_web/main.py`

| Test | What to assert |
|---|---|
| History loads on page open | GET `/history/data` called, entries rendered |
| Delete selected entries | Selected entries removed, remaining entries intact |
| Clear all history | All entries removed, empty state shown |
| Entry click shows results | Detail view opens with correct results and plot |
| History entry shows correct timestamp | Stored timestamp matches display |

---

## 16. Error Handling & Recovery

**Source:** `application.py`, `state_run_assay.py`, `sentri_web/main.py`

| Test | What to assert |
|---|---|
| Serial port not found | Descriptive exception logged, error screen shown |
| GPIO access denied | Exception caught, not a silent failure |
| SPI bus failure | ADC capture fails gracefully, run aborted cleanly |
| Optics log file not writable | Exception caught before run starts, user notified |
| Run thread crash | Main thread catches exception, error screen shown, hardware disabled |
| `hw_deinitialize()` on exception | Thermal controller disabled even if run raises mid-cycle |
| Zombie thread cleanup | All child threads terminate within 10s of stop event |

---

## 17. Deployment / Container Health

**Source:** `fleet-config/docker-compose.yml`, `sentri_web/main.py`

| Test | What to assert |
|---|---|
| `/health` endpoint returns 200 | Container healthcheck passes within `start_period` |
| Backend healthy before app starts | `sentri-app` does not start until `sentri-backend` is healthy |
| Watchtower scans correct containers | Only labeled containers (`watchtower.enable=true`) updated |
| `KIOSK_CONTROL_URL` set in app container | Env var present and points to `host.docker.internal:9191` |
| Container restarts on failure | `restart: unless-stopped` causes recovery after crash |

---

## 18. Security Boundaries

**Source:** `sentri_web/main.py`, `state_run_assay.py`

| Test | What to assert |
|---|---|
| Run name sanitized | Special characters in run name do not affect file paths (see `_safe_name()`) |
| Results path not traversable | `/results/by-path?path=../../etc/passwd` returns 400 or 404 |
| Tube names not injected into DOM | XSS characters in tube name labels are escaped |
| Profile names sanitized | Profile name with `../` does not write outside profiles dir |

---

## 19. Seam Tests — Data Handoffs Between Components

These tests verify that data flows correctly *between* subsystems. Each seam is a point where a silent failure could cause results, history, or state to diverge without any visible error.

---

### Seam A: Results File → Frontend Display

**Source:** `state_run_assay.py:258-259`, `sentri_web/main.py:510-523`, `script.js:731`

| Test | What to assert |
|---|---|
| Results file exists before `mark_results_ready()` | File is fully written to disk before POST `/results/path` is called |
| `/results` returns parseable JSON | Response is valid JSON with correct `{row: {col: value}}` structure |
| Results on screen match file on disk | Frontend-rendered values identical to what's in `results.json` |
| Race condition: frontend requests before file written | `/results` returns 404 or "not ready", not a 500 or empty object |
| Results path not overwritten mid-display | Second run starting does not clear first run's displayed results before ack |
| Results cleared after run complete ack | After ack, `/results/status` returns not-ready |

---

### Seam B: Results → History Entry Consistency

**Source:** `state_run_assay.py:269`, `sentri_web/main.py:630-659`

| Test | What to assert |
|---|---|
| History entry `results_path` points to same file shown on screen | Path stored in history.json resolves to the same JSON rendered in the UI |
| History entry created after results file written | `/history/append` is never called before `results_to_json()` completes |
| History results match run-time results | Loading history entry shows same Detected/Not Detected/Inconclusive as original run |
| History entry `tube_names` match labels shown at run completion | Names in history match what was displayed in results panel |
| Concurrent runs don't share history entry | Two simultaneous runs produce two distinct history entries with correct paths |
| history.json remains valid JSON after append | File is valid and parseable after any number of appends |

---

### Seam C: Run Completion → Screen Transition → Ack

**Source:** `state_run_assay.py:254-270`, `script.js:365-404`, `sentri_web/main.py:540-550`

| Test | What to assert |
|---|---|
| Screen transitions to "complete" after run ends | Backend emits `screen="complete"` via WebSocket before results are displayed |
| Results panel populates on "complete" screen | Frontend fetches and renders results immediately on receiving "complete" state |
| Run complete modal appears | Modal is shown when screen = "complete" and `runDoneAcknowledged` is false |
| POST `/run/complete/ack` sent on modal close | Network request fires when user dismisses modal |
| Hardware unblocks after ack | `button_logic` exits waiting state after ack received |
| `run_complete_ack` reset after handling | Flag is False before next run starts |
| Browser refresh on "complete" screen | Ack not re-sent on reload; results still visible |

---

### Seam D: Profile Selection → Run → Results Label Matching

**Source:** `script.js:967-981`, `sentri_web/main.py:878-883`, `state_run_assay.py:164-167`

| Test | What to assert |
|---|---|
| Selected profile is the one used for the run | `thermal_profile` in hardware matches `selected_profile` in backend at run start |
| Profile FAM/ROX labels appear in results | Labels fetched from `/profiles/details` are applied to result dot display |
| Profile deleted after selection but before run | Run fails with clear error, not a silent wrong-profile run |
| Profile labels in history match profile at run time | History entry reflects labels from the profile used, not a later-edited version |
| Profile with no labels falls back gracefully | Default "FAM" / "ROX" labels used, no crash |

---

### Seam E: Tube Names → Run → History

**Source:** `script.js:65-88`, `sentri_web/main.py:572-581`, `state_requests.py:70-75`

| Test | What to assert |
|---|---|
| Tube names at run time are captured in history | Names edited before run match names stored in history entry |
| Tube names edited mid-run not captured | Names changed during a run do not affect the in-progress history entry |
| History tube names shown in results view | Clicking a history entry shows tube labels matching history record, not current labels |
| Backend tube names sync from frontend | POST `/tube_names` updates backend global before run is triggered |
| Tube name fetch failure during history append | Defaults used, not a crash or missing history entry |

---

### Seam F: Run Name → History → Next Run Increment

**Source:** `sentri_web/main.py:150-170`, `state_run_assay.py:270`, `script.js:617-628`

| Test | What to assert |
|---|---|
| Run name in history matches name shown at run time | `run_name` stored in history.json equals what was displayed in the UI |
| Next run name increments after completion | After `advance_run_name()`, `/run/name` returns `run{N+1}` |
| Next run name is unique across history | No two history entries share the same `run_name` |
| Custom run name preserved in history | Non-default run name (e.g. "patient_001") stored and displayed correctly |
| Increment survives restart | After container restart, next run name does not reset to "run1" |

---

### Seam G: Plot Path → History → Image Display

**Source:** `state_run_assay.py:194-195, 265-266`, `sentri_web/main.py:651`, history page

| Test | What to assert |
|---|---|
| Plot file created before `graph_path` stored in history | Image file exists at the path recorded in history.json |
| `graph_path` in history is a valid web URL | `GET {graph_path}` from browser returns 200 with image content |
| Plot image in history matches run that generated it | Image displayed in history entry corresponds to the correct run's optics |
| Plot generation failure does not block history append | History entry created even if plot fails; `graph_path` is null/empty |
| Concurrent runs produce distinct plot files | Two runs do not overwrite each other's plot |

---

### Seam H: Screen State → Timer → Elapsed Time

**Source:** `sentri_web/main.py:1192-1204`, `script.js:419-529`

| Test | What to assert |
|---|---|
| Timer starts when screen transitions to "running" | Elapsed time begins incrementing at run start, not before |
| Timer stops when screen transitions to "complete" | Elapsed time freezes at run end |
| Timer value in WebSocket matches wall clock | Elapsed seconds within ±2s of actual run duration |
| Timer resets on new run | Elapsed time is 0 at start of next run |
| Rapid screen changes don't cause negative elapsed | No negative timer values if state flips quickly |

---

### Seam I: Stop Button → Thermal Engine Halt → Results Not Written

**Source:** `state_run_assay.py:_monitor_stop_request()`, `sentri_lib/thermal_engine.py`, `state_run_assay.py:230-271`

**Known bug:** Stop works (run halts) but UI freezes on the running screen until Reset is pressed. Root cause: `drawer.open()` in the `finally` block (line 249) is a blocking motor movement. `sr.change_screen("1")` at line 254 only executes *after* the drawer finishes opening. If `drawer.open()` is slow or raises an exception, the screen never transitions back and the UI appears frozen.

| Test | What to assert |
|---|---|
| Stop mid-run raises `RunStopped` | Thermal engine exits loop when stop event is set |
| Results file not written after stop | `results_to_json()` is not called when `run_aborted=True` |
| History not appended after stop | No `/history/append` call made for a stopped run |
| Screen does not show "complete" after stop | UI never shows run complete modal when stop was pressed |
| Stop button re-arms for next run | `stop_requested` flag is False before next run starts |
| **Screen transitions to ready within 5 seconds of stop** | **`change_screen("1")` is called within 5s regardless of drawer state — regression test for the freeze bug** |
| **`drawer.open()` exception does not freeze screen** | **If drawer motor fails during stop cleanup, `change_screen("1")` is still called** |
| **UI leaves "running" state immediately on stop, not after drawer opens** | **Screen changes to a transitional or ready state before drawer movement completes** |
| **Reset button returns to ready from frozen running screen** | **If screen is stuck on "running", reset navigates back to screen "1"** |
| **Consecutive stop → new run works without restart** | **After a stopped run, a new run can be started without rebooting the device** |

---

### Seam J: Docker Container Restart → State Recovery

**Source:** `fleet-config/docker-compose.yml`, `sentri_web/main.py`

| Test | What to assert |
|---|---|
| Results from previous run still accessible after restart | `/history/data` returns entries from before container restart |
| In-progress run on restart shows error screen | Run that was mid-cycle when container restarted does not show "complete" |
| Tube names survive container restart | Tube names persisted on disk are loaded on startup |
| `run_complete_ack` not stuck True after restart | Flag resets to False on backend startup |
| `selected_profile` cleared on restart | Stale profile selection from previous session not carried over |

---

## 20. GUI → State → Hardware Translation Tests

These tests verify that a user action in the UI actually propagates all the way through to the backend flag, gets picked up by the hardware polling loop, and produces a real hardware effect. Each layer can silently absorb a failure without the user knowing.

The full chain for every button is:
```
User clicks button (browser)
  → JS fetch POST to backend (~10-50ms)
    → Backend global flag set
      → Hardware polls /button_status every 500ms (worst case +500ms latency)
        → Hardware action executes
          → Hardware POSTs state update back to backend
            → WebSocket broadcasts new state to frontend (~1s)
              → UI reflects result
```

---

### GUI → Backend Flag Translation

| Test | What to assert |
|---|---|
| Run button click sets `run_requested=True` | GET `/button_status` immediately after click returns `run_requested: true` |
| Stop button click sets `stop_requested=True` | GET `/button_status` immediately after click returns `stop_requested: true` |
| Open drawer click sets `drawer_open=True` | GET `/button_status` returns `drawer_open_status: true` |
| Close drawer click sets `drawer_close=True` | GET `/button_status` returns `drawer_close_status: true` |
| Exit button click sets `exit_button=True` | GET `/button_status` returns `exit_button_status: true` |
| Force exit sets `force_exit=True` | GET `/button_status` returns `force_exit: true` |
| Profile selection sets `selected_profile` | GET `/button_status` returns correct profile ID |
| Run name entry sets `run_name` | GET `/button_status` returns the typed run name |
| All flags reset after hardware consumes them | After hardware polls and acts, all flags return to False on next GET |

---

### Backend Flag → Hardware Polling Detection

| Test | What to assert |
|---|---|
| Run flag detected within 500ms | Hardware `wait_for_button()` returns within 1 poll cycle of flag being set |
| Stop flag detected within 500ms | `_monitor_stop_request()` calls `stop_event.set()` within 500ms of flag set |
| Drawer open flag detected within 500ms | `button_logic()` reads `drawer_open=True` on next poll |
| `/button_status` returning 500 error | Hardware retries after 500ms sleep, does not crash |
| `/button_status` timeout (5s) | Hardware logs warning, retries — does not block forever |
| Hardware polls while run is in progress | Stop monitor thread independently polls every 500ms during thermal cycle |
| Flag set and cleared before hardware polls | Hardware misses single-poll-window flag — test that critical flags are not pulse-width sensitive |

---

### Hardware Action → Backend State Update → Frontend Feedback

| Test | What to assert |
|---|---|
| Drawer physically opens → backend state updated | POST `/drawer/state` called with `open=true` after `drawer.open()` completes |
| Drawer state update → WebSocket broadcast | Next WebSocket message includes `drawer_state_open: true` |
| Drawer state → UI warning shown | "Drawer is open" warning appears within 1 WebSocket cycle of drawer opening |
| Screen change → WebSocket → UI renders | `sr.change_screen("2")` → WebSocket → frontend shows running screen within 1s |
| Timer start → frontend timer increments | POST `/timer start` → frontend timer begins incrementing within 1 WebSocket cycle |
| Timer stop → frontend timer freezes | POST `/timer stop` → frontend timer value stops changing |
| Run complete → results loaded automatically | `sr.change_screen("3")` → frontend calls `loadResults()` without user action |
| Run aborted → ready screen without user action | `sr.change_screen("1")` after stop → frontend returns to ready screen automatically |

---

### Run Button: Full Chain Validation

| Test | What to assert |
|---|---|
| Click run with no profile → warning shown, hardware not triggered | Frontend shows warning, `run_requested` never set to True |
| Click run with no run name → warning shown, hardware not triggered | Frontend shows warning before POST, or backend returns `ok: false` |
| Click run with drawer open → warning shown, hardware not triggered | Both frontend and backend validate drawer state before setting flag |
| Click run with valid inputs → screen transitions to "running" within 2s | From click to screen="running" in WebSocket, total latency under 2s |
| `run_requested` cleared after hardware consumes | POST `/run_status/reset` called by hardware, flag returns to False |
| `selected_profile` cleared after run starts | After hardware reads profile from `/button_status`, backend resets it to None |
| Run button disabled while run is in progress | `run-cta` button is disabled on screen="running", cannot trigger double-run |
| Run button re-enabled after run completes | Button is clickable again on screen="ready" after complete cycle |

---

### Stop Button: Full Chain Validation

| Test | What to assert |
|---|---|
| Stop button only visible during run | `stop-run-button` hidden on screen="ready" and "complete" |
| Stop button click → "Stopping…" shown immediately | UI shows stopping message before hardware responds |
| Stop button disabled after click | Cannot click stop twice — button disabled immediately on click |
| Stop button click → thermal engine halts within 1s | `RunStopped` raised within 1 poll cycle (500ms) of `stop_requested=True` |
| Stop button click → screen returns to ready | UI transitions from "running" to "ready" after stop completes |
| Stop button click → screen returns to ready within 30s | Even with slow drawer open, ready screen shown within 30s (regression for freeze bug) |
| Stop during ramp vs stop during hold | Both halt correctly — `stop_event` checked at every thermal engine iteration |
| Stop monitor thread stops after run ends | `stop_monitor_event.set()` terminates thread — no orphan threads after run |
| `stop_requested` cleared after hardware consumes | POST `/stop/reset` called, flag returns to False before next run |

---

### Drawer Buttons: Full Chain Validation

| Test | What to assert |
|---|---|
| Open drawer click → motor physically moves | `drawer.open()` called in hardware `button_logic()` |
| Open drawer click → UI shows "Drawer is open" warning | Warning appears after hardware updates `/drawer/state` and WebSocket broadcasts |
| Close drawer (read) click → motor moves to read position | `drawer.read()` called, not `drawer.close()` — read position ≠ home |
| Drawer state on UI matches physical state | After open: `drawer_state_open=True`, `drawer_state_closed=False` |
| Drawer state prevents run start | If `drawer_state_open=True`, run button click returns `ok: false` |
| Open/close during run blocked | Drawer buttons have no effect while screen="running" |
| Drawer state persists across WebSocket reconnect | After WS disconnect+reconnect, correct drawer state shown immediately |
| Drawer state flag reset after hardware consumes | `drawer_open` and `drawer_close` backend flags reset after `button_logic()` handles them |

---

### Profile Selection: Full Chain Validation

| Test | What to assert |
|---|---|
| Profile selected in dropdown → backend `selected_profile` set | POST `/profile/select` fires on dropdown change, backend stores ID |
| Profile labels load after selection | FAM/ROX labels fetched from `/profiles/details` and applied to dots |
| Profile in hardware matches profile in UI | `thermal_profile` used during run matches `selected_profile` set by user |
| Profile selection lost after run | `selected_profile` cleared after `run_status/reset`, dropdown resets |
| Changing profile mid-ready state updates labels | Selecting different profile replaces previous labels without page reload |
| Profile ID never reaches hardware if run not started | `selected_profile` cleared by reset before hardware can start a second run with stale profile |

---

### Run Name: Full Chain Validation

| Test | What to assert |
|---|---|
| Typed run name → backend `run_name` set | POST `/run/name` fires on input blur, backend stores value |
| Run name stored in history entry matches what was typed | History `run_name` field == value user entered |
| Run name advances after run completes | After `advance_run_name()`, GET `/run/name` returns `run{N+1}` |
| New run name shown in input after completion | Frontend input field updates to next run name after run complete ack |
| Custom run name preserved (not overwritten by auto-advance) | If user typed "patient_001", history stores "patient_001" not "run5" |
| Run name sanitized before use in file paths | `_safe_name()` called — special chars don't create invalid filenames |

---

### WebSocket Disconnection: State Consistency

| Test | What to assert |
|---|---|
| WebSocket disconnect → timer stops updating | Timer freezes on last value when WS closes |
| WebSocket reconnect → correct screen state shown | On reconnect, frontend receives current `current_item.screen` immediately |
| WebSocket reconnect → correct drawer state shown | On reconnect, `drawer_state_open/closed` reflects hardware reality |
| Button clicks still reach backend during WS disconnect | HTTP POSTs to `/button/*` work independently of WebSocket |
| Run completes during WS disconnect | When WS reconnects, screen="complete" detected and results loaded |
| WS disconnect during run → stop button still works | POST `/button/stop` succeeds even without active WebSocket |

---

### Validation Layer Consistency (Frontend vs Backend)

The frontend and backend both validate before allowing a run. They must agree.

| Test | What to assert |
|---|---|
| Frontend validates no profile → backend also rejects | Both layers independently block run with no profile |
| Frontend validates no run name → backend also rejects | Both layers block empty run name |
| Frontend validates drawer open → backend also rejects | Both layers check `drawer_state_open` |
| Frontend passes but backend rejects | `ok: false` response from backend shows warning in UI, run does not start |
| Backend passes but frontend already blocked | Cannot reach backend if frontend validation fails (fetch never called) |
| Validation state stale on frontend | If profile deselected via another session, frontend thinks it's valid but backend rejects — UI handles `ok: false` gracefully |

---

### Screen State: GUI Reflects Hardware Reality

| Test | What to assert |
|---|---|
| Screen 0 (initializing) shown during hardware init | `change_screen("0")` produces visible loading state before "ready" |
| Screen 1 (ready) shown when hardware is ready | UI shows "Ready" state with run button enabled |
| Screen 2 (running) shown during thermal cycle | UI shows timer, stop button, no run button |
| Screen 3 (complete) shown after successful run | UI shows results panel, done modal |
| Screen -1 (hardware error) shown on exception | UI shows error message, not frozen running screen |
| Screen -3 (keyboard interrupt) shown on KeyboardInterrupt | UI shows error state |
| Screen -4 (exiting) shown during exit sequence | UI shows "Closing..." message |
| Screen -5 (exit confirm) shown on first exit press | UI shows confirmation prompt before closing |
| Screen 4 (no profile error) shown when run without profile | UI shows profile error, not crash |
| Screen 6 (drawer opening) and back to 1 | Brief screen change during drawer open then returns to ready |
| Unknown screen code received | Frontend handles gracefully — no crash, no blank screen |

---

## Priority Order for Implementation

| Priority | Area | Reason |
|---|---|---|
| 1 | Web API endpoints (section 8) | Everything depends on these; easiest to test with `TestClient` |
| 2 | Button functionality (section 1) | Core user interaction, already partially covered in `unit_tests/` |
| 3 | Seam C: Run completion → ack (section 19) | Hardware blocks forever if this handoff fails |
| 4 | Seam A & B: Results file → display → history (section 19) | Silent mismatch between what ran and what was recorded |
| 5 | Run lifecycle state machine (section 4) | Highest risk — hardware involved |
| 6 | Exit GUI (section 2) | Known bug, fix already in place, needs regression test |
| 7 | Thermal engine (section 5) | Pure logic, no hardware needed, high safety impact |
| 8 | Seam I: Stop → no results written (section 19) | Stopped run must not produce a fake result |
| 9 | Curve analysis & results (section 7) | Testable with fixture optics files |
| 10 | Seam D & E: Profile + tube names → history (section 19) | Audit trail integrity |
| 11 | Configuration loading (section 9) | Prevents silent wrong-device deploys |
| 12 | Drawer state sync (section 3) | Hardware state/UI mismatch is a known pain point |
| 13 | Frontend UI state (section 13) | Needs browser test runner (e.g. playwright) |
| 14 | All others | After core pipeline is stable |

---

## 21. On-Screen Keyboard

**Source:** `sentri_web/static/keyboard.js`

The kiosk has no physical keyboard. All text input (run names, profile names, WiFi passwords) goes through a custom on-screen keyboard built in `keyboard.js`. If it breaks, the device cannot accept any user input.

| Test | What to assert |
|---|---|
| Keyboard appears on input focus | Tapping any `input[type='text']` element shows `.onscreen-keyboard` in DOM |
| Keyboard hidden when no input focused | `.onscreen-keyboard` not visible on page load |
| Letter key inserts character at cursor | Clicking "a" appends "a" to active input value |
| Backspace removes last character | Backspace key reduces input value length by 1 |
| Space key inserts space | Space key appends " " to active input value |
| Close button dismisses keyboard | Clicking ✕ hides `.onscreen-keyboard`, `activeInput` cleared |
| Keyboard adds body padding when visible | `document.body.style.paddingBottom` set to keyboard height + 24px |
| Padding removed on keyboard dismiss | `paddingBottom` cleared when keyboard hides |
| Physical key press suppresses mouse events | `suppressMouseEvents=true` after physical keydown, prevents duplicate input |
| Physical key debounce respected | Second keydown within `KEY_DEBOUNCE_MS` (50ms) ignored |
| Keyboard does not block run button | Run button remains clickable when keyboard is visible |
| Keyboard works on run name input | Run name field accepts characters from on-screen keyboard |
| Keyboard works on tube name inputs | All 4 tube name inputs accept characters from keyboard |
| Keyboard dismissed on form submit | Keyboard hides when run is started |
| Long input doesn't overflow | 100+ character input handled without visual overflow or crash |

---

## 22. History Detail View

**Source:** `sentri_web/static/history_detail.js`, `sentri_web/static/history_detail.html`

The detail view is a separate page (`/history/run?index=N`) with its own result rendering logic independent of the main run screen. It has its own `summarizeResults()`, Cq value parsing, QC status, and tube pill rendering.

| Test | What to assert |
|---|---|
| Detail view loads correct entry by index | `?index=2` loads the third history entry, not first or last |
| Invalid index shows "Run not found" | `?index=999` or `?index=abc` shows error message, not crash |
| Run information section populated | Date, profile, run name, result text all rendered from history entry |
| Per-tube pills render correct status | Detected → `.run-detail-pill--detected`, Inconclusive → `--inconclusive`, Not Detected → `--not-detected` |
| Tube labels from history shown in pills | Custom tube names from history entry appear in pill text, not defaults |
| Amplification plot image rendered | `<img src="{graph_path}">` present when `graph_path` in history entry |
| No plot → "No graph available" shown | When `graph_path` is null/empty, fallback text shown |
| Detected count KPI correct | "2/4 Detected" matches actual number of detected tubes |
| Inconclusive count KPI correct | Count matches actual inconclusive tubes |
| Avg Ct value calculated correctly | Average of all detected Cq values, rounded to 2 decimal places |
| Avg Ct shows "--" when no detections | No Cq values → KPI shows `--` not NaN or crash |
| QC status "Review" when any inconclusive | `inconclusiveCount > 0` → QC status shows "Review" |
| QC status "Pass" when all definitive | All tubes Detected or Not Detected → QC status shows "Pass" |
| Results loaded via `/results/path` + `/results` | Detail view POSTs to `/results/path` then GETs `/results` to load data |
| Detail result matches list view result | Summary text in history list matches detail view for the same entry |
| `summarizeResults()` logic matches `history.js` | Both files produce identical per-tube status for same input data |
| Failed results load falls back to `entry.result` | If `/results` returns `data.failed`, entry's stored result string used |
| Detail page navigable from history list | "View" link in history list opens detail page for correct entry |

---

## 23. kiosk-control Service

**Source:** `scripts/kiosk-control/kiosk_control.py`

Runs on the host Pi (not in Docker) at `127.0.0.1:9191`. Controls Chromium lifecycle and WiFi. Critical for exit GUI and WiFi management.

| Test | What to assert |
|---|---|
| `/health` returns `{"ok": true}` | GET `/health` returns 200 |
| Request from loopback allowed | `127.0.0.1` passes `_is_allowed()` |
| Request from Docker bridge allowed | `172.17.x.x`, `172.20.x.x`, `10.x.x.x` pass `_is_allowed()` |
| Request from external IP rejected | IP not in `ALLOWED_PREFIXES` → 403 response |
| `/exit-kiosk` kills Chromium process | `pkill -TERM chromium` called, returns `{"ok": true}` |
| `/exit-kiosk` when no Chromium running | Returns `{"ok": true, "message": "no chromium process found"}` — not an error |
| `/start-kiosk` launches Chromium | `subprocess.Popen` called with correct flags including `--kiosk` and `KIOSK_URL` |
| `/start-kiosk` runs as kiosk user | Command uses `sudo -u pi` when running as root |
| Unknown endpoint returns 404 | GET/POST to unregistered path returns 404 |
| SIGTERM shuts down server cleanly | `signal.SIGTERM` triggers `server.shutdown()` without hanging |
| `_nmcli` failure returns error dict | nmcli non-zero exit → error included in response, not exception |
| POST `/wifi/connect` with no SSID returns 400 | Missing `ssid` field → 400, not 500 |
| POST `/wifi/forget` with no SSID returns 400 | Missing `ssid` field → 400, not 500 |
| Service unreachable → `_exit_kiosk()` falls back | `state_run_assay._exit_kiosk()` runs `exit_kiosk.sh` when 9191 unreachable |
| `KIOSK_CONTROL_URL` env var used in app container | Container reads env var, not hardcoded `127.0.0.1` (regression for exit GUI bug) |

---

## 24. Disk Space & Log Management

**Source:** `fleet-config/docker-compose.yml`, `sentri_web/main.py`, `sentri_lib/utils.py`

The Pi has limited SD card storage. Docker logs are capped at 10MB per file, but result files, optics logs, PCR logs, and plots under `/opt/aquila/` grow unbounded with no cleanup logic.

| Test | What to assert |
|---|---|
| Docker container logs respect `max-size: 10m` | Each container's JSON log file does not exceed 10MB |
| Result files accumulate per run | After N runs, N result JSON files exist in `logs/results/` |
| Optics log files accumulate per run | After N runs, N optics log files exist in `logs/optics/` |
| Plot PNG files accumulate per run | After N runs, N PNG files exist in `logs/plots/` |
| Disk full during results write | `results_to_json()` raises `OSError`, error logged, run marked aborted not complete |
| Disk full during optics logging | Write to optics log file fails gracefully, run aborts cleanly |
| Disk full during history append | `_save_history()` fails with `OSError`, existing history.json not corrupted |
| History file not corrupted on partial write | If process killed mid-write, history.json remains valid JSON on next load |
| `/opt/aquila/` volume survives container restart | Files in mounted volume persist after `docker compose restart` |
| Large history file loads without timeout | History with 500+ entries loads from `/history/data` within 5s |
| Run name counter correct after many runs | After 100 runs, `advance_run_name()` produces `run101` without collision |

---

## 25. Concurrent Browser Sessions

**Source:** `sentri_web/main.py`, `sentri_web/static/script.js`

The backend uses global Python variables for all state. Two browser sessions hitting the same backend simultaneously can produce unexpected interactions.

| Test | What to assert |
|---|---|
| Two browsers on ready screen | Both receive same WebSocket state — no crash, no divergence |
| Browser A starts run, Browser B sees running screen | WebSocket broadcast reaches both sessions within 1s |
| Browser A presses stop, Browser B sees state update | `stop_requested` flag set once, hardware stops, both UIs reflect "ready" |
| Browser B cannot start second run while Browser A's run is active | `run_requested` flag already True, second POST returns `ok: false` |
| Browser A edits tube names, Browser B sees updated names | Backend `current_tube_names` updated, WebSocket broadcast reflects change |
| Browser A selects profile, Browser B selects different profile | Last POST to `/profile/select` wins — no crash, backend holds one profile |
| Browser A acks run complete, Browser B also tries to ack | Second ack is idempotent — no crash, state consistent |
| Browser disconnects mid-run | WebSocket close does not affect hardware run or stop monitor thread |
| Browser refreshes during run | Page reload reconnects WebSocket, receives current running state immediately |
| Browser opens on complete screen after run | New session loading during "complete" state sees results without triggering new run |

---

## 26. Profiles UI (Create / Edit / Delete)

**Source:** `sentri_web/static/profiles.html`, `sentri_web/main.py`

The profiles page lets users create and manage test profiles. Profiles drive the entire thermal cycle. A corrupt or missing profile blocks all runs.

| Test | What to assert |
|---|---|
| Profile list loads on page open | All JSON files in profiles directory shown |
| Create profile with valid steps | POST `/profiles` → file written to disk, returned ID loadable |
| Created profile appears in run page dropdown | After creation, new profile visible in `<select>` on run screen |
| Profile name sanitized on save | Special characters → `_`, path traversal stripped (see `main.py:946`) |
| Profile with duplicate name | Second save with same name overwrites first without error |
| Delete profile | Profile removed from disk, no longer in dropdown |
| Delete profile currently selected | Stale `selected_profile` cleared, run blocked until new profile chosen |
| Profile with missing `steps` key | Loaded profile missing required field → clear error shown, run blocked |
| Profile with empty steps array | Zero-step profile → thermal engine produces no actions, run completes immediately |
| Profile FAM/ROX labels stored and retrieved | Labels saved in profile JSON, returned by `/profiles/details` |
| Profile labels displayed in results dots | FAM/ROX labels from profile shown in result dot tooltips/legend |
| Profile file manually deleted on disk | `/profiles` endpoint skips deleted file gracefully, no crash |
| Very long profile name | Truncated or sanitized to valid filename without error |
| Non-ASCII profile name | Sanitized to ASCII-safe filename, stored and loaded correctly |

---

## 27. Hardware Initialization Failures

**Source:** `application.py`, `state_run_assay.py`, `sentri_lib/motor_class.py`, `sentri_lib/meerstetter.py`, `sentri_lib/adc_class.py`

Hardware init happens in `AssayInterface.__init__()`. If any peripheral fails to initialize, the device must show a clear error — not silently boot into a broken state where runs appear to start but produce no results.

| Test | What to assert |
|---|---|
| Serial port not found (MeerStetter) | `serial.SerialException` caught, error screen shown (`-1`), not a crash loop |
| GPIO access denied | `RuntimeError` from RPi.GPIO caught, error screen shown |
| SPI bus unavailable (ADC) | `spidev` init failure caught, error screen shown |
| I2C bus unavailable | I2C device open fails, error logged, error screen shown |
| Axis home never detected | `home()` moves `home_steps` without finding flag — raises exception or times out, not infinite loop |
| Drawer home never detected | Same as axis — bounded movement, not infinite loop |
| MeerStetter not responding after connect | Serial open succeeds but read/write times out — caught, error screen shown |
| Hardware init failure → no run possible | With error screen active, Run button cannot trigger a run |
| Hardware init partial failure | One peripheral fails but others succeed — failure is isolated, logged clearly |
| GPIO cleanup on init failure | `GPIO.cleanup()` called even if `__init__` raises, no pin state leak |
| Device recovers after reboot | After fixing hardware issue and rebooting, device initializes successfully without lingering bad state |

# Hardware Test Protocol

All commands save output to `/opt/aquila/logs/` on the host. Replace `<sn>` with the device serial number (e.g. `sn05`) and `<YYYYMMDD>` with the date.

---

## 1. Motors

### 1a. Drawer Motor

**What it tests:** Physical movement of the sample drawer — homing, opening, positioning.

| Command | Arguments | What it does |
|---------|-----------|--------------|
| `home` | _(none)_ | Moves drawer fully back to home position (0 steps). Sends 5000 steps back, stops at home flag. |
| `open` | _(none)_ | Moves drawer fully open (4500 steps from home). |
| `read` | _(none)_ | Homes first, then moves to read position (~151–160 steps, device-dependent). |
| `steps N` | `N` = integer step count (positive = out, negative = back toward home) | Homes first, then moves `N` steps. Range: 0–4500. |
| `steps N --no-home` | `N` = integer step count | Moves `N` steps from **current** position without homing first. |
| `status` | _(none)_ | Prints current position, home flag state, and all configured limits. No motor movement. |

**Command:**
```bash
docker exec -e PYTHONPATH=/opt/aquila sentri-app python3 scripts/hardware_tests/motor_drawer.py <command> [options] > /opt/aquila/logs/drawer_<command>_<sn>_<YYYYMMDD>.txt 2>&1
```

**Notes:**
- Safety limits are enforced from config: min 0 steps, max 4500 steps.

---

### 1b. Axis Motor

**What it tests:** Lateral positioning of the optics over wells 1–4 for FAM and ROX filters.

| Command | Arguments | What it does |
|---------|-----------|--------------|
| `home` | _(none)_ | Homes the axis (sends 2500 steps back, stops at home flag). |
| `pos N` | `N` = 0–5 (position index) | Homes first, then moves to position index N. Positions: 300, 659, 1018, 1377, 1736, 2095 steps. |
| `well N --dye fam\|rox` | `N` = 1–4 (well number); `--dye fam` or `--dye rox` | Homes, then positions the specified dye filter over well N. |
| `steps N` | `N` = integer step count | Homes first, then moves to absolute position N steps. |
| `steps N --no-home` | `N` = integer (positive or negative) | Moves `N` steps relative to current position without homing. |
| `status` | _(none)_ | Prints all well positions, limits, and current position. No motor movement. |

**Position layout:**

| Position Index | Steps | ROX well | FAM well |
|---|---|---|---|
| 0 | 300 | Well 1 | — |
| 1 | 659 | Well 2 | — |
| 2 | 1018 | Well 3 | Well 1 |
| 3 | 1377 | Well 4 | Well 2 |
| 4 | 1736 | — | Well 3 |
| 5 | 2095 | — | Well 4 |

**Command:**
```bash
docker exec -e PYTHONPATH=/opt/aquila sentri-app python3 scripts/hardware_tests/motor_axis.py <command> [options] > /opt/aquila/logs/axis_<command>_<sn>_<YYYYMMDD>.txt 2>&1
```

---

## 2. ADC (Optical Read)

### 2a. ADC Scan — Logged

**What it tests:** ADC signal across the full axis range for a single dye. Sweeps X from 0 to ~2100 in steps of 20, measuring LED-on and LED-off voltage at each position.

| Argument | Values | What it does |
|----------|--------|--------------|
| `dye` | `fam` or `rox` | Selects which LED and ADC channel to use for the scan. |

**Output columns (stdout, space-separated):**
```
time_s   x_position   dye   [raw_adc_bytes...]   voltage_mV   led_state   avg_on   avg_off   avg_diff
```

**Command:**
```bash
docker exec -e PYTHONPATH=/opt/aquila sentri-app python3 scripts/hardware_tests/test_adc4_logged.py <dye> > /opt/aquila/logs/adc_<dye>_<sn>_<YYYYMMDD>.txt 2>&1
```

**Notes:**
- Script also writes data to an auto-named log file in `/opt/aquila/logs/` via `LogFileName` utility.
- Script pre-homes with a 100-step forward nudge before homing to ensure consistent reference position.
- Scan duration: ~several minutes depending on axis range.

---

## 3. Other Hardware Tests

### 3a. Lid Heater

**What it tests:** Runs the lid heater control loop for up to 60 minutes (3600 iterations), verifying the heater activates and regulates correctly.

**This test requires stopping and restarting the app container.** Run as a one-shot container with `--rm`.

| Argument | Values | What it does |
|----------|--------|--------------|
| _(none)_ | — | No arguments. Runs heater worker in background thread, prints counter to stdout every second. Press Ctrl+C to stop early. |

**Command:**
```bash
docker stop sentri-app && docker run --rm -it --privileged -v /dev:/dev -v /opt/aquila/config:/opt/aquila/config -v /opt/aquila/logs:/opt/aquila/logs -w /opt/aquila -e CONFIG_DIR=/opt/aquila/config -e DEVICE_HOSTNAME=<sn> $(docker inspect sentri-app --format '{{.Config.Image}}') python3 run_lid_heater.py > /opt/aquila/logs/lid_heater_<sn>_<YYYYMMDD>.txt 2>&1 && docker start sentri-app
```

**Notes:**
- Runs for up to 3600 seconds (1 hour) unless interrupted.
- Heater is gracefully shut off on Ctrl+C or at end of run.
- After the run (or Ctrl+C), `docker start sentri-app` restarts the main app.

---

### 3b. LOD Verification — All Wells

**What it tests:** Reads ADC signal at all 4 well positions for a given dye (both LED on and LED off) to verify optical detection limits across wells.

| Argument | Values | What it does |
|----------|--------|--------------|
| `dye` | `fam` or `rox` | Selects dye. FAM uses positions 2–5; ROX uses positions 0–3. Drawer moves to read position first. |

**Output columns (stdout, space-separated):**
```
time_s   dye   position_index   [raw_adc_bytes...]   voltage_mV   led_state
```

**Command:**
```bash
docker exec -e PYTHONPATH=/opt/aquila sentri-app python3 scripts/hardware_tests/lod_verification_all.py <dye> > /opt/aquila/logs/lod_<dye>_<sn>_<YYYYMMDD>.txt 2>&1
```

**Notes:**
- Drawer automatically moves to read position before scanning.
- Opens drawer at end of run.

---

### 3c. LED Current Verification

**What it tests:** Measures LED current (via ADC sense channels) for a single dye over ~60 seconds, cycling LED on/off.

| Argument | Values | What it does |
|----------|--------|--------------|
| `dye` | `fam` or `rox` | FAM uses ADC channels 14/13; ROX uses channels 8/10. Cycles LED on/off ~10 times per second for 60 iterations. |

**Output columns (stdout, space-separated):**
```
time_s   dye   [raw_adc_bytes...]   voltage_mV   led_state
```

**Command:**
```bash
docker exec -e PYTHONPATH=/opt/aquila sentri-app python3 scripts/hardware_tests/led_current_verification.py <dye> > /opt/aquila/logs/led_current_<dye>_<sn>_<YYYYMMDD>.txt 2>&1
```

---

## 4. Raster Scan

**What it tests:** 2D scan sweeping both the axis (X) and drawer (Y) to map the optical signal across the full well area. Used for optics alignment verification.

**This test requires stopping and restarting the app container.** Run as a one-shot container with `--rm`.

| Argument | Values | What it does |
|----------|--------|--------------|
| `dye` | `fam` or `rox` | Selects which dye channel to scan. FAM: axis positions 2–5 range; ROX: positions 0–3 range. |
| `DEVICE_HOSTNAME` | e.g. `sn05` | Sets the device hostname environment variable used by config. Replace with actual serial number. |

**Output columns (stdout, space-separated):**
```
x_position   y_position   signal_diff(on-off)
```

**Command:**
```bash
IMAGE=$(docker inspect sentri-app --format '{{.Config.Image}}') && docker stop sentri-app && docker run --rm -it --privileged -v /dev:/dev -v /opt/aquila/config:/opt/aquila/config -v /opt/aquila/logs:/opt/aquila/logs -w /opt/aquila -e CONFIG_DIR=/opt/aquila/config -e DEVICE_HOSTNAME=<sn> -e PYTHONPATH=/opt/aquila "$IMAGE" python3 scripts/hardware_tests/raster_detailed_log_centered.py <dye> > /opt/aquila/logs/raster_<dye>_<sn>_<YYYYMMDD>.txt 2>&1 && docker start sentri-app
```

**Notes:**
- Drawer Y scans from 0 (home) to `read_steps + 500` in steps of 40.
- Axis X scans within ~100 steps on either side of the well positions in steps of 40.
- After the scan completes, `docker start sentri-app` restarts the main app.
- Approximate scan time: 20–40 minutes.

---

## Filename Convention

`<test_type>_<dye>_<sn>_<YYYYMMDD>.txt` — Example: `raster_fam_sn05_20260520.txt`

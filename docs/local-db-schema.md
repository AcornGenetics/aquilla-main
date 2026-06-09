# SENTRI Local SQLite Schema — Complete Device Logging

All tables live in the on-device SQLite database (`/data/db/app.db`) with WAL mode enabled.
Every table carries `device_id TEXT`, a timestamp column, and `synced INTEGER NOT NULL DEFAULT 0`.
`synced = 0` means the row has not yet been pushed to Postgres. `synced = 1` means it has.

---

## Table Index

| Table | What it logs |
|---|---|
| `runs` | Every PCR run — start, stop, protocol, operator |
| `thermal_readings` | Every thermocouple sample from every well |
| `heater_commands` | Every setpoint sent to heater zones |
| `pcr_cycle_stages` | Stage transitions (denature/anneal/extend) per cycle |
| `fluorescence_readings` | Optical RFU per well per cycle per channel |
| `run_events` | State changes and milestones within a run |
| `run_results` | Final per-well call for each target/channel |
| `pcr_qc_flags` | Each individual QC check that failed per well |
| `device_health` | CPU/RAM/disk/GPU/temp snapshot every ~30s |
| `thermocouple_diagnostics` | Sensor fault codes and calibration offsets |
| `calibration_records` | Full history of every calibration performed |
| `network_events` | WiFi connect/disconnect/signal changes |
| `sync_log` | Every sync attempt — rows pushed, bytes sent, errors |
| `error_log` | Every caught exception with full stack trace |
| `application_events` | Process start/stop, config changes, instrument connect |
| `power_events` | Voltage, brownouts, battery, mains loss |
| `gpio_events` | Lid switch, e-stop, door latch — every physical toggle |
| `storage_health` | SD card health, bad blocks, wear level |
| `operator_actions` | Every human interaction via kiosk/UI |
| `alerts` | Threshold violations and system warnings |
| `firmware_log` | Version history for every software component |
| `process_health` | Heartbeat and liveness for each background thread |
| `devices` | One record per physical instrument — assembly window, device notes |
| `parts` | Every component installed on a device — BOM, batch, condition, known risks |

---

## Setup

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
```

---

## runs

Top-level lifecycle record for every PCR run. Every other table references `run_id`.

```sql
CREATE TABLE IF NOT EXISTS runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    operator_id         TEXT,
    protocol_name       TEXT    NOT NULL,
    protocol_version    TEXT,
    plate_barcode       TEXT,
    sample_count        INTEGER,
    status              TEXT    NOT NULL DEFAULT 'pending',
        -- pending | running | completed | aborted | error
    started_at          TEXT    NOT NULL,
    completed_at        TEXT,
    aborted_at          TEXT,
    abort_reason        TEXT,
    total_cycles        INTEGER,
    cycles_completed    INTEGER DEFAULT 0,
    notes               TEXT,
    synced              INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

---

## thermal_readings

Every thermocouple sample from every well. Written continuously during a run.

```sql
CREATE TABLE IF NOT EXISTS thermal_readings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    device_id           TEXT    NOT NULL,
    well_id             TEXT    NOT NULL,           -- e.g. "A1", "B3"
    thermocouple_index  INTEGER NOT NULL,
    temperature_c       REAL    NOT NULL,
    setpoint_c          REAL,
    error_c             REAL,                       -- measured - setpoint
    cycle_number        INTEGER,
    stage               TEXT,                       -- denature | anneal | extend | hold
    stage_elapsed_ms    INTEGER,
    run_elapsed_ms      INTEGER,
    sampled_at          TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_thermal_run    ON thermal_readings(run_id);
CREATE INDEX IF NOT EXISTS idx_thermal_synced ON thermal_readings(synced);
CREATE INDEX IF NOT EXISTS idx_thermal_well   ON thermal_readings(run_id, well_id);
```

---

## heater_commands

Every setpoint command sent to heater zones by the controller.

```sql
CREATE TABLE IF NOT EXISTS heater_commands (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    device_id           TEXT    NOT NULL,
    heater_zone         TEXT    NOT NULL,           -- "lid" | "block_top" | "block_bottom"
    setpoint_c          REAL    NOT NULL,
    ramp_rate_c_per_s   REAL,
    hold_duration_ms    INTEGER,
    pid_p               REAL,
    pid_i               REAL,
    pid_d               REAL,
    commanded_at        TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_heater_run ON heater_commands(run_id);
```

---

## pcr_cycle_stages

Protocol stage transitions per cycle — timing, target temps, and overshoot.

```sql
CREATE TABLE IF NOT EXISTS pcr_cycle_stages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    device_id           TEXT    NOT NULL,
    cycle_number        INTEGER NOT NULL,
    stage               TEXT    NOT NULL,           -- denature | anneal | extend | hold | ramp
    target_temp_c       REAL    NOT NULL,
    actual_start_temp_c REAL,
    stage_started_at    TEXT    NOT NULL,
    stage_ended_at      TEXT,
    stage_duration_ms   INTEGER,
    ramp_time_ms        INTEGER,
    overshoot_c         REAL,
    synced              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_stages_run ON pcr_cycle_stages(run_id);
```

---

## fluorescence_readings

Optical RFU measurements per well, per cycle, per channel.

```sql
CREATE TABLE IF NOT EXISTS fluorescence_readings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    device_id           TEXT    NOT NULL,
    well_id             TEXT    NOT NULL,
    cycle_number        INTEGER NOT NULL,
    channel             TEXT    NOT NULL,           -- "FAM" | "HEX" | "ROX"
    excitation_nm       INTEGER,
    emission_nm         INTEGER,
    raw_rfu             REAL    NOT NULL,
    baseline_rfu        REAL,
    normalized_rfu      REAL,
    integration_time_ms INTEGER,
    gain                REAL,
    led_power_pct       REAL,
    camera_temp_c       REAL,
    measured_at         TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fluor_run  ON fluorescence_readings(run_id);
CREATE INDEX IF NOT EXISTS idx_fluor_well ON fluorescence_readings(run_id, well_id, cycle_number);
```

---

## run_events

State transitions and notable milestones within a run.

```sql
CREATE TABLE IF NOT EXISTS run_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    device_id           TEXT    NOT NULL,
    event_type          TEXT    NOT NULL,
        -- run_started | run_completed | run_aborted
        -- cycle_started | cycle_completed
        -- stage_started | stage_completed
        -- lid_opened | lid_closed
        -- pause_requested | pause_started | resume_started
        -- protocol_loaded | threshold_crossed | operator_note
    cycle_number        INTEGER,
    stage               TEXT,
    detail              TEXT,                       -- free-text or JSON context
    occurred_at         TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id);
```

---

## run_results

Final per-well analytical call for each target and channel. One row per well per target per channel.

```sql
CREATE TABLE IF NOT EXISTS run_results (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  INTEGER NOT NULL REFERENCES runs(id),
    device_id               TEXT    NOT NULL,
    well_id                 TEXT    NOT NULL,
    sample_id               TEXT,
    target_name             TEXT    NOT NULL,       -- "IAV" | "IBV" | "RSV" | "IC"
    channel                 TEXT    NOT NULL,
    -- Call
    call                    TEXT    NOT NULL,
        -- positive | negative | inconclusive | invalid | no_call
    call_confidence         REAL,
    call_method             TEXT,                   -- "auto" | "manual_override"
    called_by               TEXT,
    -- Quantification
    cq                      REAL,
    cq_confidence           REAL,
    efficiency_pct          REAL,
    r_squared               REAL,
    -- Fluorescence landmarks
    baseline_rfu            REAL,
    baseline_noise_rfu      REAL,
    threshold_rfu           REAL,
    end_rfu                 REAL,
    max_rfu                 REAL,
    delta_rfu               REAL,
    relative_drop           REAL,
    -- Curve shape
    slope                   REAL,
    intercept               REAL,
    sigmoid_amplitude       REAL,
    sigmoid_inflection      REAL,
    sigmoid_slope           REAL,
    -- Summary
    inconclusive            INTEGER DEFAULT 0,      -- 1 if any hard QC flag fired
    flag_count              INTEGER DEFAULT 0,
    analysis_version        TEXT,
    analyzed_at             TEXT    NOT NULL,
    synced                  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_results_run  ON run_results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_well ON run_results(run_id, well_id);
CREATE INDEX IF NOT EXISTS idx_results_call ON run_results(call);
```

---

## pcr_qc_flags

One row per QC check that failed for a given well/result. Join to `run_results` on `result_id`
to reconstruct exactly why a well went inconclusive.

```sql
CREATE TABLE IF NOT EXISTS pcr_qc_flags (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  INTEGER NOT NULL REFERENCES runs(id),
    result_id               INTEGER NOT NULL REFERENCES run_results(id),
    device_id               TEXT    NOT NULL,
    well_id                 TEXT    NOT NULL,
    target_name             TEXT    NOT NULL,
    channel                 TEXT,
    -- The flag
    flag_code               TEXT    NOT NULL,
        -- LATE_CQ               Cq exceeded late-call threshold
        -- NO_AMPLIFICATION      no exponential growth detected
        -- LOW_R2                curve fit R² below minimum
        -- HIGH_BASELINE_NOISE   std dev of baseline too high
        -- LOW_DELTA_RFU         end - baseline below detection floor
        -- MOUNTAIN_ARTIFACT     non-monotonic late-phase hump detected
        -- RELATIVE_DROP         late-phase drop ratio exceeded limit
        -- SLOPE_OUT_OF_RANGE    log-linear slope outside acceptable window
        -- EFFICIENCY_LOW        amplification efficiency < 90%
        -- EFFICIENCY_HIGH       amplification efficiency > 115%
        -- SIGMOID_FIT_POOR      sigmoid residuals above threshold
        -- INHIBITION_SUSPECTED  combined low efficiency + shape abnormality
        -- NTC_CONTAMINATED      no-template control showed amplification
        -- POS_CONTROL_FAILED    positive control did not amplify as expected
        -- IC_FAILED             internal control call failed
        -- MISSING_CYCLES        fewer cycles recorded than protocol requires
        -- THERMOCOUPLE_FAULT    sensor fault during this well's reads
        -- BASELINE_DRIFT        systematic upward/downward baseline slope
        -- SATURATION_DETECTED   RFU clipped at sensor maximum
    flag_category           TEXT    NOT NULL,
        -- curve_quality | controls | instrument | data_integrity | threshold
    severity                TEXT    NOT NULL,
        -- hard (drives inconclusive/invalid) | soft (warning only)
    observed_value          REAL,
    threshold_value         REAL,
    direction               TEXT,                   -- "above" | "below" | "outside_range"
    description             TEXT,
    analysis_module         TEXT,
    analysis_version        TEXT,
    flagged_at              TEXT    NOT NULL,
    synced                  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_qcflags_run    ON pcr_qc_flags(run_id);
CREATE INDEX IF NOT EXISTS idx_qcflags_result ON pcr_qc_flags(result_id);
CREATE INDEX IF NOT EXISTS idx_qcflags_code   ON pcr_qc_flags(flag_code);
CREATE INDEX IF NOT EXISTS idx_qcflags_synced ON pcr_qc_flags(synced);
```

---

## device_health

Periodic system snapshot sampled every ~30 seconds. `run_id` is NULL when the device is idle.

```sql
CREATE TABLE IF NOT EXISTS device_health (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id               TEXT    NOT NULL,
    run_id                  INTEGER REFERENCES runs(id),
    -- CPU
    cpu_pct                 REAL,
    cpu_temp_c              REAL,
    cpu_freq_mhz            REAL,
    cpu_core_count          INTEGER,
    cpu_load_1m             REAL,
    cpu_load_5m             REAL,
    cpu_load_15m            REAL,
    -- Memory
    ram_total_mb            REAL,
    ram_used_mb             REAL,
    ram_free_mb             REAL,
    ram_pct                 REAL,
    swap_total_mb           REAL,
    swap_used_mb            REAL,
    swap_pct                REAL,
    -- Disk (SD card)
    disk_total_gb           REAL,
    disk_used_gb            REAL,
    disk_free_gb            REAL,
    disk_pct                REAL,
    disk_read_mb_s          REAL,
    disk_write_mb_s         REAL,
    -- GPU (Pi VideoCore)
    gpu_temp_c              REAL,
    gpu_freq_mhz            REAL,
    gpu_mem_total_mb        REAL,
    gpu_mem_used_mb         REAL,
    -- Board
    board_temp_c            REAL,
    throttle_flags          TEXT,                   -- raw vcgencmd value e.g. "0x50000"
    under_voltage           INTEGER,
    arm_freq_capped         INTEGER,
    throttled               INTEGER,
    -- Uptime
    uptime_seconds          INTEGER,
    process_uptime_seconds  INTEGER,
    active_thread_count     INTEGER,
    sampled_at              TEXT    NOT NULL,
    synced                  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_health_device ON device_health(device_id);
CREATE INDEX IF NOT EXISTS idx_health_run    ON device_health(run_id);
CREATE INDEX IF NOT EXISTS idx_health_synced ON device_health(synced);
```

---

## thermocouple_diagnostics

Sensor self-check results and calibration offsets per thermocouple.

```sql
CREATE TABLE IF NOT EXISTS thermocouple_diagnostics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    thermocouple_index  INTEGER NOT NULL,
    well_id             TEXT,
    fault_code          INTEGER,
    fault_description   TEXT,                       -- "open circuit" | "short to VCC" | "short to GND" | "ok"
    cold_junction_c     REAL,
    reference_voltage   REAL,
    offset_applied_c    REAL,
    passed_selftest     INTEGER,
    checked_at          TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
```

---

## calibration_records

Full history of every calibration event performed on the device.

```sql
CREATE TABLE IF NOT EXISTS calibration_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    calibration_type    TEXT    NOT NULL,           -- temperature | fluorescence | optical | pressure
    well_id             TEXT,
    sensor_index        INTEGER,
    pre_offset_c        REAL,
    post_offset_c       REAL,
    reference_value     REAL,
    measured_value      REAL,
    residual_error      REAL,
    passed              INTEGER,
    operator_id         TEXT,
    performed_at        TEXT    NOT NULL,
    expires_at          TEXT,
    notes               TEXT,
    synced              INTEGER NOT NULL DEFAULT 0
);
```

---

## network_events

WiFi and ethernet state changes.

```sql
CREATE TABLE IF NOT EXISTS network_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    event_type          TEXT    NOT NULL,
        -- connected | disconnected | reconnecting | ip_changed
        -- dns_failure | internet_reachable | internet_unreachable
    interface           TEXT,                       -- wlan0 | eth0
    ssid                TEXT,
    bssid               TEXT,
    ip_address          TEXT,
    signal_dbm          INTEGER,
    link_speed_mbps     INTEGER,
    reason_code         INTEGER,
    reason_text         TEXT,
    occurred_at         TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_net_synced ON network_events(synced);
```

---

## sync_log

History of every sync attempt — outcome, row counts, and errors.

```sql
CREATE TABLE IF NOT EXISTS sync_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    target              TEXT    NOT NULL,           -- "postgres" | "s3" | "api"
    attempted_at        TEXT    NOT NULL,
    outcome             TEXT    NOT NULL,           -- success | failure | skipped | partial
    rows_attempted      INTEGER DEFAULT 0,
    rows_pushed         INTEGER DEFAULT 0,
    rows_failed         INTEGER DEFAULT 0,
    duration_ms         INTEGER,
    error_code          TEXT,
    error_message       TEXT,
    http_status         INTEGER,
    bytes_transferred   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sync_device  ON sync_log(device_id);
CREATE INDEX IF NOT EXISTS idx_sync_outcome ON sync_log(outcome);
```

---

## error_log

Every caught exception and unhandled error with full stack trace.

```sql
CREATE TABLE IF NOT EXISTS error_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    run_id              INTEGER REFERENCES runs(id),
    severity            TEXT    NOT NULL,           -- debug | info | warning | error | critical
    thread_name         TEXT,                       -- main | health_monitor | sync | camera
    logger_name         TEXT,
    module              TEXT,
    function_name       TEXT,
    line_number         INTEGER,
    message             TEXT    NOT NULL,
    exception_type      TEXT,
    exception_message   TEXT,
    stack_trace         TEXT,
    context_json        TEXT,
    occurred_at         TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_error_severity ON error_log(severity);
CREATE INDEX IF NOT EXISTS idx_error_run      ON error_log(run_id);
CREATE INDEX IF NOT EXISTS idx_error_synced   ON error_log(synced);
```

---

## application_events

Software lifecycle events — process start/stop, config changes, instrument connection.

```sql
CREATE TABLE IF NOT EXISTS application_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    event_type          TEXT    NOT NULL,
        -- app_start | app_stop | app_crash | watchdog_restart
        -- thread_start | thread_stop | thread_crash | thread_restart
        -- config_loaded | config_changed | firmware_updated
        -- instrument_connected | instrument_disconnected
        -- usb_inserted | usb_removed | kiosk_start | kiosk_stop | kiosk_crash
    process_name        TEXT,
    thread_name         TEXT,
    firmware_version    TEXT,
    config_key          TEXT,
    config_old_value    TEXT,
    config_new_value    TEXT,
    detail              TEXT,
    occurred_at         TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_appev_synced ON application_events(synced);
```

---

## power_events

Supply voltage readings, brownouts, battery state, and mains transitions.

```sql
CREATE TABLE IF NOT EXISTS power_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    event_type          TEXT    NOT NULL,
        -- power_on | power_off | brownout_detected | over_voltage
        -- battery_low | battery_charging | battery_full | mains_lost | mains_restored
    input_voltage_v     REAL,
    rail_5v_v           REAL,
    rail_3v3_v          REAL,
    current_ma          REAL,
    power_w             REAL,
    battery_pct         REAL,
    source              TEXT,                       -- mains | battery | poe
    occurred_at         TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
```

---

## gpio_events

Physical hardware events — lid switch, e-stop, door latch, and other GPIO transitions.

```sql
CREATE TABLE IF NOT EXISTS gpio_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    run_id              INTEGER REFERENCES runs(id),
    pin_number          INTEGER,
    pin_name            TEXT,                       -- "lid_switch" | "e_stop" | "door_latch"
    event_type          TEXT    NOT NULL,           -- rising | falling | high | low
    value               INTEGER,
    occurred_at         TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
```

---

## storage_health

SD card and filesystem metrics including wear-level data where available.

```sql
CREATE TABLE IF NOT EXISTS storage_health (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    filesystem          TEXT    NOT NULL,           -- "/" | "/boot" | "/data"
    total_gb            REAL,
    used_gb             REAL,
    free_gb             REAL,
    use_pct             REAL,
    inode_total         INTEGER,
    inode_used          INTEGER,
    inode_free          INTEGER,
    read_errors         INTEGER,
    write_errors        INTEGER,
    lifetime_writes_gb  REAL,
    erase_count_avg     INTEGER,
    erase_count_max     INTEGER,
    bad_blocks          INTEGER,
    health_pct          REAL,
    sampled_at          TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
```

---

## operator_actions

Every human interaction via the kiosk or API — login, run control, settings changes.

```sql
CREATE TABLE IF NOT EXISTS operator_actions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    run_id              INTEGER REFERENCES runs(id),
    operator_id         TEXT,
    action              TEXT    NOT NULL,
        -- login | logout | run_start | run_abort | run_pause | run_resume
        -- protocol_selected | barcode_scanned | note_added
        -- settings_changed | calibration_started | export_requested
        -- emergency_stop | door_override
    target              TEXT,
    old_value           TEXT,
    new_value           TEXT,
    input_method        TEXT,                       -- touch | keyboard | barcode_scanner | api
    occurred_at         TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_opact_run ON operator_actions(run_id);
```

---

## alerts

Threshold violations and system warnings, with acknowledgement tracking.

```sql
CREATE TABLE IF NOT EXISTS alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    run_id              INTEGER REFERENCES runs(id),
    alert_type          TEXT    NOT NULL,
        -- temp_overshoot | temp_undershoot | temp_sensor_fault
        -- cpu_overheat | disk_full | ram_critical | battery_low
        -- sync_lag | run_overdue | protocol_timeout
        -- lid_open_during_run | unexpected_stop
    severity            TEXT    NOT NULL,           -- info | warning | critical
    well_id             TEXT,
    sensor_index        INTEGER,
    threshold_value     REAL,
    actual_value        REAL,
    message             TEXT    NOT NULL,
    acknowledged        INTEGER DEFAULT 0,
    acknowledged_by     TEXT,
    acknowledged_at     TEXT,
    auto_resolved       INTEGER DEFAULT 0,
    resolved_at         TEXT,
    triggered_at        TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_run      ON alerts(run_id);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_synced   ON alerts(synced);
```

---

## firmware_log

Version history for every software component on the device.

```sql
CREATE TABLE IF NOT EXISTS firmware_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    component           TEXT    NOT NULL,           -- "aquila_app" | "kiosk" | "pi_os" | "instrument_fw"
    previous_version    TEXT,
    new_version         TEXT    NOT NULL,
    update_method       TEXT,                       -- "ota" | "manual" | "factory_flash"
    update_source       TEXT,
    checksum            TEXT,
    update_status       TEXT    NOT NULL,           -- success | failed | rolled_back
    error_message       TEXT,
    applied_at          TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
```

---

## process_health

Per-thread liveness, heartbeat status, and loop timing metrics.

```sql
CREATE TABLE IF NOT EXISTS process_health (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    thread_name         TEXT    NOT NULL,           -- main | health_monitor | sync | camera | watchdog
    status              TEXT    NOT NULL,           -- alive | dead | hung | restarting
    last_heartbeat_at   TEXT,
    heartbeat_interval_s INTEGER,
    missed_heartbeats   INTEGER DEFAULT 0,
    cpu_pct             REAL,
    memory_mb           REAL,
    open_file_handles   INTEGER,
    loop_latency_ms     REAL,
    queue_depth         INTEGER,
    sampled_at          TEXT    NOT NULL,
    synced              INTEGER NOT NULL DEFAULT 0
);
```

---

## Useful Diagnostic Queries

```sql
-- How many rows are waiting to sync across all tables?
SELECT 'thermal_readings'    AS tbl, COUNT(*) AS pending FROM thermal_readings    WHERE synced = 0
UNION ALL
SELECT 'fluorescence_readings',      COUNT(*) FROM fluorescence_readings      WHERE synced = 0
UNION ALL
SELECT 'run_results',                COUNT(*) FROM run_results                WHERE synced = 0
UNION ALL
SELECT 'pcr_qc_flags',               COUNT(*) FROM pcr_qc_flags               WHERE synced = 0
UNION ALL
SELECT 'device_health',              COUNT(*) FROM device_health              WHERE synced = 0
UNION ALL
SELECT 'error_log',                  COUNT(*) FROM error_log                  WHERE synced = 0;

-- Why did a specific well go inconclusive?
SELECT flag_code, severity, observed_value, threshold_value, direction, description
FROM pcr_qc_flags
WHERE result_id = ?
ORDER BY severity DESC, flag_code;

-- All hard QC failures across the fleet (Postgres side)
SELECT device_id, run_id, well_id, target_name, flag_code, COUNT(*) AS occurrences
FROM pcr_qc_flags
WHERE severity = 'hard'
GROUP BY device_id, flag_code
ORDER BY occurrences DESC;

-- Runs that had any errors during execution
SELECT r.id, r.device_id, r.protocol_name, r.status, r.started_at,
       COUNT(e.id) AS error_count
FROM runs r
LEFT JOIN error_log e ON e.run_id = r.id
GROUP BY r.id
HAVING error_count > 0;

-- Device health during a specific run
SELECT sampled_at, cpu_pct, cpu_temp_c, ram_pct, throttled
FROM device_health
WHERE run_id = ?
ORDER BY sampled_at;
```

---

## devices

One record per physical instrument. Captures the assembly window and any device-level observations
that apply to the unit as a whole rather than a specific part.

```sql
CREATE TABLE IF NOT EXISTS devices (
    id                  TEXT    PRIMARY KEY,        -- serial number e.g. "SN03"
    assembled_start     TEXT,                       -- ISO8601 date assembly began
    assembled_end       TEXT,                       -- ISO8601 date assembly completed
    assembly_technician TEXT,                       -- who assembled it
    assembly_location   TEXT,                       -- lab or facility name
    hw_revision         TEXT,                       -- hardware revision of this unit e.g. "rev_B"
    notes               TEXT,                       -- device-level observations e.g. "screen flickers during recipe runs"
    retired             INTEGER NOT NULL DEFAULT 0, -- 1 if unit is no longer in service
    retired_at          TEXT,
    retired_reason      TEXT,
    synced              INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

---

## parts

Every component installed on a device. One row per part per installation event —
if a part is replaced, the old row gets `removed_at` filled in and a new row is inserted.

Series classification follows the AQU-XXXX numbering convention:
- **2000s** — purchased components (LEDs, springs, o-rings)
- **3000s** — custom machined and molded parts
- **4000s** — electrical components and PCBs
- **7000s** — purchased assemblies (motors, terminated sensors)

```sql
CREATE TABLE IF NOT EXISTS parts (
    id                  TEXT    PRIMARY KEY,        -- UUID generated locally
    device_id           TEXT    NOT NULL REFERENCES devices(id),
    part_number         TEXT    NOT NULL,           -- e.g. "AQU-3003"
    series              INTEGER NOT NULL,           -- 2000 | 3000 | 4000 | 7000
    description         TEXT    NOT NULL,           -- full part description
    material            TEXT,                       -- e.g. "Al 6061 (Black Anodized II)", "PTFE"
    supplier_part_number TEXT,                      -- supplier catalog number e.g. "SP-05-B3", "TEC-1089-SV-PT100"
    supplier_url        TEXT,                       -- link to supplier listing
    quantity            INTEGER NOT NULL DEFAULT 1,
    batch_number        TEXT,                       -- e.g. "Arete Provided", "Ours", "Ours at present"
    date_received       TEXT,                       -- ISO8601
    installed_at        TEXT,                       -- ISO8601 — when this instance was installed
    removed_at          TEXT,                       -- ISO8601 — NULL if still installed
    removal_reason      TEXT,                       -- "failed" | "replaced" | "upgraded" | "returned"
    -- Condition and risk tracking
    install_condition   TEXT,
        -- "ok" | "slightly bent during assembly" | "had to cut screw ourselves"
        -- free text — whatever the technician observed at install time
    known_risk          INTEGER NOT NULL DEFAULT 0, -- 1 if note flags a potential future failure
    known_risk_detail   TEXT,
        -- e.g. "U7 may have been stressed and could fail in future"
        -- e.g. "lid power connection is loose on the board and wobbling"
        -- e.g. "motor sticks at home and must be physically pushed"
    risk_resolved       INTEGER NOT NULL DEFAULT 0, -- 1 if the risk was later addressed
    risk_resolved_at    TEXT,
    risk_resolved_notes TEXT,
    -- Who did what
    installed_by        TEXT,
    inspected_by        TEXT,
    inspected_at        TEXT,
    notes               TEXT,                       -- general free-text notes
    synced              INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_parts_device      ON parts(device_id);
CREATE INDEX IF NOT EXISTS idx_parts_number      ON parts(part_number);
CREATE INDEX IF NOT EXISTS idx_parts_known_risk  ON parts(device_id, known_risk) WHERE known_risk = 1;
CREATE INDEX IF NOT EXISTS idx_parts_installed   ON parts(device_id, removed_at);
```

### Useful parts queries

```sql
-- All currently installed parts on a device
SELECT part_number, series, description, material, batch_number, installed_at, install_condition
FROM parts
WHERE device_id = 'SN03' AND removed_at IS NULL
ORDER BY series, part_number;

-- All active known risks across the fleet
SELECT device_id, part_number, description, known_risk_detail, installed_at
FROM parts
WHERE known_risk = 1 AND risk_resolved = 0 AND removed_at IS NULL
ORDER BY device_id, part_number;

-- Part replacement history for a specific component
SELECT device_id, installed_at, removed_at, removal_reason, install_condition, notes
FROM parts
WHERE part_number = 'AQU-4001'
ORDER BY device_id, installed_at;

-- All parts received on a given date
SELECT device_id, part_number, description, batch_number, quantity
FROM parts
WHERE date_received = '2026-03-05'
ORDER BY series, part_number;
```

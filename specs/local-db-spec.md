# SENTRI Local SQLite — DB Layer Spec

**Schema reference:** [local-db-schema.md](../docs/local-db-schema.md)

This document specifies the Python database access layer that sits between the instrument
code and the local SQLite file. It covers initialization, one write function per table,
the sync handoff, and implementation priority order.

---

## Overview

```
Instrument code          DB layer (this spec)       SQLite file
─────────────────        ────────────────────       ──────────────────────
meerstetter.py      ──►  insert_thermal_reading()  ──►  /data/db/app.db
thermal_engine.py   ──►  insert_heater_command()
adc_class.py        ──►  insert_fluorescence()
hw_api.py           ──►  insert_run() / close_run()
background threads  ──►  insert_device_health()
                         insert_error()
                         insert_network_event()
                         ...                        ──►  sync thread  ──►  Postgres
```

The entire DB layer lives in one module: `src/local_db.py`.
All functions accept plain Python values (no ORM objects).
All timestamps are ISO8601 UTC strings: `datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"`.

---

## 1. Setup and Initialization

### File location

| Environment | Path |
|---|---|
| Pi (production) | `/data/db/app.db` |
| Dev / CI | `$LOCAL_DB_PATH` env var, defaults to `data/db/app.db` |

### `init_db(path=None) -> sqlite3.Connection`

Called once at application startup. Creates all tables if they do not exist, enables WAL
mode, and returns a connection that is shared across threads.

```python
def init_db(path: str = None) -> sqlite3.Connection:
    db_path = path or os.environ.get("LOCAL_DB_PATH", "data/db/app.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_tables(conn)
    return conn
```

`_create_tables(conn)` runs every `CREATE TABLE IF NOT EXISTS` statement from the schema.
Because of `IF NOT EXISTS`, this is safe to call on an existing database — it is a no-op
if the tables are already there.

### Thread safety

One connection is created at startup and passed to all threads. WAL mode allows concurrent
reads during writes. A single `threading.Lock` (`_write_lock`) is acquired before any
`INSERT` or `UPDATE`. Reads do not need the lock.

```python
_write_lock = threading.Lock()
```

---

## 2. Write Endpoints

Each function below takes the specific values needed for that table, acquires `_write_lock`,
executes the `INSERT`, releases the lock, and returns the new row `id`.

---

### `insert_run`

Called when a run starts. Returns `run_id` which is passed to all subsequent inserts.

```python
def insert_run(
    conn,
    device_id: str,
    protocol_name: str,
    protocol_version: str = None,
    operator_id: str = None,
    plate_barcode: str = None,
    sample_count: int = None,
    total_cycles: int = None,
    notes: str = None,
) -> int
```

**Called from:** `hw_api.py:DockInterface` — replace `generate_runid()` with this.
**Returns:** integer `run_id` used as foreign key in all other tables.

---

### `update_run_status`

Called when a run completes, aborts, or errors.

```python
def update_run_status(
    conn,
    run_id: int,
    status: str,               # "completed" | "aborted" | "error"
    cycles_completed: int = None,
    abort_reason: str = None,
) -> None
```

---

### `insert_thermal_reading`

Called inside `meerstetter.py:log()` on every polling loop iteration, once per channel.

```python
def insert_thermal_reading(
    conn,
    run_id: int,
    device_id: str,
    well_id: str,
    thermocouple_index: int,
    temperature_c: float,
    setpoint_c: float = None,
    cycle_number: int = None,
    stage: str = None,
    stage_elapsed_ms: int = None,
    run_elapsed_ms: int = None,
    sampled_at: str = None,     # ISO8601 UTC — defaults to now if omitted
) -> int
```

**Called from:** `meerstetter.py:log()` — add a call here alongside the existing `print()`.
**Volume:** high — every ~50ms during a run. Use `executemany` if batching multiple channels.

---

### `insert_heater_command`

Called every time a setpoint or ramp rate is sent to the Meerstetter.

```python
def insert_heater_command(
    conn,
    run_id: int,
    device_id: str,
    heater_zone: str,           # "lid" | "block_top" | "block_bottom"
    setpoint_c: float,
    ramp_rate_c_per_s: float = None,
    hold_duration_ms: int = None,
) -> int
```

**Called from:** `thermal_engine.py` — add calls at the `meer.change_setpoint()` and
`meer.change_ramprate()` lines.

---

### `insert_pcr_cycle_stage`

Called at the start of each ramp/hold stage from the thermal parser output.

```python
def insert_pcr_cycle_stage(
    conn,
    run_id: int,
    device_id: str,
    cycle_number: int,
    stage: str,                 # "denature" | "anneal" | "extend" | "hold" | "ramp"
    target_temp_c: float,
    actual_start_temp_c: float = None,
    stage_started_at: str = None,
) -> int
```

`close_pcr_cycle_stage(conn, stage_id, stage_ended_at, overshoot_c)` fills in the
end time and overshoot once the stage completes.

**Called from:** `thermal_engine.py` — at the top of each `if name == "hold":` /
`elif name == "ramp":` branch.

---

### `insert_fluorescence_reading`

Called in `adc_class.py:OpticalRead` after each ADC conversion, replacing the current
`print_result()` stdout output.

```python
def insert_fluorescence_reading(
    conn,
    run_id: int,
    device_id: str,
    well_id: str,
    cycle_number: int,
    channel: str,               # "FAM" | "HEX" | "ROX"
    raw_rfu: float,
    led_power_pct: float = None,
    integration_time_ms: int = None,
    gain: float = None,
    measured_at: str = None,
) -> int
```

**Called from:** `adc_class.py:capture_blink()` — replace or supplement `print_result()`.

---

### `insert_run_event`

Called at any state transition or notable moment during a run.

```python
def insert_run_event(
    conn,
    run_id: int,
    device_id: str,
    event_type: str,
    cycle_number: int = None,
    stage: str = None,
    detail: str = None,         # free text or JSON string
) -> int
```

**Called from:** `thermal_engine.py` at run start/stop/abort, cycle boundaries, lid events.

---

### `insert_run_result`

Called once per well per target after the analysis module produces a call.

```python
def insert_run_result(
    conn,
    run_id: int,
    device_id: str,
    well_id: str,
    target_name: str,
    channel: str,
    call: str,                  # "positive" | "negative" | "inconclusive" | "invalid"
    cq: float = None,
    r_squared: float = None,
    efficiency_pct: float = None,
    baseline_rfu: float = None,
    end_rfu: float = None,
    delta_rfu: float = None,
    relative_drop: float = None,
    slope: float = None,
    flag_count: int = 0,
    inconclusive: int = 0,
    analysis_version: str = None,
    analyzed_at: str = None,
) -> int
```

**Called from:** PCR analysis module (to be built). Returns `result_id` needed by
`insert_qc_flag`.

---

### `insert_qc_flag`

Called once per failed QC check, linked to a `result_id`.

```python
def insert_qc_flag(
    conn,
    run_id: int,
    result_id: int,
    device_id: str,
    well_id: str,
    target_name: str,
    flag_code: str,             # see flag_code list in schema doc
    flag_category: str,
    severity: str,              # "hard" | "soft"
    observed_value: float = None,
    threshold_value: float = None,
    direction: str = None,
    description: str = None,
    analysis_module: str = None,
    analysis_version: str = None,
) -> int
```

---

### `insert_device_health`

Called by the background health monitor thread every ~30 seconds.

```python
def insert_device_health(
    conn,
    device_id: str,
    run_id: int = None,         # None when idle
    cpu_pct: float = None,
    cpu_temp_c: float = None,
    ram_pct: float = None,
    ram_used_mb: float = None,
    disk_pct: float = None,
    disk_free_gb: float = None,
    gpu_temp_c: float = None,
    throttled: int = None,
    under_voltage: int = None,
    uptime_seconds: int = None,
    sampled_at: str = None,
) -> int
```

**Requires:** `psutil` for CPU/RAM. `vcgencmd measure_temp` or `/sys/class/thermal` for
board temp. `vcgencmd get_throttled` for throttle flags.
**New subsystem needed:** `src/health_monitor.py` — a daemon thread that calls this on a
30s interval.

---

### `insert_thermocouple_diagnostic`

Called at startup, before each run, and on any serial fault.

```python
def insert_thermocouple_diagnostic(
    conn,
    device_id: str,
    thermocouple_index: int,
    well_id: str = None,
    fault_code: int = None,
    fault_description: str = None,   # "ok" | "open circuit" | "short to VCC" | "short to GND"
    cold_junction_c: float = None,
    reference_voltage: float = None,
    offset_applied_c: float = None,
    passed_selftest: int = None,
) -> int
```

**Called from:** `meerstetter.py` — in the `except SerialException` block and on a
pre-run self-check call.

---

### `insert_network_event`

Called by a network monitor whenever interface state changes.

```python
def insert_network_event(
    conn,
    device_id: str,
    event_type: str,            # "connected" | "disconnected" | "ip_changed" etc.
    interface: str = None,
    ssid: str = None,
    ip_address: str = None,
    signal_dbm: int = None,
    reason_text: str = None,
) -> int
```

**New subsystem needed:** `src/network_monitor.py` — polls `ip link` / `iwconfig` or
listens to NetworkManager D-Bus signals.

---

### `insert_sync_log`

Called by the sync thread after every attempt, whether it succeeded or failed.

```python
def insert_sync_log(
    conn,
    device_id: str,
    target: str,                # "postgres"
    outcome: str,               # "success" | "failure" | "skipped" | "partial"
    rows_attempted: int = 0,
    rows_pushed: int = 0,
    rows_failed: int = 0,
    duration_ms: int = None,
    error_message: str = None,
    http_status: int = None,
    bytes_transferred: int = None,
) -> int
```

**Called from:** `sentri_web/sync.py` — wrap the existing `sync_pending_events()` call
to record the outcome here.

---

### `insert_error`

Called from a custom logging handler that intercepts the Python `logging` module.

```python
def insert_error(
    conn,
    device_id: str,
    severity: str,              # "debug" | "info" | "warning" | "error" | "critical"
    message: str,
    run_id: int = None,
    thread_name: str = None,
    module: str = None,
    function_name: str = None,
    line_number: int = None,
    exception_type: str = None,
    exception_message: str = None,
    stack_trace: str = None,
) -> int
```

**How to wire it:** add a `SQLiteHandler(logging.Handler)` subclass that calls
`insert_error()` in its `emit()` method and attach it to the root logger in
`utils.py:LOGGING_CONFIG`. This captures every `logger.error()` / `logger.critical()`
call site without changing any of them.

---

### `insert_application_event`

```python
def insert_application_event(
    conn,
    device_id: str,
    event_type: str,
    process_name: str = None,
    thread_name: str = None,
    firmware_version: str = None,
    detail: str = None,
) -> int
```

---

### `insert_alert`

```python
def insert_alert(
    conn,
    device_id: str,
    alert_type: str,
    severity: str,              # "info" | "warning" | "critical"
    message: str,
    run_id: int = None,
    well_id: str = None,
    threshold_value: float = None,
    actual_value: float = None,
) -> int
```

`acknowledge_alert(conn, alert_id, acknowledged_by)` and
`resolve_alert(conn, alert_id)` update the existing row.

---

### `insert_gpio_event`

```python
def insert_gpio_event(
    conn,
    device_id: str,
    pin_name: str,              # "lid_switch" | "e_stop" | "door_latch"
    event_type: str,            # "rising" | "falling"
    value: int,
    run_id: int = None,
    pin_number: int = None,
) -> int
```

**Called from:** `hw_api.py` GPIO interrupt callbacks.

---

### `insert_storage_health`

```python
def insert_storage_health(
    conn,
    device_id: str,
    filesystem: str,
    total_gb: float,
    used_gb: float,
    free_gb: float,
    use_pct: float,
    read_errors: int = None,
    write_errors: int = None,
) -> int
```

---

### `insert_operator_action`

```python
def insert_operator_action(
    conn,
    device_id: str,
    action: str,
    run_id: int = None,
    operator_id: str = None,
    target: str = None,
    old_value: str = None,
    new_value: str = None,
    input_method: str = None,
) -> int
```

---

### `insert_firmware_log`

```python
def insert_firmware_log(
    conn,
    device_id: str,
    component: str,             # "aquila_app" | "kiosk" | "pi_os" | "instrument_fw"
    new_version: str,
    update_status: str,         # "success" | "failed" | "rolled_back"
    previous_version: str = None,
    update_method: str = None,
    error_message: str = None,
) -> int
```

---

### `insert_process_health`

```python
def insert_process_health(
    conn,
    device_id: str,
    thread_name: str,
    status: str,                # "alive" | "dead" | "hung" | "restarting"
    last_heartbeat_at: str = None,
    missed_heartbeats: int = 0,
    loop_latency_ms: float = None,
    cpu_pct: float = None,
    memory_mb: float = None,
) -> int
```

---

## 3. Read / Query Endpoints

These are used by the sync thread and the kiosk UI.

```python
def get_unsynced_rows(conn, table: str, limit: int = 500) -> list[dict]
    # SELECT * FROM {table} WHERE synced = 0 LIMIT {limit}

def mark_synced(conn, table: str, ids: list[int]) -> None
    # UPDATE {table} SET synced = 1 WHERE id IN (...)

def get_run(conn, run_id: int) -> dict

def get_run_results(conn, run_id: int) -> list[dict]

def get_qc_flags_for_result(conn, result_id: int) -> list[dict]

def get_active_alerts(conn, device_id: str) -> list[dict]
    # WHERE acknowledged = 0 AND auto_resolved = 0

def get_pending_sync_count(conn) -> dict
    # Returns {table_name: unsynced_row_count} for all tables
```

---

## 4. Sync Thread Integration

The sync thread in `sentri_web/sync.py` currently pushes a single `events` table.
With the new schema, it iterates over all syncable tables:

```python
SYNCABLE_TABLES = [
    "runs", "thermal_readings", "heater_commands", "pcr_cycle_stages",
    "fluorescence_readings", "run_events", "run_results", "pcr_qc_flags",
    "device_health", "thermocouple_diagnostics", "calibration_records",
    "network_events", "error_log", "application_events", "power_events",
    "gpio_events", "storage_health", "operator_actions", "alerts",
    "firmware_log", "process_health",
]

def sync_cycle(conn, pg_conn):
    for table in SYNCABLE_TABLES:
        rows = get_unsynced_rows(conn, table, limit=500)
        if not rows:
            continue
        try:
            push_to_postgres(pg_conn, table, rows)
            mark_synced(conn, table, [r["id"] for r in rows])
            insert_sync_log(conn, ..., outcome="success", rows_pushed=len(rows))
        except Exception as e:
            insert_sync_log(conn, ..., outcome="failure", error_message=str(e))
```

`runs` must always be synced before any table that references `run_id`, so keep it first
in `SYNCABLE_TABLES`.

---

## 5. Implementation Priority

### Phase 1 — Wire existing data sources (no new subsystems)

These tables have data in memory right now. They just need the DB layer inserted.

| Priority | Table | Change needed |
|---|---|---|
| 1 | `runs` | Replace `generate_runid()` in `hw_api.py` with `insert_run()` |
| 2 | `thermal_readings` | Add `insert_thermal_reading()` call inside `meerstetter.py:log()` |
| 3 | `heater_commands` | Add inserts at `change_setpoint()` / `change_ramprate()` in `thermal_engine.py` |
| 4 | `pcr_cycle_stages` | Add inserts at stage transitions in `thermal_engine.py` |
| 5 | `fluorescence_readings` | Add inserts in `adc_class.py:capture_blink()` |
| 6 | `run_events` | Add inserts at run start/stop/abort and cycle boundaries |
| 7 | `error_log` | Add `SQLiteHandler` to root logger in `utils.py` |

### Phase 2 — New background subsystems

| Priority | Table | New file needed |
|---|---|---|
| 8 | `device_health` | `src/health_monitor.py` — `psutil` daemon thread, 30s interval |
| 9 | `thermocouple_diagnostics` | Pre-run self-check in `meerstetter.py` |
| 10 | `network_events` | `src/network_monitor.py` — poll interface state |
| 11 | `process_health` | Watchdog heartbeat per thread |
| 12 | `sync_log` | Wrap `sentri_web/sync.py` outcome recording |

### Phase 3 — Requires new analytical modules

| Priority | Table | Depends on |
|---|---|---|
| 13 | `run_results` | PCR analysis module (curve fitting, Cq calling) |
| 14 | `pcr_qc_flags` | Same analysis module |
| 15 | `calibration_records` | Calibration workflow UI + logic |
| 16 | `alerts` | Alert threshold engine |

### Phase 4 — Manual / operational data entry

| Priority | Table | Notes |
|---|---|---|
| 17 | `devices` | One-time insert per unit at assembly |
| 18 | `parts` | Entered at assembly, updated on part replacement |
| 19 | `operator_actions` | Wire to kiosk UI events |
| 20 | `firmware_log` | Insert on OTA update completion |

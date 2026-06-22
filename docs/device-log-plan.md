# Device Log — Plan

## What this is

A parts and maintenance log per device. Each device tracks its own installed
components, replacement history, and technician notes locally. Records sync
to the cloud so the full fleet history is queryable from one place.

---

## Database advice

### Don't use PostgreSQL on the device

PostgreSQL on a Raspberry Pi is overkill — it runs as a server process, uses
~50–100 MB RAM idle, requires config, and adds failure modes. For a single
device writing a few records per week, it's the wrong tool.

### Use SQLite on the device

SQLite is embedded — no server, no config, a single file at
`/opt/aquila/logs/device_log.db`. It's what the Pi already does well and
it's the standard choice for edge/IoT device storage.

### Use Supabase in the cloud (hosted PostgreSQL)

Supabase gives you:
- Hosted PostgreSQL with a clean web UI to browse all device records
- A REST API the device can POST to without any extra server
- A free tier that is sufficient for a fleet of this size
- Row-level security so each device can only write its own records

The device writes to SQLite first, then syncs to Supabase when it has
internet. If the device is offline, records queue locally and sync later.

---

## Data model

### `devices` — top-level device record

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT | matches `DEVICE_ID` env var e.g. "SN03" |
| `assembled_start` | TEXT (ISO8601) | start of assembly window |
| `assembled_end` | TEXT (ISO8601) | end of assembly window |
| `notes` | TEXT | device-level notes |
| `synced` | INTEGER | 0 / 1 |
| `created_at` | TEXT (ISO8601) | |
| `updated_at` | TEXT (ISO8601) | |

### `parts` — what is installed on the device

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT (UUID) | generated locally |
| `device_id` | TEXT | FK → devices.id e.g. "SN03" |
| `part_number` | TEXT | AQU-XXXX identifier e.g. "AQU-4004" |
| `series` | INTEGER | 2000, 3000, 4000, 7000 |
| `description` | TEXT | full part description |
| `material` | TEXT | e.g. "Al 6061 (Black Anodized II)", "PTFE" |
| `supplier_part_number` | TEXT | supplier/link reference e.g. "TEC-1089-SV-PT100" |
| `quantity` | INTEGER | number of this part installed |
| `batch_number` | TEXT | e.g. "Arete Provided", "Ours" |
| `date_received` | TEXT (ISO8601) | |
| `installed_at` | TEXT (ISO8601) | |
| `removed_at` | TEXT (ISO8601) | null if still installed |
| `notes` | TEXT | e.g. "U7 may have been stressed", "Had to cut screw ourselves" |
| `synced` | INTEGER | 0 = not yet synced to cloud, 1 = synced |
| `created_at` | TEXT (ISO8601) | |
| `updated_at` | TEXT (ISO8601) | |

### `events` — log of actions taken on the device

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT (UUID) | generated locally |
| `device_id` | TEXT | |
| `part_id` | TEXT | FK → parts.id, nullable (some events are device-level) |
| `event_type` | TEXT | "installed", "replaced", "inspected", "failed", "note" |
| `performed_by` | TEXT | technician name |
| `notes` | TEXT | |
| `synced` | INTEGER | 0 / 1 |
| `created_at` | TEXT (ISO8601) | |

---

## Architecture

```
┌─────────────────────────────────┐
│  Pi Device                      │
│                                 │
│  /opt/aquila/database/          │
│    device_log.db  (SQLite)      │
│                                 │
│  sentri-backend container       │
│    GET  /device-log/parts       │
│    POST /device-log/parts       │
│    PUT  /device-log/parts/{id}  │
│    GET  /device-log/events      │
│    POST /device-log/events      │
│    POST /device-log/sync        │ ← manual trigger
│                                 │
│  background sync task           │
│    runs every 10 min            │
│    pushes unsynced rows         │
│    to Supabase REST API         │
└────────────────┬────────────────┘
                 │ HTTPS POST (when online)
                 ▼
┌─────────────────────────────────┐
│  Supabase (cloud PostgreSQL)    │
│                                 │
│  tables: parts, events          │
│  web UI: browse all devices     │
│  REST API: auto-generated       │
└─────────────────────────────────┘
```

---

## Step 1 — SQLite setup (backend)

Create the DB and tables on first run. Add to `main.py` startup:

```python
import sqlite3
from uuid import uuid4

DB_PATH = Path(os.getenv("DATA_DIR", "/opt/aquila")) / "database" / "device_log.db"

def _init_device_log_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            assembled_start TEXT,
            assembled_end TEXT,
            notes TEXT,
            synced INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS parts (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            part_number TEXT NOT NULL,
            series INTEGER,
            description TEXT NOT NULL,
            material TEXT,
            supplier_part_number TEXT,
            quantity INTEGER DEFAULT 1,
            batch_number TEXT,
            date_received TEXT,
            installed_at TEXT,
            removed_at TEXT,
            notes TEXT,
            synced INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            part_id TEXT,
            event_type TEXT NOT NULL,
            performed_by TEXT,
            notes TEXT,
            synced INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
    """)
    con.commit()
    con.close()
```

---

## Step 2 — Backend endpoints (main.py)

### Parts
- `GET  /device-log/parts` — list all parts for this device
- `POST /device-log/parts` — add a new part
- `PUT  /device-log/parts/{id}` — update (e.g. set removed_at, add notes)

### Events
- `GET  /device-log/events` — list events, optional `?part_id=` filter
- `POST /device-log/events` — log a new event

### Sync
- `POST /device-log/sync` — manually trigger sync to Supabase
- `GET  /device-log/sync/status` — returns count of unsynced records

---

## Step 3 — Cloud sync (Supabase)

### Setup (one-time)
1. Create a Supabase project at supabase.com
2. Create `parts` and `events` tables with the same schema (minus the `synced`
   column — that's device-only)
3. Create a service role API key for the device to use
4. Add to `device.env`:
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-service-role-key
   ```

### Sync logic (background task in main.py)

```python
import httpx

async def _sync_to_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    for table in ("parts", "events"):
        rows = con.execute(
            f"SELECT * FROM {table} WHERE synced = 0"
        ).fetchall()
        if rows:
            payload = [dict(r) for r in rows]
            # remove device-only column
            for p in payload:
                p.pop("synced", None)
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{url}/rest/v1/{table}",
                    json=payload,
                    headers={**headers, "Prefer": "resolution=merge-duplicates"},
                    timeout=10
                )
            if resp.status_code in (200, 201):
                ids = [r["id"] for r in payload]
                con.execute(
                    f"UPDATE {table} SET synced=1 WHERE id IN "
                    f"({','.join('?'*len(ids))})", ids
                )
                con.commit()
    con.close()
```

Run this as a FastAPI background task every 10 minutes via `asyncio`:

```python
@app.on_event("startup")
async def start_sync_loop():
    asyncio.create_task(_sync_loop())

async def _sync_loop():
    while True:
        await asyncio.sleep(600)
        try:
            await _sync_to_supabase()
        except Exception as e:
            logger.warning("Supabase sync failed: %s", e)
```

---

## Step 4 — Frontend page (device-log.html)

Accessible from the nav at `/device-log`.

### Layout

```
┌──────────────────────────────────────────┐
│  ‹  Device Log          [nav links]      │
│  Device: SN03   Assembled: 3/5–3/27/26  │
│  Last sync: 2 min ago   [Sync Now]       │
├──────────────────────────────────────────┤
│  ▸ 2000s — Purchased Components  (2)     │
│  ▸ 3000s — Machined & Molded     (18)    │
│  ▼ 4000s — Electrical            (10)    │
│                                          │
│    AQU-4004  Meerstetter                 │
│    TEC-1089-SV-PT100 · Qty 1            │
│    Batch: Arete Provided · 3/5/26        │
│    [Edit]  [Log Event]  [Mark Removed]   │
│                                          │
│    AQU-4001  Raspberry Pi Adapter Board  │
│    AQU-4001_RB · Qty 1                  │
│    ⚠ U7 may have been stressed          │
│    [Edit]  [Log Event]  [Mark Removed]   │
│                                          │
│  ▸ 7000s — Purchased Assemblies  (2)     │
├──────────────────────────────────────────┤
│  [+ Add Part]                            │
├──────────────────────────────────────────┤
│  Event History                           │
│                                          │
│  2026-03-15  replaced  AQU-7001          │
│  Had to cut screw ourselves              │
│  Performed by: Nicole                    │
└──────────────────────────────────────────┘
```

### Behaviours
- Page loads → `GET /device-log/parts` + `GET /device-log/events`
- "+ Add" → inline form: part_type, part_name, serial, installed_at, notes
- "Mark Removed" → sets removed_at to today, moves part to a collapsed
  "Removed Parts" section
- "Log Event" → inline form: event_type dropdown, performed_by, notes
- Sync status badge shows count of unsynced records + last sync time
- "Sync Now" button → `POST /device-log/sync`
- Does NOT use WebSocket — purely REST request/response

---

## Step 5 — Nav update

Add to nav in all pages:
```html
<a class="run-nav-link" href="/device-log">Device Log</a>
```

---

## Step 6 — FastAPI route

```python
@app.get("/device-log")
async def device_log_page():
    return FileResponse(str(static_dir / "device-log.html"))
```

---

## Deployment checklist

- [ ] Create Supabase project, create tables, get API key
- [ ] Add `SUPABASE_URL` and `SUPABASE_KEY` to `device.env` on the Pi
- [ ] Add `SUPABASE_URL` and `SUPABASE_KEY` to `deployment2.sh` `device.env` block
      (as `SUPABASE_URL=` and `SUPABASE_KEY=` — values filled in per device)
- [ ] Add `httpx` to `requirements-backend.txt`
- [ ] Rebuild and push the `api` Docker image
- [ ] Restart `sentri-backend` container on the Pi

---

## What you get

| Capability | Where |
|---|---|
| Browse this device's parts | `/device-log` in kiosk |
| Log a replacement or inspection | `/device-log` in kiosk |
| See all devices' history in one place | Supabase web UI |
| Query across fleet (e.g. "all devices with part X") | Supabase SQL editor |
| Works offline | SQLite queues records, syncs when online |
| No extra server needed | Supabase is the cloud backend |

# Spec: Manual OTA Updates (No Auto-Restart)

## Problem

Watchtower is configured with `--interval 300`, which causes it to poll GHCR every 5 minutes and **immediately pull and restart containers** when a new image is found. This happens mid-run, opening the drawer and destroying an active PCR run.

## Goal

- Watchtower never acts autonomously — it only restarts containers when explicitly told to
- The app checks for new image versions in the background, without pulling
- The user sees a notification when an update is available and chooses when to apply it
- Applying an update is blocked if a run is currently active

---

## Architecture

```
Every 300s (background task in main.py):
  GET GHCR registry API → compare manifest digest to startup digest
  If different → set _update_available = True, _update_status = "available"
  (no pull, no restart, no Watchtower involved)

User opens Help → Updates tab:
  Sees "A software update is available"
  Clicks "Update Now"
  → POST /update/apply
  → Guard: reject if run is active (HTTP 409)
  → POST to Watchtower HTTP API (localhost:8081/v1/update)
  → Watchtower pulls new image and restarts containers
```

---

## What Is Already Built

### Backend (`aquila_web/main.py`, lines 1315–1479)

| Component | Status |
|-----------|--------|
| GHCR digest fetch (`_ghcr_manifest_digest`) | Done |
| Background poller (`_background_update_poller`) | Done |
| `GET /update/status` — returns available/status/last_checked | Done |
| `POST /update/check` — triggers immediate check | Done |
| `POST /update/apply` — calls Watchtower HTTP API | Done (missing run guard) |
| `POST /update/dismiss` — clears badge | Done |
| `POST /update/reset` — dev helper | Done |

### UI (`aquila_web/static/help.html`, lines 261–405)

| Component | Status |
|-----------|--------|
| "Updates" tab in Help page | Done |
| Red dot on tab when update available | Done |
| Red badge on `?` nav icon when update available | Done |
| "Check for updates" on tab open | Done |
| "Update Now" / "Later" buttons | Done |
| Error state with retry | Done |
| "Up to date" confirmation | Done |

### Infrastructure (`fleet-config/docker-compose.yml`, line 122)

| Component | Status |
|-----------|--------|
| Watchtower HTTP API enabled | Done |
| Bearer token auth | Done |
| **Remove `--interval 300`** | **NOT DONE** |

---

## Changes Required

### 1. `fleet-config/docker-compose.yml` — remove auto-poll interval

**File:** `fleet-config/docker-compose.yml`, line 122

```diff
- command: --label-enable --http-api-update --cleanup --api-version 1.54 --interval 300
+ command: --label-enable --http-api-update --cleanup --api-version 1.54
```

Without `--interval`, Watchtower sits idle and only acts when `POST /v1/update` is called. The background poller in `main.py` handles detection.

### 2. `aquila_web/main.py` — add run-active guard to `/update/apply`

The `/update/apply` endpoint must reject the request if a PCR run is currently in progress.

```python
@app.post("/update/apply")
async def apply_update():
    if <run_is_active>:   # check whatever state variable tracks active runs
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": "Cannot update during an active run. Stop the run first."}
        )
    # ... existing Watchtower POST logic
```

The UI already handles the error case (`d.ok === false` renders the error string), so no UI change needed.

---

## Behavior Spec

### Version Detection

- On startup, `_background_update_poller` runs immediately and records the current GHCR manifest digest as the **baseline** (`_startup_image_digest`).
- On each subsequent poll, it fetches the latest digest and compares to baseline.
- If digests differ → `_update_available = True`.
- Detection is passive: no image is pulled, no containers are touched.

### Notification

- `nav.js` calls `GET /update/status` on every page load.
- If `available === true` and `dismissed !== true`, a red `"1"` badge appears on the `?` nav icon.
- On the Help → Updates tab, a red dot appears on the tab button.

### Applying an Update

1. User opens Help → Updates tab.
2. Sees: *"A software update is available. Do you want to update now?"*
3. Clicks **Update Now**.
4. Frontend POSTs to `/update/apply`.
5. If a run is active → error message displayed, no restart.
6. If no run is active → Watchtower receives the trigger, pulls the new image, and restarts all labelled containers. Device reboots into the new version.

### Dismissing

- **Later** button POSTs to `/update/dismiss`.
- Badge and dot are cleared for the session.
- On next page load, `nav.js` will re-check — if update is still available and not dismissed, the badge returns.

### Error States

| Condition | Displayed As |
|-----------|-------------|
| Registry unreachable | "Could not check for updates: Registry unreachable…" + Try Again |
| Credentials not configured | "Could not check for updates: Registry credentials not configured" |
| Watchtower unreachable | "Update failed: …" + error string |
| Run is active | "Cannot update during an active run. Stop the run first." |

---

## Rollout

1. Merge compose fix → image pushed to GHCR.
2. On each existing device: `docker compose pull && docker compose up -d` (this is the last automatic-style restart — done manually once).
3. After that, all future updates are manual-only.
4. New devices deployed via `deployment2.sh` get the safe config automatically.

---

## Files Changed

| File | Change |
|------|--------|
| `fleet-config/docker-compose.yml` | Remove `--interval 300` from watchtower command |
| `aquila_web/main.py` | Add run-active guard to `apply_update()` |

# Spec: OTA Auto-Reboot + One-Time "Update Complete" Modal

**Issue:** #183 (implementation) — fixes bug #120
**Supersedes:** `specs/frontend/spec_ota_update_complete_on_reload.md` (reuses its on-disk sentinel idea; replaces the reload-based completion with a reboot + acknowledge modal)
**Related:** `specs/backend/spec_manual_ota_updates.md`, ADR-002 (Watchtower OTA), ADR-005 (kiosk host X11/Chromium)

## Problem

After a manual OTA update, the kiosk freezes indefinitely on the update/loading screen. Root causes: (1) Watchtower replaces the containers, so the old UI/API container — and the in-memory `_update_status` — is destroyed mid-update; (2) the new container boots at `_update_status = "idle"` with no memory that an update just finished; (3) `script.js` does a WebSocket-reconnect `window.location.reload()` that can destroy the polling loop. The operator's only recovery is a manual power-cycle. See #120.

## Goal

After an update completes, the device **reboots itself** (full software reboot) to guarantee a clean state across every layer (containers, X session, Chromium, hardware connections), and on the way back up shows a **one-time, blocking "Update Complete" modal** that the operator dismisses with **OK**. No manual reset required.

Decision rationale (full reboot over the lighter kiosk-relaunch or reload-only options) is recorded in ADR-016.

---

## Flow

```
1. User clicks "Update Now" (Help → Updates).
2. /update/apply (existing run-active 409 guard still applies):
     - write sentinel /opt/fleet/last_update.json  → {"state": "reboot_pending", "ts": <utc>}
     - POST Watchtower /v1/update   (existing logic)
3. Watchtower pulls new image, swaps containers.   (NO reboot here — pull in progress,
                                                     and this container is being killed)
4. NEW container starts → startup checks sentinel:
     - state == "reboot_pending":
         · rewrite sentinel → {"state": "show_complete", "ts": <utc>}   (persist BEFORE reboot)
         · (guard) only if no run active
         · POST kiosk-control /reboot   → host runs `systemctl reboot`
5. Pi reboots (~30–60s offline), Chromium relaunches → login screen.
6. Operator logs in → first post-login page loads → nav.js GET /update/status:
     - startup had read sentinel state == "show_complete" → _update_status = "complete"
     - frontend renders blocking "✓ Update Complete" modal
7. User taps OK → modal closes → POST /update/ack-complete → delete sentinel,
   reset _update_status = "idle". Shows exactly once; never loops.
```

The two-state sentinel (`reboot_pending` → `show_complete` → deleted) guarantees the device reboots **once** and the modal fires **once**. A short TTL (e.g. 10 min) on the sentinel is a belt-and-suspenders guard so a sentinel that somehow survives can't pop a stale modal days later.

---

## Backend changes (`aquila_web/main.py`)

- **Sentinel helpers** — `_write_update_sentinel(state)`, `_read_update_sentinel()`, `_clear_update_sentinel()` against `/opt/fleet/last_update.json` (host-volume path, survives container swap per ADR-002).
- **`/update/apply`** — before the Watchtower POST, write sentinel `reboot_pending`. (Existing run-active 409 guard unchanged.)
- **Startup hook** — on app start, read the sentinel:
  - `reboot_pending` → flip to `show_complete`, then (if `current_item.screen != "running"`) call kiosk-control `/reboot`. If the reboot call fails, leave `show_complete` in place and log — the modal will still show on the next (manual) reset, so behavior degrades to "no worse than today."
  - `show_complete` → set `_update_status = "complete"` (do **not** reboot again).
  - older than TTL → clear and ignore.
- **`/update/status`** — add `"complete"` to the documented states (`idle | checking | available | updating | error | complete`).
- **`POST /update/ack-complete`** — clears the sentinel and resets `_update_status = "idle"`. Called when the user taps OK.
- **`POST /reboot` proxy** — `main.py` forwards to kiosk-control `/reboot` (mirrors the existing `/wifi/*` proxy pattern via `_kiosk_post`).

## Host changes (`scripts/kiosk-control/kiosk_control.py`)

- Add **`POST /reboot`** endpoint → runs `systemctl reboot` (or `sudo reboot`). Origin-checked like the other endpoints (loopback / Docker bridge only).
- **Deployment note:** kiosk-control is a host systemd service, NOT in the Docker image. This endpoint reaches devices only via the host-service deploy path (`scripts/kiosk-control/update_host_service.sh`, `deployment2.sh`) — not via Watchtower. The first rollout must push the updated host service before auto-reboot works on a device.

## Frontend changes

- **`aquila_web/static/nav.js`** (loaded on all post-login pages) — when `/update/status` returns `status === "complete"`, render a blocking, centered "✓ Update Complete" modal with an **OK** button over a dimmed backdrop. No auto-dismiss.
- **OK handler** — close modal, `POST /update/ack-complete`. The modal does not reappear (sentinel deleted; status back to `idle`).
- **Login page** — unchanged (no `nav.js`); modal intentionally appears on the first post-login screen.
- **`aquila_web/static/script.js` WS-reconnect reload** — left as-is. The reboot makes the completion flow independent of it; out of scope unless it visibly interferes pre-reboot.

---

## Edge cases

| Case | Behavior |
|------|----------|
| Update fails (Watchtower non-200) | No sentinel state advance; existing `error` status shown; no reboot. |
| kiosk-control `/reboot` unreachable / host not yet updated | Sentinel stays `show_complete`; modal shows on next manual reset; failure logged. No worse than today. |
| Run active at reboot-trigger time | Reboot skipped (guard); a fresh post-update boot has no active run, so this is defensive. |
| Sentinel older than TTL (e.g. unrelated boot) | Ignored and cleared; no modal. |
| Power lost mid-reboot | Sentinel persists on disk; modal shows once the device next boots and the operator logs in. |

---

## Tests

- **Unit (pytest)** — sentinel state machine: `apply` writes `reboot_pending`; startup transitions `reboot_pending → show_complete` (and attempts reboot) then `show_complete → complete`; `ack-complete` clears it; TTL expiry ignored. Mock the kiosk-control call and filesystem path.
- **Contract (`tests/contract/`)** — `/update/status` returns `complete` after a simulated update; `POST /update/ack-complete` clears it; `/update/apply` still 409s during an active run.
- **Host endpoint** — `POST /reboot` on kiosk-control is hardware/host-dependent; cannot run in CI. Mark `@pytest.mark.hardware` with a note; verify the reboot subprocess is invoked via a mock, not actually executed.
- `pytest tests unit_tests -v` passes.

## Files touched

| File | Change |
|------|--------|
| `aquila_web/main.py` | Sentinel helpers; `apply` writes sentinel; startup reads + triggers reboot + sets `complete`; `/update/ack-complete`; `/reboot` proxy; `complete` status |
| `scripts/kiosk-control/kiosk_control.py` | New `POST /reboot` → `systemctl reboot` |
| `aquila_web/static/nav.js` | Blocking "Update Complete" modal on `status == complete`; OK → ack |
| `specs/frontend/spec_ota_update_complete_on_reload.md` | Mark superseded |

## Out of scope

- Lighter recovery (kiosk relaunch / reload-only) — considered and rejected; see ADR-016.
- Changing the `script.js` WS-reconnect reload.
- Persisting completion across reboots beyond the short sentinel TTL.

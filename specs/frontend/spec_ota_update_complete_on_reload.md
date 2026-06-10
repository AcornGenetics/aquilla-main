# Spec: OTA Update Complete State Survives Page Reload

## Problem

When a device update is applied, the UI shows an overlay ("Applying update…") and polls
`/update/status` every 3 seconds. The poll resolves to "Update complete" as soon as the
new container returns `status: "idle"`.

However, there is a race condition:

1. The user clicks **Update Now** → overlay appears, polling starts.
2. Watchtower kills the old container. The WebSocket drops.
3. `script.js` detects the WebSocket reconnect while `#update-overlay` is in the DOM and
   calls `window.location.reload()` (intended to clear stale overlay state).
4. The reload navigates to a fresh page — the overlay and its polling loop are destroyed.
5. The new page has no knowledge that an update just finished, so no "Update complete"
   message is ever shown. The user sees a normal page with no feedback.

This is intermittent: if the container restarts quickly and the poll fires before the
WebSocket drop is detected, the happy path succeeds. If the WebSocket reconnect fires
first, the user gets a silent reload with no completion state.

## Root Cause

`_update_status` is an in-memory Python global. When the container is replaced by
Watchtower, the new container starts with `_update_status = "idle"`. The browser has no
way to distinguish "idle because update just finished" from "idle because nothing has
happened yet" — and after a reload, it no longer even polls.

## Proposed Fix

### 1. Write a completion sentinel to disk before the container dies

In `apply_update()`, after Watchtower confirms the trigger (`r.status_code == 200`),
write a small JSON file to a volume-mounted path (e.g. `/opt/fleet/last_update.json`):

```json
{ "completed_at": "2026-06-04T18:43:10Z", "status": "complete" }
```

This file persists across container restarts because it lives on the host volume, not
in the container's ephemeral filesystem.

### 2. Read the sentinel on startup

On app startup, check for `/opt/fleet/last_update.json`. If it exists and
`completed_at` is within the last 10 minutes, set `_update_status = "complete"` (new
state) instead of `"idle"`. Clear the file after reading so it only fires once.

### 3. Add a `"complete"` status to `/update/status`

The poll in `help.html` already handles any non-`"updating"`, non-`"error"` status as
success. Adding an explicit `"complete"` state makes the contract clearer and lets the
frontend distinguish "just finished" from "never started".

### 4. On page load, check for a recent completion

In `help.html`, at page-load time (alongside the existing update-available check), call
`/update/status` once. If `status === "complete"`, render the green "✓ Update complete"
message immediately without requiring the user to have seen the overlay.

This means even if the WebSocket reload destroyed the polling loop, the next page load
correctly shows the completion state.

### 5. Remove the WebSocket-triggered reload (or scope it more narrowly)

The `window.location.reload()` in `script.js` line 610 was added to clear stale overlay
state. With the sentinel approach this is no longer needed — the overlay is correctly
resolved on reload. Remove or gate this reload so it doesn't destroy the polling loop.

## Affected Files

| File | Change |
|------|--------|
| `aquila_web/main.py` | Write sentinel on apply, read on startup, expose `"complete"` status |
| `aquila_web/static/help.html` | Poll handles `"complete"`, page-load check shows recent completion |
| `aquila_web/static/script.js` | Remove or narrow the WebSocket-reconnect reload |

## Not in Scope

- Persisting update status across reboots longer than 10 minutes (sentinel TTL is short
  by design — stale "complete" banners are confusing).
- Showing update completion on pages other than the help/updates tab.

## Acceptance Criteria

- [ ] Clicking "Update Now" and waiting always resolves to "✓ Update complete" or an
      error — never a silent reload back to normal state.
- [ ] If the browser reloads during the update (WebSocket drop or manual refresh), the
      help page shows "✓ Update complete" on the next load within 10 minutes of the
      update finishing.
- [ ] No regression: updates that fail still show an error message.
- [ ] No regression: the "no update available" flow is unchanged.

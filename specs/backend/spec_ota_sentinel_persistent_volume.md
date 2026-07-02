# Spec: Persist the OTA Reboot Sentinel Across the Container Swap

**Issue:** bugfix for the auto-reboot shipped in #183 / ADR-018
**Related:** `specs/backend/spec_ota_auto_reboot_complete.md` (the feature this fixes), ADR-002 (Watchtower OTA), `fleet-config/docker-compose.yml`

## Problem

The OTA auto-reboot never fires on a real device. The completion flow depends on an
on-disk **sentinel** (`/opt/fleet/last_update.json`) that `/update/apply` writes *before*
triggering Watchtower, and that the freshly-started container reads on startup to decide
whether to reboot the host.

The sentinel never survives the swap. Watchtower **destroys the old `aquila-backend`
container and creates a new one** from the pulled image. But the `backend` service only
bind-mounts a single file from the fleet directory:

```yaml
volumes:
  - /opt/fleet/.env:/opt/fleet/.env      # ← only the .env file, NOT the directory
```

So `/opt/fleet/last_update.json` is written into the **old container's ephemeral writable
layer**, which is thrown away when the container is recreated. The new container reads
`/opt/fleet/last_update.json`, finds nothing, `read_sentinel()` returns `None`,
`next_startup_action()` returns `"none"`, and it clears and moves on — **no reboot, ever**.

The original feature spec (`spec_ota_auto_reboot_complete.md`, "Backend changes") assumed
`/opt/fleet/last_update.json` was a "host-volume path, survives container swap per ADR-002."
That assumption was never true for the `backend` service — the mount was never added.

## Goal

Make the sentinel persist on the host across the Watchtower container swap and the reboot,
so the two-state sentinel machine (`reboot_pending` → `show_complete` → deleted) works as
designed. No change to the sentinel state-machine logic — only *where the file lives* must
be corrected.

---

## Fix

Bind-mount the fleet directory into the `backend` service so the sentinel's directory
(`/opt/fleet`) is host-backed and survives the container being recreated. Replace the
narrower `.env`-only file mount with the parent directory (the directory mount still
exposes `/opt/fleet/.env` to the container):

```yaml
# fleet-config/docker-compose.yml — services.backend.volumes
- /opt/fleet:/opt/fleet          # was: /opt/fleet/.env:/opt/fleet/.env
```

The Python default path (`AQ_UPDATE_SENTINEL_PATH`, default `/opt/fleet/last_update.json`
in `aquila_web/main.py`) is left unchanged — it becomes correct once the directory is
mounted. This keeps the fix faithful to the ADR-002 intent that the sentinel lives in the
host-managed `/opt/fleet` control directory.

Only the `backend` service needs the mount — it is the sole reader/writer of the sentinel
(`main.py`). The `app` service (`application.py`) does not touch it.

### Why the directory, not the file

A bind mount of a single file (`/opt/fleet/.env`) only persists that one file; any *other*
path under `/opt/fleet` inside the container is still ephemeral. Mounting the directory
makes the whole `/opt/fleet` tree host-backed, so `last_update.json` written by the old
container is visible to the new one.

---

## Rollout note

This is a deploy-config change, so it only takes effect for updates applied **after** a
device is already running the fixed `docker-compose.yml`. The fleet update path re-fetches
`docker-compose.yml` from the repo on each update (`scripts/deploy/fleet-update.sh`), so:

- The **first** update that carries this fix still won't auto-reboot (the currently-running
  container predates the mount).
- Every update **after** that will, because the device is now running a container that has
  `/opt/fleet` mounted.

No manual intervention is required beyond the normal update; document this one-cycle delay
so it isn't mistaken for the fix not working.

---

## Tests

- **Compose config (`tests/fleet_device/test_compose_config.py`, CI-runnable)** — the
  regression test that would have caught this:
  - The `backend` service bind-mounts a host source whose target directory contains the
    OTA sentinel path (`/opt/fleet`), i.e. the sentinel's parent directory is a bind mount,
    not just the `.env` file.
  - Asserted structurally by parsing the YAML — no Docker required.
- **Existing sentinel/state-machine tests** (`tests/unit/test_update_sentinel.py`,
  `tests/contract/test_update_complete_flow.py`, `tests/unit/test_kiosk_reboot.py`) — must
  continue to pass unchanged; this fix does not alter that logic.
- `pytest tests unit_tests -v` passes.

## Files touched

| File | Change |
|------|--------|
| `fleet-config/docker-compose.yml` | `backend` service: mount `/opt/fleet` (dir) instead of only `/opt/fleet/.env` |
| `tests/fleet_device/test_compose_config.py` | New regression test: sentinel's parent dir is bind-mounted into `backend` |

## Out of scope

- The sentinel state machine, TTL, modal, and `/reboot` proxy (all shipped in #183, unchanged).
- Moving the sentinel to a different persistent location (e.g. `/opt/aquila/...`) — keeping
  it at `/opt/fleet` per ADR-002 is the minimal, intent-faithful fix.
- The `app`/`ui`/`watchtower` services — none read the sentinel.

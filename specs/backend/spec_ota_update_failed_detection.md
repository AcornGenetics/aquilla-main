# Spec: Detect a Failed OTA Update and Show "Update Failed" (not a false "Complete")

**Issue:** fixes the false-completion bug in #183 / PR #184
**Builds on:** `specs/backend/spec_ota_auto_reboot_complete.md`, ADR-018
**Branch:** `fix/ota-update-failed-detection` → merges into `sentri-update-reset`

## Problem

The auto-reboot completion flow (#183) advances its on-disk sentinel
`reboot_pending → show_complete` on the **first container startup after an update
was triggered**, and never verifies that the new image actually booted. So if the
device crashes or loses power mid-update (e.g. during the Watchtower image pull,
before the container swap finishes), the next boot — still running the **old**
image — sees `reboot_pending`, declares success, and shows a false
"✓ Update Complete" modal. The update did not happen; the screen lies.

## Goal

On the post-update boot, **verify the running image matches the image we tried to
install** before declaring success. On a confirmed mismatch, surface a one-time,
blocking **"✗ Update Failed"** modal instead of "Update Complete". The device stays
on its old (working) image; the operator can re-trigger the update from
Help → Updates. No retry automation.

## Why the running-image digest, from the host

The container **cannot trust its own `RUNNING_IMAGE_DIGEST` env**: `/update/apply`
writes the *target* digest into `/opt/fleet/.env` **before** the swap
(`main.py`, so a restarted container picks up the right baseline even if killed
mid-swap). After a crash that env therefore reports the target regardless of what
actually booted. The only honest source of "what image is really running" is a
`docker inspect` of the running container on the host — which the privileged
`kiosk-control` systemd service can do (it already runs `docker inspect` in
`deployment2.sh`). This reuses the exact host-deploy path and proxy pattern PR #184
already introduces for `/reboot`.

## Flow

```
1. /update/apply  → sentinel {state: "reboot_pending", ts, target_digest: <api digest we are installing>}
2. New/recovery container boots, sees reboot_pending:
     running = GET kiosk-control /image-digest      (real digest of running aquila-backend)
     classify(target_digest, running):
       running == target          → "complete"  (update applied)
       running known, != target   → "failed"    (old image still here)
       target or running missing  → "unknown"   (cannot tell)
     persist next state BEFORE rebooting (fire-once, no loop):
       complete | unknown → sentinel "show_complete"   (unknown stays optimistic: no regression vs today)
       failed             → sentinel "show_failed"
     then trigger host reboot (guarded: skip if a run is active).
3. After reboot:
       show_complete → _update_status = "complete" → green "✓ Update Complete" modal
       show_failed   → _update_status = "failed"   → red  "✗ Update Failed"  modal
4. Operator taps OK:
       complete → POST /update/ack-complete  (existing)
       failed   → POST /update/ack-failed     (new) → clear sentinel, status → idle
```

The `unknown → show_complete` fallback is deliberate: if kiosk-control is
unreachable or predates the `/image-digest` endpoint (older device), we must not
flip a genuinely-successful update into a scary false "Failed". The failed modal
fires **only on a positively-confirmed mismatch**.

## Backend changes (`aquila_web/main.py`)

- `/update/apply` — record the target API digest in the sentinel:
  `write_sentinel(path, "reboot_pending", ts, target_digest=_latest_ghcr_digest)`.
- `_fetch_running_digest()` — sync best-effort `GET {KIOSK_CONTROL_URL}/image-digest`,
  returns the `api` digest string or `None` (mirrors `_trigger_host_reboot`'s error
  swallowing; never crashes startup).
- `_resolve_startup_update_state()` — on the `reboot_pending` branch, compute
  `classify_update(target, running)` and persist `show_failed` vs `show_complete`
  accordingly before rebooting. `show_failed` startup branch sets
  `_update_status = "failed"`.
- `POST /update/ack-failed` — clears the sentinel and resets `_update_status` to
  `idle` (mirror of `/update/ack-complete`).
- `/update/status` — documented states gain `failed`
  (`idle | checking | available | updating | error | complete | failed`).

## Pure logic (`aquila_web/update_sentinel.py`)

- `write_sentinel(path, state, ts, target_digest=None)` — persist `target_digest`
  when given (back-compatible; existing 3-arg callers unchanged).
- `classify_update(target_digest, running_digest) -> "complete" | "failed" | "unknown"`
  — pure comparison; `unknown` when either digest is missing/empty.
- `next_startup_action(...)` — add `show_failed → "show_failed"`.

## Host changes (`scripts/kiosk-control/kiosk_control.py`)

- **`GET /image-digest`** → `{"api": <sha256:…|null>, "ui": <sha256:…|null>}` by
  inspecting the running containers `aquila-backend` / `aquila-ui`:
  resolve the container's image id (`docker inspect --format '{{.Image}}'`), then
  read that image's `RepoDigests` and return the `@sha256:…` part. Inspecting the
  **running container's** image (not the `:tag`) is what makes this honest even if
  Watchtower pulled the new image but never recreated the container.
- Deployment note: like `/reboot`, this ships via the host-service path
  (`update_host_service.sh` / `deployment2.sh`), **not** Watchtower. On a device
  whose host service predates this endpoint, the call 404s → `unknown` → optimistic
  `show_complete` (no regression).

## Frontend changes

- **`aquila_web/static/nav.js`** — generalize the completion-modal renderer to
  handle both `status === "complete"` (green "✓ Update Complete", OK →
  `/update/ack-complete`) and `status === "failed"` (red "✗ Update Failed",
  body "The update did not finish; the device is still on its previous version.
  Please try again.", OK → `/update/ack-failed`). Blocking, no auto-dismiss.
- **`aquila_web/static/styles.css`** — add a `--failed` red variant of the modal
  title/OK button. OK button keeps the existing ≥44px touch target.

## Edge cases

| Case | Behavior |
|------|----------|
| Power lost mid-pull, old image reboots | digest mismatch → `show_failed` → "Update Failed" modal. **(the bug being fixed)** |
| Update applied cleanly | digest == target → `show_complete` → "Update Complete" (unchanged). |
| kiosk-control unreachable / host not yet updated | `unknown` → optimistic `show_complete`; no false "Failed". |
| `/image-digest` raises / docker error | treated as `None` → `unknown` → optimistic. |
| Run active at reboot-trigger time | reboot skipped (existing guard); resolved on a later boot. |
| Sentinel older than TTL | ignored & cleared (existing). |

## Tests

- **Unit (`tests/unit/test_update_sentinel.py`)** — `classify_update` complete/
  failed/unknown; `write_sentinel` round-trips `target_digest`; `next_startup_action`
  returns `show_failed`.
- **Unit (`tests/unit/test_kiosk_image_digest.py`)** — `_image_digest` parses the
  `@sha256:` out of `RepoDigests` with `docker` mocked; returns `None` on docker
  failure. `@pytest.mark.hardware`-style note: the real docker call is host-only.
- **Contract (`tests/contract/test_update_complete_flow.py`)** — a mismatch at
  `reboot_pending` advances the sentinel to `show_failed`, the boot reports
  `status == "failed"`, and `POST /update/ack-failed` clears it back to `idle`;
  an unreachable digest falls back to `show_complete`.
- `pytest tests unit_tests -v` passes.

## Files touched

| File | Change |
|------|--------|
| `aquila_web/update_sentinel.py` | `target_digest` persistence; `classify_update`; `show_failed` |
| `aquila_web/main.py` | record target digest; `_fetch_running_digest`; verify on boot; `ack-failed`; `failed` status |
| `scripts/kiosk-control/kiosk_control.py` | `GET /image-digest` |
| `aquila_web/static/nav.js` | red "Update Failed" modal branch |
| `aquila_web/static/styles.css` | `--failed` modal variant |
| `tests/unit/test_update_sentinel.py`, `tests/unit/test_kiosk_image_digest.py`, `tests/contract/test_update_complete_flow.py` | new tests |

## Out of scope

- Automatic retry of a failed update (operator re-triggers manually).
- Verifying the UI image digest (only the API/backend digest gates success here).
- Changing the reboot-on-failure behavior (kept for symmetry; see ADR-018 revisit
  conditions if the extra downtime on failure proves annoying).

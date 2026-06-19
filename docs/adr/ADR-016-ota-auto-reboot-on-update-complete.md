# ADR-016: OTA updates finish with a full device reboot + one-time completion modal

**Status:** Proposed
**Date:** 2026-06-19
**Author:** Jack Hu
**Deciders:** Jack Hu

---

## Context

Manual OTA updates (ADR-002, `spec_manual_ota_updates.md`) apply by triggering Watchtower's HTTP API, which pulls the new image and **replaces the containers**. The completion state (`_update_status`) is an in-memory Python global, so when the old container is destroyed mid-update that state is lost, and the new container boots at `idle` with no memory that an update just finished. Combined with a WebSocket-reconnect `window.location.reload()` in `script.js`, the kiosk is left frozen indefinitely on the update screen. The operator's only recovery is to manually power-cycle the device (issue #120).

An earlier proposal (`spec_ota_update_complete_on_reload.md`) addressed this *without* rebooting: write an on-disk completion sentinel, add a `complete` status, show "✓ Update complete" on the next page load, and remove the WS reload. It was never implemented.

The freeze can have causes at several layers — the Chromium browser, the X session, the Docker containers, or the serial/USB-connected PCR hardware — and we cannot always be certain which. A field-deployed diagnostic device that wedges after an update means a support call.

Two facts constrain the design:
- **The container cannot reboot its host**, but the host already runs a privileged systemd service (`kiosk_control.py`, ADR-005) that can.
- **The reboot cannot be triggered while Watchtower is pulling** (it would interrupt the download) nor by the container running `/update/apply` (that container is killed in the swap). The only safe trigger is the *new* container's startup, after the pull has finished.

If we did nothing: operators keep manually power-cycling after every update.

---

## Decision

**We will make a successful OTA update end with a full software reboot of the device (`systemctl reboot`), and surface a one-time, blocking "Update Complete" modal on the first post-login screen after the reboot.**

Concretely:
- `/update/apply` writes a two-state on-disk sentinel (`/opt/fleet/last_update.json`) that survives the container swap (ADR-002 volume).
- The new container, on startup, sees `reboot_pending`, flips the sentinel to `show_complete`, and calls a new `kiosk-control /reboot` endpoint. After the reboot, it sees `show_complete`, reports `complete`, and the frontend shows a blocking modal dismissed with **OK**, which clears the sentinel. The two states guarantee reboot-once / modal-once.
- The reboot is a **full host reboot**, chosen over the lighter alternatives below.

This is **moderately hard to reverse**: it changes fleet-wide post-update behavior operators come to rely on, and it requires a host-side service deploy (kiosk-control is not in the Watchtower-updated image), so the capability rolls out separately from container images. Implementation detail: `spec_ota_auto_reboot_complete.md`.

---

## Consequences

### Positive
- The operator no longer manually resets after an update — the device recovers itself and positively confirms completion.
- A full reboot clears *every* layer (containers, X, Chromium, hardware connections), so it is robust even against freeze causes we haven't diagnosed.
- The on-disk sentinel makes "update just completed" survive the container swap and the reboot, fixing the root cause of the lost completion state.

### Negative
- **~30–60s of total device downtime** per update while the Pi reboots (vs ~2s for a browser relaunch).
- **Boot-loop risk** if the sentinel state machine is wrong — mitigated by advancing/clearing the sentinel before rebooting and a short TTL, but it is a real hazard to get right.
- **Two-stage rollout:** the `kiosk-control /reboot` endpoint ships via the host-service deploy path, not Watchtower, so auto-reboot does not work on a device until its host service is updated. The first deployment of this feature is special-cased.
- A blocking modal reintroduces one required tap after an otherwise hands-off update (acceptable: positive confirmation on a diagnostic device).

### Neutral / Trade-offs
- Reuses the sentinel mechanism from the superseded reload spec; the difference is reboot + modal instead of reload + banner.
- The `script.js` WS-reconnect reload is left in place; the reboot makes the completion flow independent of it.

---

## Alternatives Considered

### Option A: Sentinel + reload only (the existing `spec_ota_update_complete_on_reload.md`)
**Why rejected:** Makes the completion *message* reliable but does not guarantee the frozen screen recovers — if Chromium is stuck on a dead page, nothing in the page can revive it, so the operator may still have to manually reset. Doesn't meet the "no manual reset" goal.

### Option B: Kiosk relaunch (no full reboot)
**Why rejected:** Lighter and faster (~seconds, no downtime, no boot-loop risk) and fixes the *known* browser freeze. Rejected in favor of certainty: a full reboot also clears X/Docker/hardware-level wedges we can't always rule out on a field diagnostic device. Recorded as the natural fallback if reboot downtime proves too costly.

### Option C: Literal power-cycle
**Why rejected:** Software cannot cut its own power without added relay hardware, and a warm `systemctl reboot` is cleaner (orderly shutdown, no FS-corruption risk) while achieving the same offline→online cycle.

---

## Revisit Conditions

- Reboot downtime proves disruptive in the field → switch to Option B (kiosk relaunch), reusing the same sentinel + modal.
- Auto-reboot ever causes a boot loop in practice → reassess the sentinel state machine or gate the reboot behind an explicit one-shot host flag.
- The kiosk-control host service is folded into a host-update mechanism → revisit the two-stage rollout caveat.

---

## References
- Implements: issue #183 (fixes bug #120)
- Spec: `specs/backend/spec_ota_auto_reboot_complete.md`
- Supersedes: `specs/frontend/spec_ota_update_complete_on_reload.md`
- Related ADRs: ADR-002 (Watchtower OTA + `/opt` persistence), ADR-005 (kiosk host X11/Chromium)
- `aquila_web/main.py` — OTA endpoints + startup; `scripts/kiosk-control/kiosk_control.py` — host control service

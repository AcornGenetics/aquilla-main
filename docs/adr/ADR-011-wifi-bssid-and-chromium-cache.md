# ADR-011: Prevent BSSID Pinning in WiFi Profiles and Disable Chromium Disk Cache

**Status:** Proposed
**Date:** 2026-06-11
**Author:** Nicole Cornell
**Deciders:** Nicole Cornell

---

## Context

Two related issues discovered during fleet testing:

### Issue 1 — BSSID pinning breaks hotspot reconnection

NetworkManager automatically records the BSSID (hardware MAC address) of the access point a device connected to when creating or updating a WiFi profile. Hotspots — particularly iPhone personal hotspots — rotate their BSSID when toggled off/on or when a different phone creates the hotspot. When the BSSID changes, NetworkManager refuses to connect using a profile that has the old BSSID pinned, even if the SSID and password are correct.

`wifi_recovery.sh` already clears pinned BSSIDs at boot as a workaround, but this does not protect against mid-session BSSID changes. The root fix is to never allow a BSSID to be stored in a profile in the first place.

The `_wifi_connect()` function in `kiosk_control.py` creates profiles via `nmcli connection add` without explicitly setting `802-11-wireless.bssid ""`. For open networks, it uses `nmcli device wifi connect`, which is the worst offender — it connects to a specific AP and pins its BSSID into the profile immediately.

### Issue 2 — Chromium kiosk does not show updated HTML after container image update

When the backend Docker image is updated (e.g. with UI changes to `wifi.html`), the Chromium kiosk on the device continued to render the old version of the WiFi page, even after multiple device reboots. Confirmed via `curl http://localhost:8090/wifi | grep -i forget` that the backend was serving the correct updated HTML — the issue was entirely in the Chromium layer.

Two contributing causes identified:

1. **Flag mismatch between launch paths**: The openbox autostart (set up by `deployment2.sh` at boot) passes `--user-data-dir=/tmp/chromium-kiosk`, keeping Chromium's profile in `/tmp`. The `_start_chromium()` function in `kiosk_control.py` (invoked when `POST /start-kiosk` is called mid-session) omits this flag, so Chromium falls back to the persistent `~/.config/chromium` profile, which can cache content across reboots.

2. **Potential SPA routing**: If the WiFi UI is rendered via JavaScript navigation rather than a full HTTP request to `/wifi`, cached JavaScript bundles served from `/static/` (without `Cache-Control: no-store`) could render stale UI regardless of server-side changes.

---

## Decision

**We will prevent BSSID storage at the point of profile creation and unify Chromium's launch flags across both paths.**

### Changes required:

**1. `scripts/kiosk-control/kiosk_control.py` — `_wifi_connect()`**
- Add `"802-11-wireless.bssid", ""` to the `nmcli connection add` call for secured networks
- After `nmcli connection up`, add `nmcli connection modify {ssid} 802-11-wireless.bssid ""` to clear any BSSID NetworkManager auto-writes on connect
- Replace the open-network `nmcli device wifi connect` path with an explicit `nmcli connection add ... ssid {ssid}` + `connection up` + `connection modify bssid ""` sequence

**2. `scripts/deploy/deployment2.sh` — NetworkManager dispatcher**
- Add a NetworkManager dispatcher script to `/etc/NetworkManager/dispatcher.d/99-no-bssid` that runs `nmcli connection modify $CONNECTION_ID 802-11-wireless.bssid ""` on every `up` event — OS-level safety net that clears BSSID regardless of which code path created the profile

**3. `scripts/kiosk-control/kiosk_control.py` — `_start_chromium()`**
- Add `--user-data-dir=/tmp/chromium-kiosk` to match the openbox autostart (line 272 of `deployment2.sh`)
- Add `--disk-cache-size=0` to both `_start_chromium()` and the openbox autostart in `deployment2.sh`

**Open question:** Confirm whether navigating to the WiFi page in the kiosk triggers a full HTTP request to `/wifi` or a SPA JavaScript navigation. If SPA, static JS files in `/static/` must also be served with `Cache-Control: no-store`.

`wifi_recovery.sh` boot-time BSSID cleanup is retained as a third safety net.

---

## Consequences

### Positive
- Hotspot reconnection works reliably mid-session and across reboots regardless of BSSID rotation
- UI changes in the backend image are visible in the kiosk immediately after the container restarts — no stale renders
- Chromium kiosk launch is consistent whether triggered by boot (openbox) or by `POST /start-kiosk` (kiosk-control API)

### Negative
- `--disk-cache-size=0` means Chromium fetches all assets from the backend on every page load — minor increase in backend traffic, acceptable for a local kiosk on localhost

### Neutral / Tradeoffs
- `wifi_recovery.sh` becomes redundant for BSSID clearing but is kept as a backstop — removing it is a separate decision

---

## Alternatives Considered

### Option A: Boot-time BSSID clearing only (current state via `wifi_recovery.sh`)
**Why rejected:** Does not protect against mid-session BSSID changes when a hotspot is toggled while the Pi is running.

### Option B: Chromium `--incognito` alone (already present)
**Why rejected:** Incognito prevents session cookie persistence but does not guarantee no-cache behaviour for resources served without explicit `no-store` headers. The persistent `~/.config/chromium` fallback in `_start_chromium()` also undermines this.

---

## Revisit Conditions

- If NetworkManager changes its behaviour around automatic BSSID recording in a future version, the dispatcher may become unnecessary
- If the app moves to a fully offline-capable PWA with a service worker, cache invalidation strategy must be redesigned

---

## References

- Related ADRs: ADR-002 (Watchtower fleet updates), ADR-005 (kiosk host X11 Chromium)
- `scripts/kiosk-control/kiosk_control.py` — `_wifi_connect()` (line 201), `_start_chromium()` (line 93)
- `scripts/deploy/deployment2.sh` — openbox autostart block (line 255), NetworkManager dispatcher (to be added)
- `scripts/setup/wifi_recovery.sh` — existing boot-time BSSID cleanup (retained)

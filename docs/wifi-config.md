# WiFi Configuration — Implementation Plan (Option A: D-Bus + nmcli)

## Overview

Add an in-kiosk WiFi settings page so the device can join a new network without
exiting the GUI. The backend container calls `nmcli` via subprocess after gaining
access to the host NetworkManager through the D-Bus socket.

---

## Architecture Decision: D-Bus in Docker vs. kiosk-control proxy

There are two valid approaches. Choose one before starting.

### Option A: Mount D-Bus socket into the backend container (original plan)
- Requires rebuilding the Docker image (Dockerfile.api change)
- Requires updating fleet-config/docker-compose.yml
- `nmcli` runs inside the container over the host D-Bus socket
- More self-contained — all WiFi logic lives in the backend

### Option B: Add WiFi commands to the kiosk-control host service (simpler)
- No Dockerfile changes needed
- No D-Bus socket mounting needed
- The `kiosk-control` service already runs as root on the host and can call `nmcli` directly
- The backend proxies requests to `127.0.0.1:9191/wifi/...`
- WiFi endpoints added to `scripts/kiosk-control/kiosk_control.py`

**Recommendation:** Option B is simpler for the current deployment since kiosk-control
already exists and runs on the host with root access. Use Option A if you want all
logic in the container long-term.

---

## Prerequisites — Verify on Pi before starting

Run these on the Pi to confirm which network stack is in use:

```bash
# Confirm NetworkManager is running (Pi OS Bookworm uses this)
nmcli general status

# Confirm D-Bus socket exists (needed for Option A)
ls /run/dbus/system_bus_socket

# Confirm Pi OS version
cat /etc/os-release
```

**If `nmcli` is not found**, the Pi is using `dhcpcd` + `wpa_supplicant` (Bullseye or
older). In that case the command layer in Step 3 must use `wpa_cli` instead of `nmcli`.
The endpoint contract (same URLs, same request/response shapes) stays the same —
only the subprocess calls change.

**Expected output on Bookworm with NetworkManager:**
```
STATE      CONNECTIVITY  WIFI-HW  WIFI     WWAN-HW  WWAN
connected  full          enabled  enabled  missing  missing
```

---

## Step 1 — Dockerfile.api (Option A only)

Add `network-manager` to the apt install block so `nmcli` is available inside the
container image.

**File:** `docker/Dockerfile.api`

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    procps \
    network-manager \
    && rm -rf /var/lib/apt/lists/*
```

Skip this step if using Option B.

---

## Step 2 — docker-compose.yml (Option A only)

Mount the host D-Bus socket into the backend container and add `NET_ADMIN`
capability so `nmcli` can issue network commands.

**File:** `fleet-config/docker-compose.yml` — `backend` service

Add under `volumes`:
```yaml
- /run/dbus/system_bus_socket:/run/dbus/system_bus_socket
```

Add under the service:
```yaml
cap_add:
  - NET_ADMIN
environment:
  DBUS_SYSTEM_BUS_ADDRESS: "unix:path=/run/dbus/system_bus_socket"
```

Full diff of the backend service block:
```yaml
backend:
  ...
  cap_add:
    - NET_ADMIN
  environment:
    ...
    DBUS_SYSTEM_BUS_ADDRESS: "unix:path=/run/dbus/system_bus_socket"
  volumes:
    - /opt/aquila/results:/opt/aquila/results
    - /opt/aquila/logs:/opt/aquila/logs
    - /opt/aquila/profiles:/opt/aquila/profiles
    - /opt/aquila/config:/opt/aquila/config
    - /run/dbus/system_bus_socket:/run/dbus/system_bus_socket  # <-- add
```

Skip this step if using Option B.

---

## Step 3 — Backend endpoints (main.py)

Add four new endpoints. All call `nmcli` via `subprocess.run` with
`capture_output=True`.

### Helper function
```python
import subprocess

def _run_nmcli(*args) -> tuple[int, str, str]:
    result = subprocess.run(
        ["nmcli", "--terse", "--colors", "no", *args],
        capture_output=True, text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()
```

### GET /wifi/status
Returns current connection state.
```python
@app.get("/wifi/status")
async def wifi_status():
    code, out, err = _run_nmcli("-f", "ACTIVE,SSID,SIGNAL,SECURITY",
                                 "device", "wifi")
    # Parse output, return {connected: bool, ssid: str, signal: int}
```

### GET /wifi/scan
Triggers a rescan and returns nearby networks.
```python
@app.get("/wifi/scan")
async def wifi_scan():
    _run_nmcli("device", "wifi", "rescan")
    await asyncio.sleep(2)  # wait for scan
    code, out, err = _run_nmcli("-f", "SSID,SIGNAL,SECURITY,IN-USE",
                                 "device", "wifi", "list")
    # Parse and return list of {ssid, signal, secured, in_use}
```

### POST /wifi/connect
```python
class WifiConnect(BaseModel):
    ssid: str
    password: str

@app.post("/wifi/connect")
async def wifi_connect(body: WifiConnect):
    code, out, err = _run_nmcli("device", "wifi", "connect", body.ssid,
                                 "password", body.password)
    return {"ok": code == 0, "error": err if code != 0 else None}
```

### POST /wifi/forget
```python
class WifiForget(BaseModel):
    ssid: str

@app.post("/wifi/forget")
async def wifi_forget(body: WifiForget):
    code, out, err = _run_nmcli("connection", "delete", body.ssid)
    return {"ok": code == 0}
```

---

## Step 4 — Frontend: wifi.html

New static page at `sentri_web/static/wifi.html`.

### Layout
```
┌─────────────────────────────────────────┐
│  ‹  WiFi Settings         [nav links]   │
├─────────────────────────────────────────┤
│  Current: ● Acorn_Lab_5G  (signal 82%)  │
│  [Rescan]                               │
├─────────────────────────────────────────┤
│  Available Networks                     │
│  ▓▓▓▓  Acorn_Lab_5G         ✓ connected │
│  ▓▓▓░  GuestNetwork         🔒          │
│  ▓▓░░  Neighbor_2.4                     │
│                                         │
│  [tap network → password field appears] │
│  Password: [____________] [👁]          │
│            [Connect]                    │
└─────────────────────────────────────────┘
```

### Key UI behaviours
- Page loads → immediately calls `GET /wifi/status` to show current network
- "Rescan" button → calls `GET /wifi/scan` (shows spinner, ~3s)
- Tap a network row → expands inline password field + Connect button
- Connect button → calls `POST /wifi/connect`, shows spinner
- On success: row updates to show ✓ connected, status bar refreshes
- On failure: inline error message ("Wrong password", "Network not found")
- Password field has show/hide toggle (eye icon)
- Open networks (no 🔒) skip the password field

### Does NOT load script.js (no WebSocket needed — WiFi is purely request/response)

---

## Step 5 — Placement: Help page (for now)

Rather than adding a WiFi link to every nav bar immediately, add a **WiFi Settings**
section and link inside `help.html` only. This keeps the scope small and lets the
feature be tested before promoting it to the main nav.

**In `sentri_web/static/help.html`** — add to the sidebar nav:
```html
<a href="/wifi">WiFi Settings</a>
```

**Add a new section** at the bottom of the help content:
```html
<section id="help-wifi">
  <h2>WiFi Settings</h2>
  <p>To connect this device to a new network, tap <strong>WiFi Settings</strong>
     in the sidebar. You can scan for available networks, enter a password,
     and connect without leaving the kiosk.</p>
  <a href="/wifi" class="btn">Open WiFi Settings →</a>
</section>
```

### Promoting to the main nav later

When ready to add WiFi to all pages, add to the nav in each of these files:
```html
<a class="run-nav-link" href="/wifi">WiFi</a>
```

Pages to update:
- `sentri_web/static/run.html`
- `sentri_web/static/help.html`
- `sentri_web/static/history.html`
- `sentri_web/static/history_detail.html`
- `sentri_web/static/profiles.html`
- `sentri_web/static/profiles/index.html`
- `sentri_web/static/profiles/edit.html`

---

## Step 6 — FastAPI route for the page

Add to `main.py`:
```python
@app.get("/wifi")
async def wifi_page():
    return FileResponse(str(static_dir / "wifi.html"))
```

---

## Deployment checklist

- [ ] SSH into Pi and run `nmcli general status` to confirm NetworkManager is active
- [ ] Decide: Option A (D-Bus in Docker) or Option B (kiosk-control proxy)
- [ ] If Option A: rebuild and push the `api` image (`docker build -f docker/Dockerfile.api`)
- [ ] If Option A: update `/opt/fleet/docker-compose.yml` with D-Bus socket mount
- [ ] If Option B: add WiFi handlers to `scripts/kiosk-control/kiosk_control.py`
- [ ] Add 4 WiFi endpoints to `sentri_web/main.py`
- [ ] Create `sentri_web/static/wifi.html`
- [ ] Add WiFi link/section to `sentri_web/static/help.html`
- [ ] Add FastAPI `/wifi` route to `main.py`
- [ ] Restart the stack: `docker compose -f /opt/fleet/docker-compose.yml up -d`
- [ ] Confirm `nmcli` runs inside the container (Option A): `docker exec aquila-backend nmcli general status`
- [ ] Test scan, connect, and forget flows on device

---

## Risk / notes

| Risk | Mitigation |
|---|---|
| Connecting to a new network drops the current one briefly | Show warning: "Device will reconnect — page may reload" |
| Wrong password leaves device on old network | `nmcli` returns non-zero; show error, device stays connected |
| D-Bus socket path differs on some Pi OS versions | Check `/run/dbus/system_bus_socket` vs `/var/run/dbus/system_bus_socket` |
| NetworkManager not installed (Bullseye) | Fall back to `wpa_cli` command layer — same endpoint contract, different subprocess calls |
| Connecting to a network with no internet kicks the Pi off fleet monitoring | Out of scope — user responsibility |
| Password sent as plain text over localhost HTTP | Acceptable for local kiosk — not exposed externally |

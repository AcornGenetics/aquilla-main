# WiFi Configuration — Implementation Plan (Option A: D-Bus + nmcli)

## Overview

Add an in-kiosk WiFi settings page so the device can join a new network without
exiting the GUI. The backend container calls `nmcli` via subprocess after gaining
access to the host NetworkManager through the D-Bus socket.

---

## Prerequisites (verify on Pi before starting)

```bash
# Confirm NetworkManager is running
nmcli general status

# Confirm D-Bus socket exists
ls /run/dbus/system_bus_socket

# Confirm Pi OS version
cat /etc/os-release
```

If `nmcli` is not found, the Pi is using `dhcpcd` + `wpa_supplicant` (Bullseye or
older) and the command layer in Step 3 will need to use `wpa_cli` instead.

---

## Step 1 — Dockerfile.api

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

---

## Step 2 — docker-compose.yml (fleet-config)

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

New static page at `aquila_web/static/wifi.html`.

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

## Step 5 — Nav update

Add a WiFi link to the nav in every page that has a nav bar:

```html
<a class="run-nav-link" href="/wifi">WiFi</a>
```

Pages to update:
- `aquila_web/static/run.html`
- `aquila_web/static/help.html`
- `aquila_web/static/history.html`
- `aquila_web/static/history_detail.html`
- `aquila_web/static/profiles.html`
- `aquila_web/static/profiles/index.html`
- `aquila_web/static/profiles/edit.html`

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

- [ ] Verify `nmcli general status` works on Pi before building
- [ ] Rebuild and push the `api` image (`docker build -f docker/Dockerfile.api`)
- [ ] Update `/opt/aquila/config/device.env` if needed
- [ ] Restart with updated `fleet-config/docker-compose.yml`
- [ ] Confirm `nmcli` runs inside the container: `docker exec aquila-backend nmcli general status`
- [ ] Test scan, connect, and forget flows

---

## Risk / notes

| Risk | Mitigation |
|---|---|
| Connecting to a new network drops the current one briefly | Show warning: "Device will reconnect — page may reload" |
| Wrong password leaves device on old network | `nmcli` returns non-zero; show error, device stays connected |
| D-Bus socket path differs on some Pi OS versions | Check `/run/dbus/system_bus_socket` vs `/var/run/dbus/system_bus_socket` |
| NetworkManager not installed (Bullseye) | Fall back to `wpa_cli` command layer — same endpoint contract, different subprocess calls |
| Connecting to a network with no internet kicks the Pi off fleet monitoring | Out of scope — user responsibility |

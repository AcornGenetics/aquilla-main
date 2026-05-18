# Exit GUI Button Fix Plans

**Version:** 1.1.1
**Branch:** profile-pipline
**Date:** 2026-04-21

---

## Diagnosis

The exit button has a **two-step flow** in `aquila_web/static/script.js:674-698`:

1. `POST /button/exit` → FastAPI backend (sets `exit_button = True`) — **works fine**
2. `POST /kiosk-control/exit-kiosk` → nginx proxy → host kiosk-control service (actually kills Chromium) — **broken**

**Root cause:** `docker/nginx.conf` is missing the `/kiosk-control/` proxy location block. There is already a ready-made block in `scripts/kiosk-control/nginx-kiosk-proxy.conf` — it was never merged into the active nginx config used by the Docker UI container.

Additionally, neither Docker service in `docker/docker-compose.yml` has `extra_hosts: host.docker.internal:host-gateway`, which on Linux/Pi is **required** for `host.docker.internal` to resolve inside containers.

**Result:** Step 2 silently fails (404), Chromium is never killed, and the exit button appears to do nothing.

---

## Plan 1 — Fix the Nginx Proxy (Intended Design)

This is what the architecture was designed for. The comment in `nginx-kiosk-proxy.conf` literally says: *"Add this location block to the server{} block in your UI container's nginx config."*

### Files to change

**`docker/nginx.conf`** — insert before the catch-all `location /` block:

```nginx
location /kiosk-control/ {
    limit_except POST { deny all; }
    proxy_pass         http://host.docker.internal:9191/;
    proxy_http_version 1.1;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_read_timeout 10s;
    proxy_connect_timeout 5s;
}
```

**`docker/docker-compose.yml`** — add `extra_hosts` to the `ui` service:

```yaml
ui:
  extra_hosts:
    - "host.docker.internal:host-gateway"
```

### Pros
- Matches the existing intended architecture
- No backend code changes

### Cons
- Requires rebuilding and pushing the UI Docker image (uses a container slot)
- Still depends on `host.docker.internal` resolving and kiosk-control systemd service being healthy

---

## Plan 2 — Backend Proxies the Exit Call (Recommended)

The backend already has `httpx`, `_kiosk_post()`, and `KIOSK_CONTROL_URL` — it uses the exact same pattern to proxy WiFi calls to the kiosk-control service. This just adds one call inside the existing `/button/exit` handler.

### Files to change

**`aquila_web/main.py`** — add kiosk-control forwarding inside `button_exit()` (`main.py:794`):

```python
@app.post("/button/exit")
async def button_exit():
    global exit_button, sim_exit_pending
    exit_button = True
    logger.info("exit button pressed")
    try:
        await _kiosk_post("/exit-kiosk", {})
    except Exception as e:
        logger.warning("kiosk-control exit failed: %s", e)
    if DEV_SIMULATE:
        ...
    return {"ok": True}
```

**`docker/docker-compose.yml`** — add `extra_hosts` to the `backend` service:

```yaml
backend:
  extra_hosts:
    - "host.docker.internal:host-gateway"
```

**`aquila_web/static/script.js`** — simplify `notifyExit()` to remove the second fetch, since the backend now handles it. The single `POST /button/exit` does everything:

```js
async function notifyExit() {
    try {
        await fetch("/button/exit", { method: "POST" });
    } catch (err) {
        console.warn("notifyExit backend signal failed", err);
    }
}
```

### Pros
- Only requires a backend image rebuild (no UI image rebuild — saves a container slot)
- Infrastructure (`_kiosk_post`, `KIOSK_CONTROL_URL`, `httpx`) is already present and proven working for WiFi
- If WiFi is working, this will work

### Cons
- Requires `extra_hosts` to work; same `host.docker.internal` dependency
- Backend now handles two responsibilities on exit press

---

## Plan 3 — Shared File IPC (No HTTP, Most Reliable)

Bypass Docker networking entirely. The backend writes a sentinel file to a shared host-mounted volume; a lightweight host-side watcher script detects it and kills Chromium. No `host.docker.internal`, no proxy, no port dependencies.

### Files to change

**`docker/docker-compose.yml`** — add shared IPC volume to the `backend` service:

```yaml
backend:
  volumes:
    - /tmp/aquila-ipc:/tmp/aquila-ipc   # add alongside existing volumes
```

**`aquila_web/main.py`** — write sentinel file in `button_exit()`:

```python
import pathlib
IPC_DIR = pathlib.Path(os.getenv("IPC_DIR", "/tmp/aquila-ipc"))

@app.post("/button/exit")
async def button_exit():
    global exit_button, sim_exit_pending
    exit_button = True
    logger.info("exit button pressed")
    try:
        IPC_DIR.mkdir(exist_ok=True)
        (IPC_DIR / "exit_requested").touch()
    except Exception as e:
        logger.warning("IPC file write failed: %s", e)
    if DEV_SIMULATE:
        ...
    return {"ok": True}
```

**`aquila_web/static/script.js`** — simplify `notifyExit()` (same as Plan 2, remove second fetch).

**Host-side watcher** — add to `deployment2.sh` or a new systemd unit. Simple polling loop:

```bash
#!/bin/bash
# /usr/local/bin/aquila-exit-watcher.sh
# Watches for exit signal written by the Docker backend container
while true; do
    if [ -f /tmp/aquila-ipc/exit_requested ]; then
        rm -f /tmp/aquila-ipc/exit_requested
        pkill -TERM -f chromium || true
    fi
    sleep 1
done
```

### Pros
- Works even if all Docker networking is misconfigured
- No `host.docker.internal` dependency
- Survives container restarts
- Only backend image rebuild needed

### Cons
- Requires host-side watcher setup via deployment script
- 1-second polling delay (imperceptible in practice)
- More moving parts to set up initially

---

## Recommendation

**Start with Plan 2.** It is the smallest diff, requires only a backend image rebuild, and reuses infrastructure that is already proven working (WiFi proxying uses the same `_kiosk_post` + `KIOSK_CONTROL_URL` pattern).

If `host.docker.internal` turns out to be unreliable on the Pi, fall back to **Plan 3** — it is the most networking-independent option and will work regardless of Docker network configuration.

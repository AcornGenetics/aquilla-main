#!/usr/bin/env python3
"""
kiosk_control.py — Host-side control service for Chromium kiosk management.

Runs as a systemd service on the Pi host (NOT inside Docker).
Listens only on 127.0.0.1:9191 so it is reachable by Docker containers via
host.docker.internal (requires --add-host=host.docker.internal:host-gateway in
docker-compose) but NOT reachable from the network.

Endpoints:
    POST /exit-kiosk     — kill the Chromium kiosk process
    POST /start-kiosk    — launch Chromium in kiosk mode
    GET  /health         — liveness check
    GET  /wifi/status    — current WiFi connection info
    GET  /wifi/scan      — scan for available networks
    POST /wifi/connect   — connect to a network  {ssid, password}
    POST /wifi/forget    — forget a saved network {ssid}
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------------------
# Configuration — edit these to match your deployment
# ---------------------------------------------------------------------------

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.environ.get("KIOSK_CONTROL_PORT", "9191"))

# URL Chromium should open in kiosk mode.
# deployment2.sh points Chromium at :8090 (the backend directly).
KIOSK_URL = os.environ.get("KIOSK_URL", "http://localhost:8090")

# User that runs the desktop session (needed for DISPLAY/XAUTHORITY env vars
# when launching Chromium)
KIOSK_USER = os.environ.get("KIOSK_USER", "pi")

# Chromium binary name — deployment2.sh installs "chromium" (not chromium-browser)
CHROMIUM_BIN = os.environ.get("CHROMIUM_BIN", "chromium")

# Allowed caller IPs — Docker bridge + loopback.
# 172.17.0.0/16 covers the default Docker bridge; tighten if you use a custom
# network with a known gateway (e.g. 172.20.0.1).
ALLOWED_PREFIXES = ("127.", "172.17.", "172.18.", "172.19.", "172.20.", "10.")

# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("kiosk-control")


def _is_allowed(addr: str) -> bool:
    return any(addr.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _kill_chromium() -> tuple[bool, str]:
    """Send SIGTERM to every kiosk browser process (Chromium or kiosk.py WebKit)."""
    patterns = [CHROMIUM_BIN, "chromium", "kiosk.py"]
    killed_any = False
    for pattern in patterns:
        result = subprocess.run(
            ["pkill", "-TERM", "-f", pattern],
            capture_output=True,
        )
        if result.returncode == 0:
            killed_any = True
    if not killed_any:
        return True, "no kiosk process found"
    # Launch desktop on the existing X session.
    # Use su -c so the process runs as pi with its own environment.
    xauth = f"/home/{KIOSK_USER}/.Xauthority"
    desktop_env = f"DISPLAY=:0 XAUTHORITY={xauth} HOME=/home/{KIOSK_USER}"
    for app in ["pcmanfm --desktop", "lxpanel --profile LXDE", "nm-applet"]:
        subprocess.Popen(
            ["su", "-c", f"{desktop_env} {app}", KIOSK_USER],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return True, "kiosk terminated"


def _start_chromium() -> tuple[bool, str]:
    """Launch Chromium in kiosk mode as the kiosk user (X11)."""
    env = os.environ.copy()
    env["DISPLAY"] = ":0"
    env["XAUTHORITY"] = f"/home/{KIOSK_USER}/.Xauthority"

    chromium_flags = [
        "--kiosk",
        "--incognito",
        "--noerrdialogs",
        "--disable-infobars",
        "--disable-session-crashed-bubble",
        "--check-for-update-interval=31536000",
        "--disable-pinch",
        "--overscroll-history-navigation=0",
        "--disable-features=TranslateUI",
        "--touch-events=enabled",
        "--enable-touch-drag-drop",
        "--enable-gpu-rasterization",
        "--use-angle=gles",
        "--ozone-platform=x11",
        "--start-maximized",
        KIOSK_URL,
    ]

    if os.geteuid() == 0:
        cmd = ["sudo", "-u", KIOSK_USER, "-E", CHROMIUM_BIN] + chromium_flags
    else:
        cmd = [CHROMIUM_BIN] + chromium_flags

    subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, "chromium launched"


# ---------------------------------------------------------------------------
# WiFi helpers (nmcli)
# ---------------------------------------------------------------------------

def _nmcli(*args) -> tuple[int, str, str]:
    result = subprocess.run(
        ["nmcli", "--terse", "--colors", "no", *args],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _wifi_status() -> dict:
    code, out, err = _nmcli("-f", "ACTIVE,SSID,SIGNAL,SECURITY", "device", "wifi")
    if code != 0:
        return {"connected": False, "ssid": None, "signal": None, "error": err}
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0] == "yes":
            ssid = parts[1]
            signal = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
            return {"connected": True, "ssid": ssid, "signal": signal}
    return {"connected": False, "ssid": None, "signal": None}


def _wifi_scan() -> list:
    _nmcli("device", "wifi", "rescan")
    time.sleep(3)
    code, out, err = _nmcli("-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list")
    networks = []
    seen = set()
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        ssid, signal, security, in_use = parts[0], parts[1], parts[2], parts[3]
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        networks.append({
            "ssid": ssid,
            "signal": int(signal) if signal.isdigit() else 0,
            "secured": bool(security and security != "--"),
            "in_use": in_use.strip() == "*",
        })
    networks.sort(key=lambda n: n["signal"], reverse=True)
    return networks


def _wifi_connect(ssid: str, password: str) -> dict:
    if password:
        code, out, err = _nmcli("device", "wifi", "connect", ssid, "password", password)
    else:
        code, out, err = _nmcli("device", "wifi", "connect", ssid)
    return {"ok": code == 0, "error": err if code != 0 else None}


def _wifi_forget(ssid: str) -> dict:
    code, out, err = _nmcli("connection", "delete", ssid)
    return {"ok": code == 0, "error": err if code != 0 else None}


# ---------------------------------------------------------------------------

class KioskHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler — no external dependencies required."""

    def log_message(self, fmt, *args):  # suppress default access log spam
        log.info("request from %s: %s", self.client_address[0], fmt % args)

    def _check_origin(self) -> bool:
        addr = self.client_address[0]
        if not _is_allowed(addr):
            log.warning("rejected request from %s", addr)
            self._respond(403, {"error": "forbidden"})
            return False
        return True

    def _respond(self, code: int, body: dict) -> None:
        import json
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"ok": True})
        elif self.path == "/wifi/status":
            self._respond(200, _wifi_status())
        elif self.path == "/wifi/scan":
            networks = _wifi_scan()
            self._respond(200, {"networks": networks})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if not self._check_origin():
            return

        if self.path == "/exit-kiosk":
            ok, msg = _kill_chromium()
            log.info("exit-kiosk: %s", msg)
            self._respond(200 if ok else 500, {"ok": ok, "message": msg})

        elif self.path == "/start-kiosk":
            ok, msg = _start_chromium()
            log.info("start-kiosk: %s", msg)
            self._respond(200 if ok else 500, {"ok": ok, "message": msg})

        elif self.path == "/wifi/connect":
            body = self._read_json_body()
            ssid = body.get("ssid", "").strip()
            password = body.get("password", "").strip()
            if not ssid:
                self._respond(400, {"ok": False, "error": "ssid required"})
                return
            log.info("wifi/connect: ssid=%s", ssid)
            result = _wifi_connect(ssid, password)
            self._respond(200 if result["ok"] else 500, result)

        elif self.path == "/wifi/forget":
            body = self._read_json_body()
            ssid = body.get("ssid", "").strip()
            if not ssid:
                self._respond(400, {"ok": False, "error": "ssid required"})
                return
            log.info("wifi/forget: ssid=%s", ssid)
            result = _wifi_forget(ssid)
            self._respond(200 if result["ok"] else 500, result)

        else:
            self._respond(404, {"error": "not found"})


def main():
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), KioskHandler)
    log.info("kiosk-control listening on %s:%d", LISTEN_HOST, LISTEN_PORT)

    def _shutdown(signum, frame):
        log.info("shutting down")
        server.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    server.serve_forever()


if __name__ == "__main__":
    main()
